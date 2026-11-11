# Design — IPI Guard Console

Nội dung thiết kế soạn với sự hỗ trợ của AI.

## Hướng thiết kế
Công cụ kỹ thuật mật độ cao, lấy số liệu và trace làm trung tâm. Chữ, khoảng cách và đường kẻ mảnh
tạo phân cấp; không dùng thẻ trang trí, ô biểu tượng, gradient hay bóng đổ. Màu chỉ mang nghĩa kết quả.
Giữ mọi route và chức năng; mỗi con số truy được tới run và trace.

## Nguồn sự thật
- `web/src/tokens.css`: mọi màu (bộ ba RGB, hai bộ sáng/tối), phông, kích thước khung. Không khai màu ở nơi khác.
- `web/tailwind.config.js`: chỉ ánh xạ token sang lớp Tailwind; thang `slate` trỏ về token trung tính nên tự đảo khi tối.
- `web/src/components/ui.tsx`: bộ thành phần gốc. Trang chỉ ghép thành phần, không tự dựng nút, nhãn, thẻ.
- `web/src/lib/nav.ts`: cấu trúc điều hướng, dùng chung cho thanh bên, đường dẫn vị trí, bảng lệnh, phím tắt.

## Chữ
Inter (variable) cho giao diện, JetBrains Mono cho mã, ID, trace. Thang chữ duy nhất:
11 · 12 · 13 (thân) · 14 · 15 · 16 · 20 · 24 · 28 px. Không dùng cỡ tùy ý. Số trong bảng dùng `num`
(chữ số đều cột) và canh phải.

## Màu ngữ nghĩa
attack (đỏ) = tấn công thành công · defense (xanh lá) = phòng thủ chặn · refusal (tím) = model tự từ chối ·
payload (cam) = nội dung tiêm · canary (xanh dương) = dấu rò rỉ · amber = cảnh báo, lỗi hạ tầng.
Màu không bao giờ là kênh duy nhất: kết cục luôn có chữ (`Status`, `Badge`), điểm biểu đồ có nhãn trực tiếp.

## Khung ứng dụng
Thanh bên 232px (ẩn thành ngăn kéo dưới 768px). Một thanh trên 48px: vị trí · phạm vi dữ liệu · trạng thái
dịch vụ · làm mới · sáng/tối · trình bày. Nội dung tối đa 1360px.
Bảng lệnh ⌘K / Ctrl+K: trang, lô, mã run, tìm run. Phím tắt `g` + chữ đổi trang; ↑/↓ hoặc J/K trong trace.
Chế độ trình bày: ẩn thanh bên và thao tác phụ (`data-chrome`), phóng nội dung; Esc để thoát.

## Thành phần
Khối nội dung: `Card` viền 1px, bo 8px, `CardHeader` tiêu đề 13px đậm và một dòng phụ ngắn; giải thích dài
đặt trong `Disclosure` hoặc `InfoDot`. Bảng `table-base`: tiêu đề dính, hàng ~36px, bảng rộng cuộn trong khung.
Nút: primary nền đậm, secondary viền mảnh, ghost; cao 28/32px. `Tabs` gạch chân cho các mặt của một đối tượng,
`Segmented` cho chế độ xem. Tải dữ liệu bằng khung giữ chỗ (`Skeleton`), không vòng xoay giữa trang.
Biểu đồ vẽ bằng SVG tự viết (`components/charts.tsx`), không thư viện biểu đồ.

## Trung thực số liệu
Chưa đo không bao giờ hiện thành 0%. Mọi tỉ lệ kèm mẫu số và khoảng tin cậy Wilson 95%.
`blocked_by` (phòng thủ · model từ chối · harness) luôn gọi tên riêng. Phiên bản chưa tải hiện “—”, không đoán.
Bản dựng lại (vd mô tả tool K2a) ghi rõ là dựng lại.

## Tương tác và trợ năng
Focus hiển thị rõ; mọi thao tác dùng được bằng bàn phím; tooltip mở được bằng focus. Vùng chạm ≥ 32px trên
desktop. Không cuộn ngang trang ở 375px. Chuyển động 120ms, tắt khi `prefers-reduced-motion`.
