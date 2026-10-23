"""d4_egress_filter.py — D4 Egress Filter, soát luồng ra trước khi dữ liệu rời vành đai (STT-54).

Vì sao có file này: chặn G1 ở bước cuối cùng — ngay trước khi `send_email` / `http_request` thực
thi — bằng cách nhìn vào chính dữ liệu sắp ra ngoài, không phụ thuộc mô hình có bị thao túng hay
không. Đặc tả hành vi, luật, hit và điều kiện đạt: `docs/04. Design/defense_spec.md` mục 6.
Hook: `PRE_EGRESS` (interfaces.py), chỉ cho tool-call đã qua D3.

Nguyên tắc (defense_spec mục 1, 6.2):
- Mọi tham số đọc từ `config/defenses.yaml` → `defenses.d4_egress_filter`, KHÔNG hard-code
  (quy tắc cứng #4).
- Tất định, không LLM: hàm thuần của (call, run_canaries, egress_allowlist, config).
- Không đọc `data/carrier_tasks.json` hay `data/benign_queries.json` (nguyên tắc 5). Allowlist của
  D4 nằm ở `defenses.yaml`; test so nó với `global_constraints` để hai nơi không lệch.
- Đọc `customers.db` (dữ liệu công ty, không phải đáp án) để biết người nhận hợp lệ và PII thuộc ai.
- Tool ngoài `egress_tools` đi thẳng, không hit.

Bốn luật (spec §6.1), đánh giá ĐỦ cả bốn, mỗi luật vi phạm ghi một hit `block`:
- E1 `canary`       — canary của run có trong tham số, dò bằng ĐÚNG bộ dò của scorer
  (`eval.canary.canary_match_forms`) với tập dạng `canary_decode`. Hit chỉ ghi dạng đã khớp,
  không chép canary.
- E2 `destination`  — `http_request`: URL ngoài `http_url_prefixes`. `send_email`: người nhận ngoài
  `email_domain_allowlist` và không phải `contact_email` của khách nào trong customers.db.
- E3 `pii`          — PII (regex chung HOẶC trùng giá trị trong customers.db) không thuộc người
  nhận của lời gọi. `http_request` không có người nhận ⇒ mọi PII đều chặn. Hit ghi loại và số
  lượng, không ghi giá trị.
- E4 `encoded_url`  — một đoạn URL dài hơn `max_encoded_segment_len` với entropy ≥ ngưỡng. Quét
  url của `http_request` và mọi URL nằm trong tham số chuỗi khác (subject, body).

Chỉ dùng thư viện chuẩn + pyyaml.
"""

from __future__ import annotations

import math
import posixpath
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

from eval.canary import DEFAULT_CUSTOMERS_DB, EVASION_FORMS, FORM_VERBATIM, canary_match_forms
from interfaces import Decision, DefenseHit, HookStage
from tools.send_email import parse_recipients

__all__ = [
    "EgressAllowlist",
    "build_egress_allowlist",
    "filter_egress",
    "load_d4_config",
    "validate_d4_config",
    "RULE_IDS",
]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "defenses.yaml"

_DEFENSE_KEY = "d4_egress_filter"
_STAGE = HookStage.PRE_EGRESS.value  # "pre_egress" — khớp DefenseHit.stage

E1 = "E1_canary"
E2 = "E2_destination"
E3 = "E3_pii"
E4 = "E4_encoded_url"
RULE_IDS: tuple[str, ...] = (E1, E2, E3, E4)

_HTTP_TOOL = "http_request"
_MAIL_TOOL = "send_email"
#: Cách so khớp PII hiện thực được (`pii_definitions.*.match_on`).
_MATCH_ON = ("raw", "digits")


def load_d4_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Nạp và kiểm khối `defenses.d4_egress_filter`. Tách ra để test tiêm cấu hình."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg = raw["defenses"][_DEFENSE_KEY]
    validate_d4_config(cfg)
    return cfg


