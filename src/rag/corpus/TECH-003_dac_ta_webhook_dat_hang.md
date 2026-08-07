# TECH-003 — Đặc tả webhook đặt hàng

**Đối tượng:** Đội tích hợp hệ thống đặt hàng với đối tác vận chuyển.

## 1. Sự kiện webhook
Khi một đơn hàng được xác nhận, hệ thống gửi POST tới endpoint đăng ký của đối tác với payload JSON.

## 2. Ví dụ payload (Node.js xử lý webhook)

```javascript
const express = require("express");
const app = express();
app.use(express.json());

app.post("/webhook/order-confirmed", (req, res) => {
  const { orderId, sku, quantity, customer } = req.body;
  console.log(`Don hang ${orderId}: ${quantity}x ${sku} cho ${customer}`);
  res.status(200).json({ status: "received" });
});

app.listen(3000);
```

## 3. Chữ ký xác thực webhook (secret mẫu, đã mã hóa base64 để minh họa định dạng)

```
d2ViaG9vay1zZWNyZXQtcGxhY2Vob2xkZXItRE8tTk9ULVVTRS1JTi1QUk9ELTAwMDAwMDAwMDA=
```

Lưu ý: đây là secret PLACEHOLDER dùng trong tài liệu hướng dẫn định dạng, không phải secret thật đang vận hành. Secret thật được quản lý qua kho bí mật nội bộ, không lưu trong tài liệu.
