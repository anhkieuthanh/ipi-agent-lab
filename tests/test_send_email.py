"""Tool `send_email` + hộp thư MailHog (STT-29).

Hai nhóm: unit test thay `smtplib.SMTP` bằng bản giả (không cần hạ tầng), và test tích hợp
`@pytest.mark.mailhog` gửi thật qua MailHog rồi đọc lại — tự bỏ qua khi MailHog không chạy.
"""

import json
import smtplib
import urllib.request
from pathlib import Path

import pytest

from agent.llm_client import ToolCall
from tools.registry import ToolRegistry, build_tool_layer
from tools.send_email import Mail, MailboxError, MailConfig, SendEmail, parse_recipients

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path, **over) -> MailConfig:
    base = dict(
        from_addr="kinhdoanh@congty-noibo.vn",
        smtp_host="127.0.0.1",
        smtp_port=1025,
        mailhog_api_url="http://127.0.0.1:8025",
        timeout_s=5,
        attachments_dir=tmp_path,
    )
    base.update(over)
    return MailConfig(**base)


class FakeSMTP:
    """Thay `smtplib.SMTP`: giữ lại email đã gửi, có thể từ chối một số người nhận."""

    sent: list = []
    refuse: set = set()
    fail: Exception | None = None

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.fail is not None:
            raise FakeSMTP.fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send_message(self, msg):
        rcpts = [a.strip() for a in msg["To"].split(",")]
        if rcpts and all(r in FakeSMTP.refuse for r in rcpts):
            raise smtplib.SMTPRecipientsRefused({r: (550, b"no") for r in rcpts})
        FakeSMTP.sent.append(msg)
        return {r: (550, b"no") for r in rcpts if r in FakeSMTP.refuse}


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.refuse, FakeSMTP.fail = [], set(), None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def _args(**over):
    base = {"to": "lienhe.namphat@thietbi.vn", "subject": "Báo giá", "body": "Kính gửi quý khách"}
    base.update(over)
    return base


# -- cấu hình -----------------------------------------------------------------------


def test_params_trong_tools_yaml_du_khoa():
    cfg = MailConfig.from_params(ToolRegistry().params("send_email"), env={})
    assert cfg.from_addr.endswith("@congty-noibo.vn")
    assert cfg.smtp_port == 1025
    assert cfg.attachments_dir == ROOT / "src" / "rag" / "corpus"
    assert cfg.attachments_dir.is_dir()


def test_bien_moi_truong_ghi_de_host_port_url():
    params = ToolRegistry().params("send_email")
    env = {"SMTP_HOST": "mailhog", "SMTP_PORT": "2525", "MAILHOG_API_URL": "http://mailhog:8025/"}
    cfg = MailConfig.from_params(params, env=env)
    assert (cfg.smtp_host, cfg.smtp_port) == ("mailhog", 2525)
    assert cfg.mailhog_api_url == "http://mailhog:8025"


def test_params_thieu_hoac_la_bi_tu_choi():
    params = ToolRegistry().params("send_email")
    with pytest.raises(ValueError, match="thiếu"):
        MailConfig.from_params({k: v for k, v in params.items() if k != "from_addr"}, env={})
    with pytest.raises(ValueError, match="khóa lạ"):
        MailConfig.from_params({**params, "allowlist": []}, env={})


# -- handler ------------------------------------------------------------------------


def test_parse_recipients_tach_dau_phay_cham_phay():
    assert parse_recipients("a@x.vn, b@y.vn; c@z.vn ") == ["a@x.vn", "b@y.vn", "c@z.vn"]
    assert parse_recipients(" , ") == []


def test_gui_thanh_cong(tmp_path, fake_smtp):
    res = SendEmail(_config(tmp_path))(_args())
    assert not res.is_error
    assert "lienhe.namphat@thietbi.vn" in res.content
    assert res.meta["recipients"] == ["lienhe.namphat@thietbi.vn"]
    assert res.meta["message_id"].endswith("@congty-noibo.vn>")
    (msg,) = fake_smtp.sent
    assert msg["From"] == "kinhdoanh@congty-noibo.vn"
    assert msg["Subject"] == "Báo giá"
    assert msg.get_content().strip() == "Kính gửi quý khách"


def test_nhieu_nguoi_nhan_trong_mot_chuoi_deu_duoc_gui(tmp_path, fake_smtp):
    """Baseline không lọc người nhận — chặn là việc của D4, chấm là việc của scorer."""
    res = SendEmail(_config(tmp_path))(_args(to="a@thietbi.vn, attacker@evil.example"))
    assert res.meta["recipients"] == ["a@thietbi.vn", "attacker@evil.example"]


@pytest.mark.parametrize("to", ["", "khong-phai-email", "a@x.vn, xau"])
def test_nguoi_nhan_sai_dang_tra_loi_cho_model(tmp_path, fake_smtp, to):
    res = SendEmail(_config(tmp_path))(_args(to=to))
    assert res.is_error and res.meta["error"] == "invalid_recipient"
    assert fake_smtp.sent == []


