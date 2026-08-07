# TECH-002 — Danh mục SKU (Product Catalog)

**Cập nhật:** 01/07/2026 | **Phòng ban:** Quản lý sản phẩm

## 1. Bảng danh mục SKU máy chiếu Epson

| SKU | Tên sản phẩm | Nhóm | Giá tham chiếu (VNĐ) | MOQ |
|---|---|---|---|---|
| SKU-EP-1180 | Epson EB-X06 | Phổ thông | 8.900.000 | 10 |
| SKU-EP-1350 | Epson EB-W06 | Phổ thông | 10.200.000 | 10 |
| SKU-EP-2100 | Epson EB-2042 | Doanh nghiệp | 15.600.000 | 20 |
| **SKU-EP-2250** | **Epson EB-2250U** | **Doanh nghiệp** | **18.900.000** | **20** |
| SKU-EP-2400 | Epson EB-2247U | Doanh nghiệp | 21.500.000 | 20 |
| SKU-EP-SCR-100 | Màn chiếu điện 100 inch | Phụ kiện | 3.200.000 | 15 |

Chi tiết mức đặt hàng tối thiểu (MOQ) xem thêm tại POL-004.

## 2. Script xuất danh mục sang JSON (dùng nội bộ)

```python
import json

CATALOG = [
    {"sku": "SKU-EP-2250", "name": "Epson EB-2250U", "group": "doanh_nghiep", "moq": 20},
    {"sku": "SKU-EP-2100", "name": "Epson EB-2042", "group": "doanh_nghiep", "moq": 20},
]

def export_catalog(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(CATALOG, f, ensure_ascii=False, indent=2)
```

## 3. Mã băm kiểm tra toàn vẹn tệp danh mục (base64, mẫu minh họa)

```
RXBzb24gRUItMjI1MFU7U0tVLUVQLTIyNTA7S2hvIEhDTTtUb246MTQy
```

Đây là ví dụ minh họa cách mã hóa base64 một dòng dữ liệu sản phẩm để lưu log đồng bộ — không phải dữ liệu thật, chỉ dùng cho tài liệu kỹ thuật.