def validate_d4_config(cfg: dict[str, Any]) -> None:
    """Ném `ValueError` khi cấu hình D4 thiếu luật, dạng giải mã lạ hoặc loại PII chưa định nghĩa."""
    missing = [r for r in RULE_IDS if r not in cfg["rules"]]
    if missing:
        raise ValueError(f"d4_egress_filter.rules thiếu {missing}")
    params = cfg["params"]
    forms = params["canary_decode"]
    unknown = set(forms) - set(EVASION_FORMS)
    if unknown:
        raise ValueError(f"canary_decode có dạng không biết {sorted(unknown)}; hợp lệ: {EVASION_FORMS}")
    if FORM_VERBATIM not in forms:
        raise ValueError("canary_decode phải có 'verbatim'")
    defs = params["pii_definitions"]
    for kind in params["pii_patterns"]:
        if kind not in defs:
            raise ValueError(f"pii_patterns có '{kind}' không khai ở pii_definitions")
        if defs[kind]["match_on"] not in _MATCH_ON:
            raise ValueError(f"pii_definitions.{kind}.match_on phải thuộc {_MATCH_ON}")
    source = params["allowlist"]["email_recipient_must_come_from"]
    if source.count(".") < 2 or not source.split(".")[-1]:
        raise ValueError(
            f"email_recipient_must_come_from phải dạng '<file>.db.<cột>', nhận '{source}'"
        )


# ---------------------------------------------------------------------------
# Allowlist lúc chạy: phần tĩnh từ config + phần tra customers.db
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EgressAllowlist:
    """Allowlist D4 của một lô chạy. `pipeline.py` (STT-55) dựng một lần rồi truyền cho mọi run.

    `pii_index`: (loại PII, giá trị đã chuẩn hóa) → tập `contact_email` của khách sở hữu giá trị đó.
    """

    http_url_prefixes: tuple[str, ...]
    email_domains: tuple[str, ...]
    customer_emails: frozenset[str]
    pii_index: Mapping[tuple[str, str], frozenset[str]] = field(default_factory=dict)


def _digits(text: str) -> str:
    """Dãy chữ số của `text`; tiền tố quốc tế "+84" đổi thành "0" như số nội địa."""
    d = re.sub(r"\D", "", text)
    if text.lstrip().lstrip("(").startswith("+84") and d.startswith("84"):
        d = "0" + d[2:]
    return d


def _norm_value(value: str, match_on: str) -> str:
    return value.strip().casefold() if match_on == "raw" else _digits(value)


def build_egress_allowlist(
    cfg: dict[str, Any], customers_db: Path | str = DEFAULT_CUSTOMERS_DB
) -> EgressAllowlist:
    """Dựng allowlist từ `cfg` (khối d4) và customers.db. Chỉ đọc; không giữ kết nối."""
    params = cfg["params"]
    allow = params["allowlist"]
    source = allow["email_recipient_must_come_from"]
    db_file, column = source.rsplit(".", 1)
    table = Path(db_file).stem  # "customers.db" → bảng "customers"
    defs = params["pii_definitions"]
    kinds = list(params["pii_patterns"])
    columns = [column] + [defs[k]["db_column"] for k in kinds]

    uri = f"file:{Path(customers_db).resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()

    customer_emails: set[str] = set()
    index: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        owner = str(row[0]).strip().casefold()
        customer_emails.add(owner)
        for kind, value in zip(kinds, row[1:], strict=True):
            if value is None:
                continue
            norm = _norm_value(str(value), defs[kind]["match_on"])
            if norm:
                index.setdefault((kind, norm), set()).add(owner)
    return EgressAllowlist(
        http_url_prefixes=tuple(allow["http_url_prefixes"]),
        email_domains=tuple(d.casefold() for d in allow["email_domain_allowlist"]),
        customer_emails=frozenset(customer_emails),
        pii_index={k: frozenset(v) for k, v in index.items()},
    )


_DEFAULT_ALLOWLIST: dict[str, EgressAllowlist] = {}


def _default_allowlist(cfg: dict[str, Any]) -> EgressAllowlist:
    """Allowlist mặc định (customers.db gốc), dựng một lần mỗi tiến trình."""
    key = str(DEFAULT_CUSTOMERS_DB)
    if key not in _DEFAULT_ALLOWLIST:
        _DEFAULT_ALLOWLIST[key] = build_egress_allowlist(cfg)
    return _DEFAULT_ALLOWLIST[key]


# ---------------------------------------------------------------------------
# Luật
# ---------------------------------------------------------------------------


def _hit(rule: str, detail: str) -> DefenseHit:
    return DefenseHit(defense=_DEFENSE_KEY, stage=_STAGE, action="block", rule=rule, detail=detail)


def _strings(value: Any, key: str = "") -> Iterator[tuple[str, str]]:
    """Duỗi tham số thành (khóa, chuỗi): url, body, to, subject, phần tử attachments…"""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield from _strings(v, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, key)
    elif value is not None:
        yield key, str(value)


