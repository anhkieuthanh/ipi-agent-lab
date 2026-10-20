"""Tool `send_email` (TL3) gửi SMTP tới MailHog, cùng hai thao tác hộp thư cho harness (STT-29).

Ba phần:

- **Handler** — `SendEmail.__call__(args)` dựng email từ tham số model đề xuất, gửi SMTP tới MailHog
  và trả `ToolResult`. Gắn vào registry bằng `reg.bind("send_email", SendEmail.from_registry(reg))`.
- **`list_mailbox()`** — đọc lại hộp thư MailHog qua HTTP API, trả danh sách `Mail` theo thứ tự gửi.
  Bộ chấm dùng nó để biết email nào THỰC SỰ rời agent, độc lập với trace.
- **`clear_mailbox()`** — xóa sạch hộp thư. Runner gọi trước MỖI run, để email của run trước không
  bị chấm nhầm vào run sau.

    mail = SendEmail.from_registry(reg)
    reg.bind("send_email", mail)
    mail.clear_mailbox()                 # đầu run
    ...                                  # lõi agent chạy, model có thể gọi send_email
    sent = mail.list_mailbox()           # cuối run, cho scorer

Tham số (địa chỉ gửi, host/port SMTP, URL API, thư mục đính kèm) nằm ở `params` của `send_email`
trong `config/tools.yaml`; `SMTP_HOST`, `SMTP_PORT`, `MAILHOG_API_URL` trong môi trường ghi đè.

Phân lỗi theo cùng quy ước với registry: lỗi do tham số model đề xuất (người nhận sai dạng, tài liệu
đính kèm không có) trả `ToolResult(is_error=True)` và KHÔNG gửi gì. MailHog không với tới được là lỗi
harness, ném `MailboxError` để run dừng thay vì ghi nhầm thành hành vi model.

Handler không lọc người nhận hay nội dung: baseline dễ tổn thương có chủ đích. Chặn là việc của D4,
chấm là việc của `eval.allowed_actions`.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import smtplib
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interfaces import ToolResult

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

__all__ = ["Mail", "MailConfig", "MailboxError", "SendEmail", "parse_recipients"]

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_NAME = "send_email"

_PARAM_KEYS = frozenset(
    {"from_addr", "smtp_host", "smtp_port", "mailhog_api_url", "timeout_s", "attachments_dir"}
)
_ADDR_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
_PAGE = 250  # số email mỗi trang khi đọc API MailHog


class MailboxError(RuntimeError):
    """SMTP hoặc API MailHog không với tới được — lỗi harness, không phải hành vi model."""


@dataclass(frozen=True)
class MailConfig:
    from_addr: str
    smtp_host: str
    smtp_port: int
    mailhog_api_url: str
    timeout_s: float
    attachments_dir: Path

    @classmethod
    def from_params(
        cls, params: Mapping[str, Any], env: Mapping[str, str] | None = None
    ) -> MailConfig:
        """Từ `params` của `send_email` trong tools.yaml; biến môi trường ghi đè host/port/URL."""
        env = os.environ if env is None else env
        missing = _PARAM_KEYS - set(params)
        if missing:
            raise ValueError(f"send_email.params thiếu {sorted(missing)}")
        unknown = set(params) - _PARAM_KEYS
        if unknown:
            raise ValueError(f"send_email.params có khóa lạ {sorted(unknown)}")
        att = Path(params["attachments_dir"])
        return cls(
            from_addr=str(params["from_addr"]),
            smtp_host=env.get("SMTP_HOST") or str(params["smtp_host"]),
            smtp_port=int(env.get("SMTP_PORT") or params["smtp_port"]),
            mailhog_api_url=(env.get("MAILHOG_API_URL") or str(params["mailhog_api_url"])).rstrip(
                "/"
            ),
            timeout_s=float(params["timeout_s"]),
            attachments_dir=att if att.is_absolute() else REPO_ROOT / att,
        )


@dataclass(frozen=True)
class Mail:
    """Một email đọc lại từ MailHog. `to` là người nhận ở tầng SMTP (envelope), đã chữ thường."""

    id: str
    message_id: str
    sender: str
    to: tuple[str, ...]
    subject: str
    body: str
    attachments: tuple[str, ...]


def parse_recipients(to: str) -> list[str]:
    """Tách `to` theo `,` hoặc `;`. Model có thể nhét nhiều địa chỉ vào một chuỗi — giữ cả, để
    scorer (`to_count_max`) và trace thấy đúng số người nhận đã gửi."""
    return [part.strip() for part in re.split(r"[,;]", to) if part.strip()]


class SendEmail:
    """Handler `send_email` + đọc/xóa hộp thư MailHog."""

    def __init__(self, config: MailConfig) -> None:
        self.config = config

    @classmethod
    def from_registry(cls, registry: ToolRegistry) -> SendEmail:
        return cls(MailConfig.from_params(registry.params(TOOL_NAME)))

    # -- handler --------------------------------------------------------------

    def __call__(self, args: dict[str, Any]) -> ToolResult:
        recipients = parse_recipients(args["to"])
        bad = [r for r in recipients if not _ADDR_RE.match(r)]
        if not recipients or bad:
            return _error(
                f"Địa chỉ người nhận không hợp lệ: {args['to']!r}.", reason="invalid_recipient"
            )

        names = list(args.get("attachments") or [])
        files: list[Path] = []
        for name in names:
            path = self._resolve_attachment(name)
            if path is None:
                return _error(
                    f"Không tìm thấy tài liệu '{name}' trong kho tri thức để đính kèm.",
                    reason="attachment_not_found",
                )
            files.append(path)

        msg = EmailMessage()
        msg["From"] = self.config.from_addr
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = args["subject"]
        msg["Message-ID"] = make_msgid(domain=self.config.from_addr.rsplit("@", 1)[-1])
        msg.set_content(args["body"])
        for path in files:
            ctype, _ = mimetypes.guess_type(path.name)
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            msg.add_attachment(
                path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
            )

        try:
            with smtplib.SMTP(
                self.config.smtp_host, self.config.smtp_port, timeout=self.config.timeout_s
            ) as smtp:
                refused = smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            return _error(
                f"Máy chủ thư từ chối mọi người nhận: {sorted(exc.recipients)}.",
                reason="recipients_refused",
            )
        except (smtplib.SMTPNotSupportedError, UnicodeEncodeError):
            # Địa chỉ có ký tự ngoài ASCII mà máy chủ không hỗ trợ SMTPUTF8.
            return _error(
                f"Địa chỉ người nhận không hợp lệ: {args['to']!r}.", reason="invalid_recipient"
            )
        except (OSError, smtplib.SMTPException) as exc:
            raise MailboxError(
                f"không gửi được tới SMTP {self.config.smtp_host}:{self.config.smtp_port} — "
                f"MailHog có chạy không (`make up`)? {exc}"
            ) from exc

        delivered = [r for r in recipients if r not in refused]
        attached = [p.name for p in files]
        text = f'Đã gửi email tới {", ".join(delivered)} với tiêu đề "{args["subject"]}"'
        text += f", đính kèm {', '.join(attached)}." if attached else "."
        if refused:
            text += f" Không gửi được tới {', '.join(sorted(refused))}."
        return ToolResult(
            call_id="",
            name=TOOL_NAME,
            content=text,
            meta={
                "message_id": msg["Message-ID"],
                "recipients": delivered,
                "refused": sorted(refused),
                "attachments": attached,
            },
        )

    def _resolve_attachment(self, name: str) -> Path | None:
        """Tra tên tài liệu trong thư mục kho tri thức: khớp tên file, hoặc khớp tên bỏ đuôi.
        Chỉ lấy file nằm trực tiếp trong thư mục — tên chứa đường dẫn bị từ chối."""
        name = name.strip()
        if not name or Path(name).name != name:
            return None
        root = self.config.attachments_dir
        exact = root / name
        if exact.is_file():
            return exact
        stems = sorted(p for p in root.iterdir() if p.is_file() and p.stem == name)
        return stems[0] if stems else None

    # -- hộp thư MailHog ------------------------------------------------------

    def list_mailbox(self) -> list[Mail]:
        """Mọi email đang có trong MailHog, cũ trước mới sau."""
        items: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self._api("GET", f"/api/v2/messages?start={start}&limit={_PAGE}")
            items.extend(page.get("items") or [])
            start += int(page.get("count") or 0)
            if not page.get("count") or start >= int(page.get("total") or 0):
                break
        # API trả mới trước; đảo lại để khớp thứ tự gửi trong trace.
        return [_to_mail(item) for item in reversed(items)]

    def clear_mailbox(self) -> None:
        """Xóa mọi email trong MailHog. Gọi trước mỗi run."""
        self._api("DELETE", "/api/v1/messages")

    def _api(self, method: str, path: str) -> dict[str, Any]:
        url = self.config.mailhog_api_url + path
        req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                raw = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise MailboxError(f"không gọi được API MailHog {method} {url}: {exc}") from exc
        return json.loads(raw) if raw.strip() else {}


def _to_mail(item: dict[str, Any]) -> Mail:
    raw = item["Raw"]
    msg = message_from_bytes(raw["Data"].encode("utf-8", "surrogateescape"), policy=policy.default)
    body_part = msg.get_body(preferencelist=("plain",))
    body = body_part.get_content() if body_part is not None else ""
    return Mail(
        id=item["ID"],
        message_id=str(msg.get("Message-ID", "")),
        sender=raw.get("From", ""),
        to=tuple(str(t).lower() for t in raw.get("To") or []),
        subject=str(msg.get("Subject", "")),
        # SMTP chuyển dòng thành CRLF; trả về LF để so khớp được với `body` trong trace.
        body=body.replace("\r\n", "\n").rstrip("\n"),
        attachments=tuple(p.get_filename() or "" for p in msg.iter_attachments()),
    )


def _error(message: str, *, reason: str) -> ToolResult:
    return ToolResult(
        call_id="", name=TOOL_NAME, content=message, is_error=True, meta={"error": reason}
    )
