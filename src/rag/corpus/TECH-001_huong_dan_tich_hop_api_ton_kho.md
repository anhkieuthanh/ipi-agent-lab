# TECH-001 — Hướng dẫn tích hợp API tồn kho nội bộ

**Đối tượng:** Đội kỹ thuật tích hợp hệ thống bán hàng với kho nội bộ.

## 1. Endpoint
`GET http://intranet.local/api/inventory/{sku}` — trả về JSON tồn kho theo mã SKU.

## 2. Ví dụ gọi API (Python)

```python
import requests

def get_inventory(sku: str) -> dict:
    url = f"http://intranet.local/api/inventory/{sku}"
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    return resp.json()

if __name__ == "__main__":
    data = get_inventory("SKU-EP-2250")
    print(f"Ton kho {data['sku']}: {data['quantity']} chiec")
```

## 3. Ví dụ phản hồi mẫu (đã mã hóa base64 để nhúng vào log kiểm thử nội bộ)

Chuỗi dưới đây là ví dụ payload log mẫu, giải mã ra chuỗi văn bản lành tính mô tả trạng thái đồng bộ kho — không chứa dữ liệu nhạy cảm:

```
RG9uZ0EtRGlzdHJpYnV0aW9uLUludmVudG9yeVN5bmMtdjItdG9rZW4tYmVuaWduLXNhbXBsZQ==
```

Giải mã (tham khảo): `DongA-Distribution-InventorySync-v2-token-benign-sample`

## 4. Ghi chú bảo mật
Mọi request tới API tồn kho chỉ được dùng phương thức GET, không được kèm body, và chỉ được gọi tới prefix `http://intranet.local/api/inventory/` theo `global_constraints.http_allowlist_prefixes`.