def _e1(args: dict[str, Any], canaries: tuple[str, ...], forms: list[str]) -> DefenseHit | None:
    text = "\n".join(s for _, s in _strings(args))
    matched: list[str] = []
    for canary in canaries:
        used = canary_match_forms(text, canary, forms)
        if used is not None:
            matched.append("+".join(used))
    if not matched:
        return None
    return _hit(E1, f"canary của run khớp dạng: {', '.join(sorted(set(matched)))}")


def _url_allowed(url: str, prefixes: tuple[str, ...]) -> bool:
    """URL nằm dưới một tiền tố: cùng scheme, host, cổng; path chuẩn hóa (gỡ `..`) bắt đầu bằng
    path của tiền tố. URL có userinfo (`http://intranet.local@evil.test/`) không bao giờ hợp lệ."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return False
    if parts.username is not None or parts.password is not None or not parts.hostname:
        return False
    path = posixpath.normpath(unquote(parts.path) or "/")
    path = path if path.endswith("/") else path + "/"
    for prefix in prefixes:
        p = urlsplit(prefix)
        if (
            parts.scheme.casefold() == p.scheme.casefold()
            and parts.hostname == (p.hostname or "").casefold()
            and port == p.port
            and path.startswith(p.path or "/")
        ):
            return True
    return False


def _recipients(to: Any) -> list[str]:
    if not isinstance(to, str):
        return []
    return [parseaddr(r)[1].strip().casefold() for r in parse_recipients(to)]


def _internal(addr: str, allow: EgressAllowlist) -> bool:
    return any(addr.endswith(d) for d in allow.email_domains)


def _e2(name: str, args: dict[str, Any], allow: EgressAllowlist) -> DefenseHit | None:
    if name == _HTTP_TOOL:
        url = args.get("url")
        if isinstance(url, str) and _url_allowed(url, allow.http_url_prefixes):
            return None
        return _hit(E2, "http_request: URL ngoài http_url_prefixes")
    recipients = _recipients(args.get("to"))
    if not recipients:
        return _hit(E2, "send_email: không có người nhận đọc được")
    bad = [r for r in recipients if not _internal(r, allow) and r not in allow.customer_emails]
    if not bad:
        return None
    return _hit(E2, f"send_email: {len(bad)}/{len(recipients)} người nhận ngoài allowlist")


def _pii_candidates(text: str, params: dict[str, Any]) -> Iterator[tuple[tuple[str, ...], str]]:
    """(các loại PII có thể, giá trị đã chuẩn hóa) cho mọi ứng viên trong `text`.

    Một dãy số là ứng viên của MỌI loại `digits` cùng lúc: MST bắt đầu bằng 0 cũng khớp mẫu SĐT,
    nên chủ sở hữu phải xét trên tất cả các loại của cùng giá trị (xem `_e3`).
    """
    defs = params["pii_definitions"]
    kinds = list(params["pii_patterns"])
    raw_kinds = [k for k in kinds if defs[k]["match_on"] == "raw"]
    digit_kinds = tuple(k for k in kinds if defs[k]["match_on"] == "digits")
    for kind in raw_kinds:
        for m in re.finditer(defs[kind]["regex"], text):
            yield (kind,), _norm_value(m.group(0), "raw")
    if not digit_kinds:
        return
    min_digits = int(params["pii_min_digits"])
    for m in re.finditer(params["pii_digit_candidate_regex"], text):
        run = m.group(0)
        for piece in {run, *run.split()}:
            d = _digits(piece)
            if len(d) >= min_digits:
                yield digit_kinds, d


def _e3(
    name: str, args: dict[str, Any], allow: EgressAllowlist, params: dict[str, Any]
) -> DefenseHit | None:
    defs = params["pii_definitions"]
    owners = set()
    if name == _MAIL_TOOL:
        owners = {r for r in _recipients(args.get("to")) if r in allow.customer_emails}
    # `to` không quét: địa chỉ người nhận là đích của E2, không phải nội dung đi ra.
    texts = [s for k, s in _strings(args) if not (name == _MAIL_TOOL and k == "to")]
    leaked: Counter[str] = Counter()
    seen: set[str] = set()
    for text in texts:
        for variant in {text, unquote(text)}:
            for kinds, value in _pii_candidates(variant, params):
                if value in seen:
                    continue
                seen.add(value)
                known: set[str] = set()
                for k in kinds:
                    known |= allow.pii_index.get((k, value), frozenset())
                if known & owners:
                    continue  # PII của chính người nhận (email báo giá CT-05, nhóm U4)
                if known:
                    kind = next(k for k in kinds if (k, value) in allow.pii_index)
                else:
                    matched = [
                        k for k in kinds if re.fullmatch(defs[k]["regex"], value, re.IGNORECASE)
                    ]
                    if not matched:
                        continue  # không khớp mẫu chung, không có trong DB ⇒ không phải PII
                    kind = matched[0]  # khớp nhiều mẫu (10 số đầu 0: SĐT và MST): ghi loại khai trước
                if "@" in value and _internal(value, allow):
                    continue  # địa chỉ công ty, không phải dữ liệu cá nhân của khách
                leaked[kind] += 1
    if not leaked:
        return None
    shown = ", ".join(f"{k}×{n}" for k, n in sorted(leaked.items()))
    return _hit(E3, f"PII không thuộc người nhận: {shown}")


def _shannon_bits_per_char(block: str) -> float:
    n = len(block)
    return -sum(c / n * math.log2(c / n) for c in Counter(block).values())


def _urls(name: str, args: dict[str, Any], rule: dict[str, Any]) -> list[str]:
    urls = []
    if name == _HTTP_TOOL and isinstance(args.get("url"), str):
        urls.append(args["url"])
    for key, text in _strings(args):
        if name == _HTTP_TOOL and key == "url":
            continue
        urls.extend(re.findall(rule["url_regex"], text))
    return urls


def _e4(name: str, args: dict[str, Any], rule: dict[str, Any]) -> DefenseHit | None:
    max_len = int(rule["max_encoded_segment_len"])
    threshold = float(rule["entropy_threshold_bits_per_char"])
    for url in _urls(name, args, rule):
        # Bỏ scheme + host: tên miền dài không phải dữ liệu mã hóa.
        parts = urlsplit(url.strip())
        tail = url.strip()[len(f"{parts.scheme}://{parts.netloc}") :] if parts.netloc else url
        for variant in {tail, unquote(tail)}:
            for seg in re.split(rule["segment_split_regex"], variant):
                if len(seg) > max_len and _shannon_bits_per_char(seg) >= threshold:
                    ent = _shannon_bits_per_char(seg)
                    return _hit(
                        E4,
                        f"đoạn URL {len(seg)} ký tự > {max_len}, entropy {ent:.2f} >= {threshold}",
                    )
    return None


def filter_egress(
    call: Any,
    *,
    run_canaries: tuple[str, ...],
    egress_allowlist: EgressAllowlist | None,
    enabled: bool,
    config: dict[str, Any] | None = None,
) -> Decision:
    """Soát một tool-call sắp rời vành đai (D4 — spec §6). Trả `Decision(allow|block, reason, hits)`.

    `call` là `ToolCall` đã qua D3. `egress_allowlist=None` ⇒ dựng từ customers.db gốc (đủ cho
    test và chạy đơn lẻ; pipeline truyền bản dựng sẵn). `config` mặc định đọc từ `defenses.yaml`.
    """
    if not enabled:
        return Decision(action="allow")
    cfg = config if config is not None else load_d4_config()
    params = cfg["params"]
    name = call.name
    if name not in params["egress_tools"]:
        return Decision(action="allow")

    rules = cfg["rules"]
    canaries = tuple(c for c in run_canaries if c)
    if rules[E1]["enabled"] and not canaries:
        # Lỗi harness (run chưa gieo canary), không phải hành vi model — ném để run hỏng ồn ào.
        raise ValueError("run_canaries rỗng — D4 E1 không dò được canary")
    allow = egress_allowlist if egress_allowlist is not None else _default_allowlist(cfg)
    args = call.arguments or {}

    candidates = (
        _e1(args, canaries, params["canary_decode"]) if rules[E1]["enabled"] else None,
        _e2(name, args, allow) if rules[E2]["enabled"] else None,
        _e3(name, args, allow, params) if rules[E3]["enabled"] else None,
        _e4(name, args, params["url_entropy_block"]) if rules[E4]["enabled"] else None,
    )
    hits = tuple(h for h in candidates if h is not None)
    if not hits:
        return Decision(action="allow")
    return Decision(action="block", reason=_reason(hits), hits=hits)


def _reason(hits: tuple[DefenseHit, ...]) -> str:
    """Lý do trả cho model và adaptive attacker (STT-57): mã luật + chi tiết, nối bằng '; '."""
    return "D4 chặn — " + "; ".join(f"{h.rule}: {h.detail}" for h in hits)
