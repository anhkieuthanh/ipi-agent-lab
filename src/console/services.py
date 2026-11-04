"""Trạng thái dịch vụ hạ tầng lab cho console — hợp đồng ở `config/services.yaml`.

Probe chạy ở backend, song song, mỗi dịch vụ một timeout ngắn; kết quả cache dùng chung cho mọi tab.
Một probe lỗi chỉ làm dịch vụ đó `down`/`unknown`, không làm hỏng cả phản hồi. Địa chỉ probe (nội
bộ) không bao giờ ra trình duyệt; trình duyệt chỉ nhận `public_url` đã bỏ thông tin đăng nhập và
query. Dịch vụ `kind: config` (gateway LLM) chỉ kiểm có cấu hình, không gửi request.

Health xanh chỉ chứng minh dịch vụ trả lời được. Việc payload có tới nơi hay không xem bằng
`mail_messages` (hộp thư MailHog) và `canary_hits` (hit của listener theo `run_id`).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.send_email import _to_mail

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "services.yaml"
SOURCES = {"rag": ROOT / "config" / "rag.yaml", "tools": ROOT / "config" / "tools.yaml"}

#: Trạng thái của dịch vụ được probe / dịch vụ chỉ kiểm cấu hình.
PROBE_STATES = ("up", "down", "not_configured", "unknown")
CONFIG_STATES = ("configured", "not_configured")

MAIL_SNIPPET = 600
HIT_BODY_PREVIEW = 2000
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")

Fetch = Callable[[str, float], tuple[int, bytes]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _http_get(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "ipi-guard-console"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URL từ config
            return resp.status, resp.read(1 << 20)
    except urllib.error.HTTPError as e:
        return e.code, b""


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Service:
    id: str
    label: str
    short: str
    role: str
    kind: str  # probe · config
    base_from: str | None = None
    base_env: str | None = None
    health_path: str = "/"
    public_url: str | None = None
    public_url_env: str | None = None
    env: str | None = None
    demo: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ProbeSettings:
    timeout_s: float
    cache_ttl_s: float
    min_interval_s: float
    stale_before_demo_s: float


def load_config(path: Path = CONFIG) -> tuple[ProbeSettings, list[Service]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    p = raw["probe"]
    settings = ProbeSettings(
        timeout_s=float(p["timeout_s"]),
        cache_ttl_s=float(p["cache_ttl_s"]),
        min_interval_s=float(p["min_interval_s"]),
        stale_before_demo_s=float(p["stale_before_demo_s"]),
    )
    services = [Service(**s) for s in raw["services"]]
    for s in services:
        if s.kind not in ("probe", "config"):
            raise ValueError(f"services.yaml: {s.id} có kind lạ {s.kind!r}")
    return settings, services


def _lookup(source: str, sources: Mapping[str, Path]) -> str | None:
    """`rag:qdrant.url` → giá trị trong config/rag.yaml; `tools:send_email.x` → params của tool."""
    name, _, dotted = source.partition(":")
    if name not in sources:
        raise ValueError(f"base_from lạ: {source}")
    node: Any = yaml.safe_load(sources[name].read_text(encoding="utf-8"))
    keys = dotted.split(".")
    if name == "tools":
        node = node["tools"][keys[0]]["params"]
        keys = keys[1:]
    for k in keys:
        if not isinstance(node, Mapping) or k not in node:
            return None
        node = node[k]
    return str(node) if node else None


def probe_base(
    s: Service, env: Mapping[str, str] | None = None, sources: Mapping[str, Path] = SOURCES
) -> str | None:
    """Địa chỉ harness thực sự dùng: biến môi trường ghi đè trước, rồi tới file config."""
    env = os.environ if env is None else env
    if s.base_env and env.get(s.base_env):
        return env[s.base_env].rstrip("/")
    base = _lookup(s.base_from, sources) if s.base_from else None
    return base.rstrip("/") if base else None


def safe_public_url(url: str | None) -> str | None:
    """Chỉ http(s); bỏ user:password, query và fragment-chứa-token — trình duyệt chỉ cần nơi để mở."""
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def public_url(s: Service, env: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    raw = (env.get(s.public_url_env) if s.public_url_env else None) or s.public_url
    return safe_public_url(raw)


def _port(url: str | None) -> int | None:
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    return parts.port or {"http": 80, "https": 443}.get(parts.scheme)


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def _short_error(e: BaseException, timeout: float) -> str:
    """Lỗi ngắn, không chứa URL (URL nội bộ có thể mang thông tin đăng nhập)."""
    if isinstance(e, TimeoutError) or "timed out" in str(e):
        return f"hết thời gian chờ ({timeout:g}s)"
    if isinstance(e, urllib.error.URLError):
        reason = e.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            return f"hết thời gian chờ ({timeout:g}s)"
        if isinstance(reason, ConnectionRefusedError):
            return "từ chối kết nối"
        if isinstance(reason, OSError) and reason.strerror:
            return reason.strerror
        return type(reason).__name__ if isinstance(reason, BaseException) else "không kết nối được"
    if isinstance(e, ConnectionRefusedError):
        return "từ chối kết nối"
    return type(e).__name__


def probe_one(
    s: Service,
    settings: ProbeSettings,
    *,
    env: Mapping[str, str] | None = None,
    fetch: Fetch = _http_get,
    sources: Mapping[str, Path] = SOURCES,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    base = None
    out: dict[str, Any] = {
        "id": s.id, "label": s.label, "short": s.short, "role": s.role, "kind": s.kind,
        "status": "unknown", "latency_ms": None, "error": None, "checked_at": _now(),
        "public_url": None, "port": None,
    }
    if s.kind == "config":
        # Không gửi request: chỉ có hoặc không có cấu hình. Không trả giá trị biến môi trường.
        out["status"] = "configured" if s.env and env.get(s.env) else "not_configured"
        return out
    out["public_url"] = public_url(s, env)
    try:
        base = probe_base(s, env, sources)
    except Exception as e:  # noqa: BLE001 — config hỏng thì dịch vụ unknown, không hỏng cả trang
        out["error"] = f"đọc cấu hình lỗi: {type(e).__name__}"
        return out
    if not base:
        out["status"] = "not_configured"
        return out
    out["port"] = _port(base)
    t0 = time.perf_counter()
    try:
        code, _ = fetch(base + s.health_path, settings.timeout_s)
    except Exception as e:  # noqa: BLE001
        out["status"] = "down"
        out["error"] = _short_error(e, settings.timeout_s)
    else:
        out["status"] = "up" if 200 <= code < 300 else "down"
        out["error"] = None if out["status"] == "up" else f"HTTP {code}"
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


class Monitor:
    """Probe song song + cache dùng chung. Hai request tới cùng lúc khi cache hết hạn chỉ chạy một
    vòng probe (khóa); request kia nhận kết quả vừa xong."""

    def __init__(
        self,
        config: Path = CONFIG,
        *,
        fetch: Fetch = _http_get,
        env: Mapping[str, str] | None = None,
        sources: Mapping[str, Path] = SOURCES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings, self.services = load_config(config)
        self.fetch, self.env, self.sources, self._clock = fetch, env, sources, clock
        self._lock = threading.Lock()
        self._at: float | None = None
        self._result: dict[str, Any] | None = None

    def _probe_all(self) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=max(1, len(self.services))) as pool:
            items = list(pool.map(
                lambda s: probe_one(s, self.settings, env=self.env, fetch=self.fetch,
                                    sources=self.sources),
                self.services,
            ))
        return {"checked_at": _now(), "ttl_s": self.settings.cache_ttl_s, "services": items}

    def age(self) -> float | None:
        return None if self._at is None else self._clock() - self._at

    def status(self, *, force: bool = False, max_age: float | None = None) -> dict[str, Any]:
        limit = self.settings.cache_ttl_s if max_age is None else max_age
        if force:
            limit = min(limit, self.settings.min_interval_s)
        with self._lock:
            age = self.age()
            if self._result is None or age is None or age >= limit:
                self._result = self._probe_all()
                self._at = self._clock()
                age = 0.0
            return {**self._result, "age_s": round(age, 1)}

    def by_id(self, result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {s["id"]: s for s in result["services"]}


# ---------------------------------------------------------------------------
# Phụ thuộc của kịch bản demo
# ---------------------------------------------------------------------------


def _matches(rule: Any, scenario: Mapping[str, Any]) -> bool:
    if rule == "all":
        return True
    if isinstance(rule, Mapping):
        return any(scenario.get(field) in values for field, values in rule.items())
    return False


def demo_need(s: Service, scenario: Mapping[str, Any]) -> str | None:
    """required · optional · None (kịch bản không dùng dịch vụ này)."""
    rules = s.demo or {}
    if _matches(rules.get("required_for"), scenario):
        return "required"
    if _matches(rules.get("optional_for"), scenario):
        return "optional"
    return None


def demo_check(monitor: Monitor, scenario: Mapping[str, Any]) -> dict[str, Any]:
    """Probe lại nếu kết quả cũ hơn `stale_before_demo_s`. `ok` false chỉ khi dịch vụ BẮT BUỘC
    không `up`; dịch vụ tùy chọn lỗi chỉ là lưu ý."""
    result = monitor.status(max_age=monitor.settings.stale_before_demo_s)
    states = monitor.by_id(result)
    deps = []
    for s in monitor.services:
        need = demo_need(s, scenario)
        if need is None:
            continue
        st = states[s.id]
        deps.append({"id": s.id, "label": s.label, "need": need, "status": st["status"],
                     "error": st["error"]})
    blocking = [d for d in deps if d["need"] == "required" and d["status"] != "up"]
    return {"ok": not blocking, "checked_at": result["checked_at"], "deps": deps,
            "blocking": [d["id"] for d in blocking]}


# ---------------------------------------------------------------------------
# Nghiệm thu sau lượt chạy: hộp thư MailHog, hit của canary listener
# ---------------------------------------------------------------------------


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # MailHog ghi nano giây ("…:40.123456789+07:00"); fromisoformat chỉ nhận tới micro giây.
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _match_run(at: datetime | None, windows: Sequence[Mapping[str, Any]]) -> str | None:
    """Run có khung [created_at, finished_at] chứa thời điểm nhận. MailHog không mang run_id nên
    chỉ đối chiếu được theo thời gian."""
    if at is None:
        return None
    for w in windows:
        start, end = _parse_time(w.get("created_at")), _parse_time(w.get("finished_at"))
        if start and start <= at and (end is None or at <= end):
            return w["run_id"]
    return None


def mail_messages(
    monitor: Monitor, windows: Sequence[Mapping[str, Any]] = (), limit: int = 20
) -> dict[str, Any]:
    svc = next(s for s in monitor.services if s.id == "mailhog")
    base = probe_base(svc, monitor.env, monitor.sources)
    if not base:
        return {"status": "not_configured", "items": [], "total": 0}
    try:
        code, body = monitor.fetch(f"{base}/api/v2/messages?limit={int(limit)}",
                                    max(monitor.settings.timeout_s, 3.0))
    except Exception as e:  # noqa: BLE001
        return {"status": "down", "error": _short_error(e, 3.0), "items": [], "total": 0}
    if code != 200:
        return {"status": "down", "error": f"HTTP {code}", "items": [], "total": 0}
    data = json.loads(body or b"{}")
    items = []
    for m in data.get("items") or []:
        # Giải mã MIME bằng đúng hàm harness dùng để đọc lại hộp thư (tiêu đề, thân base64…).
        mail = _to_mail(m)
        at = _parse_time(m.get("Created"))
        items.append({
            "id": mail.id,
            "received_at": at.isoformat() if at else m.get("Created"),
            "from": mail.sender,
            "to": list(mail.to),
            "subject": mail.subject,
            "snippet": mail.body[:MAIL_SNIPPET],
            "truncated": len(mail.body) > MAIL_SNIPPET,
            "attachments": list(mail.attachments),
            "run_id": _match_run(at, windows),
        })
    return {"status": "up", "items": items, "total": data.get("total", len(items))}


def canary_hits(monitor: Monitor, run_ids: Sequence[str]) -> dict[str, Any]:
    """Hit của listener gắn đúng `run_id` (header X-IPI-Run). Không trả headers của request."""
    bad = [r for r in run_ids if not RUN_ID_RE.match(r)]
    if bad or not run_ids:
        raise ValueError("run_id không hợp lệ")
    svc = next(s for s in monitor.services if s.id == "canary")
    base = probe_base(svc, monitor.env, monitor.sources)
    if not base:
        return {"status": "not_configured", "items": []}
    items: list[dict[str, Any]] = []
    for run_id in run_ids:
        url = f"{base}/hits?" + urllib.parse.urlencode({"run": run_id})
        try:
            code, body = monitor.fetch(url, max(monitor.settings.timeout_s, 3.0))
        except Exception as e:  # noqa: BLE001
            return {"status": "down", "error": _short_error(e, 3.0), "items": []}
        if code != 200:
            return {"status": "down", "error": f"HTTP {code}", "items": []}
        for h in json.loads(body or b"[]"):
            text = h.get("body") or ""
            items.append({
                "id": h.get("id"),
                "run_id": h.get("run_token"),
                "received_at": h.get("received_at"),
                "method": h.get("method"),
                "original_url": h.get("original_url"),
                "body_preview": text[:HIT_BODY_PREVIEW],
                "body_encoding": h.get("body_encoding"),
                "truncated": bool(h.get("body_truncated")) or len(text) > HIT_BODY_PREVIEW,
            })
    return {"status": "up", "items": items}
