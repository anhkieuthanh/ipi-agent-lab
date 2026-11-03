# Design — IPI Guard

<!-- Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4 -->
Nội dung thiết kế soạn với sự hỗ trợ của AI.

## Hướng thiết kế
Modern-minimal. Bàn làm việc nghiên cứu và vận hành: sidebar cố định với bốn nhóm,
thanh phạm vi, nội dung, nguồn dữ liệu. Giữ tất cả route và chức năng hiện có.
Trang Tổng quan dùng dải ba chỉ số, một biểu đồ, bảng truy tới bằng chứng.
Trang phân tích và thực nghiệm dùng bảng và các vùng nội dung phân cấp.

## Hệ thống dùng chung
Nguồn màu và khoảng cách: `web/src/tokens.css`. Nền sáng, than đậm cho thao tác và
phân cấp; đỏ/xanh lá chỉ mang nghĩa kết quả. Be Vietnam Pro dùng cho tiêu đề và
nội dung, JetBrains Mono dùng cho mã và trace. Không thêm font.
Thẻ có đường viền mảnh, bo 12px, không bóng. Không gradient, không hiệu ứng xuất hiện.
Giữ nguyên các màu ngữ nghĩa payload/canary/refusal để truy vết.
Các màn hình chia sẻ header, nav, màu, cỡ chữ, button và nhịp khoảng cách.

## Hai chế độ
Làm việc: hiện bộ lọc, cập nhật dữ liệu, cấu hình và điều hướng phụ.
Trình bày: ẩn nav, cố định phạm vi đã chọn, tăng cỡ chữ, ưu tiên chỉ số và biểu đồ.
Luôn hiện nút về làm việc; Escape thoát chế độ trình bày. Lưu lựa chọn trong phiên.
Không thêm phân quyền hay nhật ký thao tác giả vào giao diện.

## Tương tác
Nút chính navy, nút phụ viền mảnh. Focus hiển thị rõ, hỗ trợ bàn phím và cảm ứng.
Bảng cuộn trong vùng riêng. Responsive 320/375/414/768px.
Motion ngắn 150ms; tôn trọng prefers-reduced-motion.

## UI UX Pro Max — quy tắc áp dụng
Tham chiếu skill cài tại `~/.codex/skills/ui-ux-pro-max`. Áp dụng gợi ý
Minimalism & Swiss Style phù hợp dashboard; giữ palette sáng/navy và font tiếng
Việt đã chốt. Không dùng bố cục marketing/Contact Sales do bộ tìm kiếm gợi ý.
Chữ phụ ít nhất 12px, vùng bấm mobile 44px cho thao tác chính; bảng dùng vùng cuộn riêng.
Tìm kiếm run debounce 300ms, bộ lọc và trang nằm trên URL để quay lại từ trace.
Chỉ vẽ chuỗi chỉ số đã đo; nhãn trực tiếp và bảng số liệu có mẫu số/CI là cách
đọc không phụ thuộc màu hay hover. Chưa đo không được trình bày thành 0%.
Trạng thái bộ lọc công bố qua aria-pressed; lỗi có thử lại tại chỗ, giữ trạng thái trang.

## Khối nội dung
Icon 22px trong ô 42px ở phía trên tiêu đề của mỗi khối. Tiêu đề 2–4 từ;
chú thích dài mở qua Chi tiết. Sidebar 224px, toolbar một hàng, nội dung nền sáng.
Thẻ phòng thủ D1–D4 theo lưới; chỉ số có biểu tượng độc lập. Giữ dữ kiện đo lường,
phân biệt chưa đo và 0%; cảnh báo và nguyên nhân chặn luôn đọc được.
