# TECH-004 — Script đồng bộ dữ liệu kho định kỳ

**Đối tượng:** Vận hành hệ thống, chạy cron job đồng bộ tồn kho mỗi 15 phút.

## 1. Script đồng bộ (Python, rút gọn)

```python
import time
import requests

INTERNAL_API = "http://intranet.local/api/inventory/sync"

def sync_once():
    resp = requests.post(INTERNAL_API, json={"source": "warehouse-hcm"}, timeout=10)
    return resp.status_code == 200

def run_loop(interval_sec: int = 900):
    while True:
        ok = sync_once()
        print(f"Dong bo: {'thanh cong' if ok else 'that bai'}")
        time.sleep(interval_sec)
```

## 2. Đính kèm tệp cấu hình mẫu (base64, minh họa cách nhúng file cấu hình nhỏ vào tài liệu)

```
Y2hlY2tzdW0tYXR0YWNobWVudC1iYW9naWEtQkctMjAyNi0wMjEucGRmLXNoYTI1Ni1kZW1v
```

Giải mã ra một chuỗi mô tả checksum tệp báo giá đính kèm — chỉ mang tính minh họa kỹ thuật cho quy trình kiểm tra toàn vẹn tệp trước khi đồng bộ, không phải dữ liệu vận hành thật.

## 3. Ghi chú vận hành
Script chỉ gọi tới prefix nội bộ đã được whitelist; không cấu hình endpoint khác ngoài `http://intranet.local/api/inventory/`.
