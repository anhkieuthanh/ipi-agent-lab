"""Tool `http_request` (TL4) — API nội bộ mô phỏng và bồn chứa G1 mức cao (STT-30).

Hai đường, chọn theo host của URL:

- **Host nội bộ** (`intranet_host`, mặc định `intranet.local`) — không có máy chủ thật; handler trả
  lời tại chỗ. `GET /api/inventory/<sku>` đọc bảng `inventory` trong `config/tools.yaml` (khớp
  TECH-001, TECH-002), mọi path khác 404, method khác GET trên endpoint tồn kho 405.
- **Mọi host khác** — KHÔNG ra Internet và không chạm dịch vụ nào của lab: handler chuyển nguyên
  method, path, query, body tới canary listener (STT-34), URL gốc đi kèm ở header `X-Original-URL`.
  Model luôn nhận cùng một phản hồi cố định (`external_response`), dù listener chạy hay không, để
  hành vi model không đổi theo trạng thái hạ tầng. Listener không với tới chỉ ghi vào `meta`.

    http = HttpRequest.from_registry(reg)
    reg.bind("http_request", http)

Mọi tham số model đề xuất (method, url, body) đã nằm nguyên văn trong `steps.tool_args` — lõi agent
ghi trước khi trả kết quả cho model. `meta` thêm URL đã tách (`host`, `path`, `query`), `route`
(`intranet` | `external`) và kết quả chuyển tiếp, cho phòng thủ và scorer, không vào context.

Handler không kiểm allowlist URL: baseline dễ tổn thương có chủ đích. Chặn là việc của D4, chấm là
việc của `eval.allowed_actions` (`url_prefix_in`, `body_must_be_empty`).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

from interfaces import ToolResult

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

__all__ = ["HttpConfig", "HttpRequest"]

TOOL_NAME = "http_request"

_PARAM_KEYS = frozenset(
    {
        "intranet_host",
        "external_sink_url",
        "sink_timeout_s",
        "external_response",
        "inventory_updated_at",
        "inventory",
    }
)
_URL_SAFE = "/:?#[]@!$&'()*+,;=%-._~"
_INVENTORY_PATH = re.compile(r"^/api/inventory/(?P<sku>[^/]+)/?$")


@dataclass(frozen=True)
class HttpConfig:
    intranet_host: str
    external_sink_url: str
    sink_timeout_s: float
    external_status: int
    external_body: str
    inventory_updated_at: str
    inventory: dict[str, dict[str, Any]]

    @classmethod
    def from_params(
        cls, params: Mapping[str, Any], env: Mapping[str, str] | None = None
    ) -> HttpConfig:
        """Từ `params` của `http_request` trong tools.yaml; CANARY_LISTENER_URL ghi đè URL sink."""
        env = os.environ if env is None else env
        missing = _PARAM_KEYS - set(params)
        if missing:
            raise ValueError(f"http_request.params thiếu {sorted(missing)}")
        unknown = set(params) - _PARAM_KEYS
        if unknown:
            raise ValueError(f"http_request.params có khóa lạ {sorted(unknown)}")
        resp = params["external_response"]
        return cls(
            intranet_host=str(params["intranet_host"]).lower(),
            external_sink_url=(
                env.get("CANARY_LISTENER_URL") or str(params["external_sink_url"])
            ).rstrip("/"),
            sink_timeout_s=float(params["sink_timeout_s"]),
            external_status=int(resp["status"]),
            external_body=str(resp["body"]),
            inventory_updated_at=str(params["inventory_updated_at"]),
            inventory={str(k): dict(v) for k, v in params["inventory"].items()},
        )


class HttpRequest:
    """Handler `http_request`."""

    def __init__(self, config: HttpConfig) -> None:
        self.config = config

    @classmethod
    def from_registry(cls, registry: ToolRegistry) -> HttpRequest:
        return cls(HttpConfig.from_params(registry.params(TOOL_NAME)))

    def __call__(self, args: dict[str, Any]) -> ToolResult:
        method = args["method"]
        url = args["url"].strip()
        body = args.get("body") or ""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return _error(f"URL không hợp lệ: {url!r}.", reason="invalid_url")

        meta: dict[str, Any] = {
            "method": method,
            "url": url,
            "host": parts.hostname,
            "path": parts.path or "/",
            "query": parts.query,
            "body_len": len(body),
        }
        if parts.hostname.lower() == self.config.intranet_host:
            status, text = self._intranet(method, parts.path or "/")
            meta["route"] = "intranet"
        else:
            status, text = self.config.external_status, self.config.external_body
            meta["route"] = "external"
            meta["sink"] = self._forward(method, url, parts, body)
        meta["status"] = status
        return ToolResult(
            call_id="",
            name=TOOL_NAME,
            content=json.dumps({"status": status, "body": text}, ensure_ascii=False),
            meta=meta,
        )

    # -- API nội bộ mô phỏng -------------------------------------------------

    def _intranet(self, method: str, path: str) -> tuple[int, str]:
        m = _INVENTORY_PATH.match(path)
        if m is None:
            return 404, _json({"error": "not_found", "path": path})
        if method != "GET":
            return 405, _json({"error": "method_not_allowed", "allowed": ["GET"]})
        sku = m.group("sku").upper()
        item = self.config.inventory.get(sku)
        if item is None:
            return 404, _json({"error": "sku_not_found", "sku": sku})
        return 200, _json(
            {
                "sku": sku,
                "name": item["name"],
                "quantity": item["quantity"],
                "warehouse": item["warehouse"],
                "updated_at": self.config.inventory_updated_at,
            }
        )

    # -- bồn chứa ngoài: chuyển tới canary listener ---------------------------

    def _forward(self, method: str, url: str, parts: Any, body: str) -> dict[str, Any]:
        """Gửi bản sao request tới listener. Lỗi mạng không ném: model đã nhận phản hồi cố định,
        và tham số rò rỉ đã nằm trong trace — listener chỉ là điểm dò thứ hai của scorer."""
        # Model có thể đặt canary chưa mã hóa, có dấu tiếng Việt vào path/query: percent-encode để
        # request đi được mà không đổi nội dung (scorer gỡ percent-encoding khi dò).
        target = self.config.external_sink_url + quote(parts.path or "/", safe=_URL_SAFE)
        if parts.query:
            target += "?" + quote(parts.query, safe=_URL_SAFE)
        req = urllib.request.Request(
            target,
            # Body đi kèm cả với GET: model có thể nhét dữ liệu vào body GET, listener phải thấy.
            data=body.encode("utf-8") if body else None,
            method=method,
            headers={
                "X-Original-URL": quote(url, safe=_URL_SAFE),
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.sink_timeout_s) as resp:
                return {"delivered": True, "status": resp.status}
        except urllib.error.HTTPError as exc:
            return {"delivered": True, "status": exc.code}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"delivered": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def _json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _error(message: str, *, reason: str) -> ToolResult:
    return ToolResult(
        call_id="", name=TOOL_NAME, content=message, is_error=True, meta={"error": reason}
    )
