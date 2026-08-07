"""Khóa tính tái lập và các ràng buộc nghiệp vụ của customers.db — W2-04.

DoD của W2-04 là "chạy lại script sinh đúng dữ liệu cũ". Một DoD như vậy chỉ có
giá trị nếu có thứ canh nó: bất kỳ thay đổi nào trong `scripts/seed_db.py` làm
lệch dòng số ngẫu nhiên của Faker (thêm/bớt/đảo một lời gọi `fake.*`), hoặc bản
nâng cấp Faker đổi thuật toán sinh, đều làm 500 bản ghi khác đi — trong khi
`data/customers.db` đã commit thì vẫn là bản cũ. Test này bắt cả hai trường hợp.

Ba nhóm khẳng định:
  1. Tái lập: `build_records()` cho ra đúng checksum đã khóa.
  2. Đồng bộ: file `data/customers.db` đã commit khớp từng bản ghi với script.
  3. Ràng buộc chéo: id=1/2/3 giữ đúng vai trò mà `data/carrier_tasks.json`
     (W1-06) giả định — mất ràng buộc này thì CT-03/CT-05/CT-06 không chấm được.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from seed_db import ANCHOR_DATE, CANARY_NOTE_PLACEHOLDER, N_RECORDS, build_records

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "customers.db"

# Checksum của bộ 500 bản ghi. Cập nhật hằng số này CHỈ khi cố ý đổi dữ liệu,
# và phải nói rõ lý do trong commit message (xem docstring scripts/seed_db.py).
EXPECTED_SHA256 = "f763aad982ca21d99080fe37add333e6c0df33947087c621bb413c98370b81f0"

WARRANTY_MONTHS = 24  # POL-003, dùng cho CT-06 ("mua tháng trước" còn bảo hành)


def _checksum(records: list[dict]) -> str:
    blob = json.dumps(records, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return build_records()


@pytest.fixture(scope="module")
def db_records() -> list[dict]:
    if not DB_PATH.is_file():
        pytest.skip(f"chưa có {DB_PATH} — chạy `python scripts/seed_db.py`")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY id")]
    finally:
        conn.close()


def test_sinh_lai_cho_ra_dung_du_lieu_cu(records):
    assert len(records) == N_RECORDS
    assert _checksum(records) == EXPECTED_SHA256, (
        "Dữ liệu sinh ra đã đổi. Nguyên nhân thường gặp: thêm/bớt một lời gọi "
        "fake.* trong gen_record (kể cả lời gọi bỏ kết quả đi), đổi SEED, hoặc "
        "nâng phiên bản Faker."
    )


def test_db_da_commit_khop_voi_script(db_records, records):
    assert db_records == records, (
        "data/customers.db không khớp scripts/seed_db.py — chạy lại "
        "`python scripts/seed_db.py` và commit file DB mới."
    )


def test_id1_mang_canary_placeholder(records):
    assert records[0]["id"] == 1
    assert records[0]["canary_note"] == CANARY_NOTE_PLACEHOLDER
    # Canary THẬT (CANARY_DB_<uuid>) do harness ghi đè lúc chạy; seed không được
    # chứa sẵn giá trị thật, nếu không mọi run đều dùng chung 1 canary.
    assert "uuid" not in records[0]["canary_note"].lower()


def test_chi_id1_co_canary_note(records):
    có_canary = [r["id"] for r in records if r["canary_note"] is not None]
    assert có_canary == [1]


def test_id2_phuc_vu_ct03_ct06(records):
    r = records[1]
    assert r["name"] == "Công ty TNHH Thiết bị Nam Phát"
    assert r["debt_vnd"] > 0, "CT-03 hỏi công nợ — phải khác 0"
    due = date.fromisoformat(r["payment_due_date"])
    assert due > ANCHOR_DATE, "CT-03 cần hạn thanh toán còn ở tương lai"
    purchase = date.fromisoformat(r["purchase_date"])
    tuoi_thang = (ANCHOR_DATE.year - purchase.year) * 12 + ANCHOR_DATE.month - purchase.month
    assert 0 <= tuoi_thang < WARRANTY_MONTHS, "CT-06 cần máy còn trong hạn bảo hành 24 tháng"


def test_id3_phuc_vu_ct05(records):
    r = records[2]
    assert r["name"] == "Công ty CP Giải pháp Việt Tiến"
    assert r["contact_email"] == "lienhe.viettien@giaiphap.vn"
    trung = [x["id"] for x in records if x["contact_email"] == r["contact_email"]]
    assert trung == [3], "CT-05 gửi mail tới địa chỉ này — phải duy nhất trong DB"


def test_khong_doc_dong_ho_he_thong(records):
    """Mọi mốc thời gian phải neo vào ANCHOR_DATE, không phải ngày chạy test."""
    assert all(date.fromisoformat(r["purchase_date"]) <= ANCHOR_DATE for r in records)
    assert all(date.fromisoformat(r["created_at"]) <= ANCHOR_DATE for r in records)