def test_dinh_kem_tra_theo_ten_hoac_ten_bo_duoi(tmp_path, fake_smtp):
    (tmp_path / "BG-2026-001.pdf").write_bytes(b"%PDF-1.4 bao gia")
    (tmp_path / "POL-006_bao_mat.md").write_text("# chính sách", encoding="utf-8")
    res = SendEmail(_config(tmp_path))(_args(attachments=["BG-2026-001.pdf", "POL-006_bao_mat"]))
    assert not res.is_error
    assert res.meta["attachments"] == ["BG-2026-001.pdf", "POL-006_bao_mat.md"]
    parts = list(fake_smtp.sent[0].iter_attachments())
    assert [p.get_filename() for p in parts] == ["BG-2026-001.pdf", "POL-006_bao_mat.md"]
    assert parts[0].get_content_type() == "application/pdf"
    assert parts[0].get_content() == b"%PDF-1.4 bao gia"


@pytest.mark.parametrize("name", ["khong-co.pdf", "../pyproject.toml", "/etc/passwd", " "])
def test_dinh_kem_khong_co_khong_gui_gi(tmp_path, fake_smtp, name):
    res = SendEmail(_config(tmp_path))(_args(attachments=[name]))
    assert res.is_error and res.meta["error"] == "attachment_not_found"
    assert fake_smtp.sent == []


def test_tu_choi_mot_phan_nguoi_nhan(tmp_path, fake_smtp):
    fake_smtp.refuse = {"b@y.vn"}
    res = SendEmail(_config(tmp_path))(_args(to="a@x.vn, b@y.vn"))
    assert not res.is_error
    assert res.meta["recipients"] == ["a@x.vn"] and res.meta["refused"] == ["b@y.vn"]
    assert "Không gửi được tới b@y.vn" in res.content


def test_tu_choi_moi_nguoi_nhan_la_loi_cho_model(tmp_path, fake_smtp):
    fake_smtp.refuse = {"a@x.vn"}
    res = SendEmail(_config(tmp_path))(_args(to="a@x.vn"))
    assert res.is_error and res.meta["error"] == "recipients_refused"


def test_smtp_khong_chay_la_loi_harness(tmp_path, fake_smtp):
    fake_smtp.fail = ConnectionRefusedError("refused")
    with pytest.raises(MailboxError, match="make up"):
        SendEmail(_config(tmp_path))(_args())


def test_api_mailhog_khong_chay_la_loi_harness(tmp_path):
    mail = SendEmail(_config(tmp_path, mailhog_api_url="http://127.0.0.1:9", timeout_s=1))
    with pytest.raises(MailboxError):
        mail.list_mailbox()


def test_registry_dien_call_id(fake_smtp):
    reg = build_tool_layer()
    call = ToolCall(
        id="c7", name="send_email", arguments=_args(), arguments_raw=json.dumps(_args())
    )
    res = reg.call_tool(call)
    assert res.call_id == "c7" and res.name == "send_email" and not res.is_error


# -- tích hợp MailHog thật -------------------------------------------------------------


@pytest.fixture
def mailhog() -> SendEmail:
    mail = SendEmail(MailConfig.from_params(ToolRegistry().params("send_email")))
    try:
        urllib.request.urlopen(mail.config.mailhog_api_url + "/api/v2/messages?limit=1", timeout=2)
    except OSError:
        pytest.skip(f"MailHog không chạy ở {mail.config.mailhog_api_url} — `make up` trước")
    mail.clear_mailbox()
    yield mail
    mail.clear_mailbox()


@pytest.mark.mailhog
def test_gui_roi_doc_lai_roi_xoa(mailhog):
    corpus = mailhog.config.attachments_dir
    doc = sorted(p for p in corpus.iterdir() if p.suffix == ".pdf")[0]
    body = "Kính gửi quý khách,\nCông ty gửi báo giá thiết bị — tổng 12.500.000 ₫."
    first = mailhog(_args(subject="Báo giá số 1", body=body, attachments=[doc.name]))
    second = mailhog(_args(to="A@X.vn; b@y.vn", subject="Thư thứ hai", body="ok"))
    assert not first.is_error and not second.is_error

    box = mailhog.list_mailbox()
    assert [m.subject for m in box] == ["Báo giá số 1", "Thư thứ hai"]
    one, two = box
    assert isinstance(one, Mail)
    assert one.sender == "kinhdoanh@congty-noibo.vn"
    assert one.to == ("lienhe.namphat@thietbi.vn",)
    assert one.body == body
    assert one.attachments == (doc.name,)
    assert one.message_id == first.meta["message_id"]
    assert two.to == ("a@x.vn", "b@y.vn")

    mailhog.clear_mailbox()
    assert mailhog.list_mailbox() == []
