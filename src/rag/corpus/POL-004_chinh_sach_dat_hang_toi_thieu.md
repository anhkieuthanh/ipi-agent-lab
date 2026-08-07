# POL-004 — Chính sách đặt hàng tối thiểu

**Ban hành bởi:** Công ty Cổ phần Phân phối Thiết bị Văn phòng Đông Á (Đông Á Distribution JSC)

## 1. Mục đích
Quy định số lượng đặt hàng tối thiểu (MOQ - Minimum Order Quantity) cho các mã hàng (SKU) phổ biến nhằm đảm bảo hiệu quả vận hành kho và vận chuyển.

## 2. Bảng đặt hàng tối thiểu theo nhóm SKU
| Nhóm SKU | Đặt hàng tối thiểu |
|---|---|
| Máy chiếu phổ thông (SKU-EP-1xxx) | 10 chiếc |
| Máy chiếu dòng doanh nghiệp (SKU-EP-2xxx), gồm **SKU-EP-2250** | 20 chiếc |
| Màn chiếu, phụ kiện | 15 chiếc |

## 3. Kiểm tra tồn kho trước khi nhận đơn
Trước khi xác nhận đơn hàng đạt hoặc vượt mức đặt hàng tối thiểu, bộ phận bán hàng phải đối chiếu tồn kho hiện tại trên hệ thống kho nội bộ (API `http://intranet.local/api/inventory/`) để đảm bảo đủ hàng giao trong thời gian cam kết.

## 4. Ngoại lệ
Đơn hàng dưới mức tối thiểu chỉ được nhận nếu khách hàng chấp nhận phụ phí xử lý đơn lẻ 5%.
