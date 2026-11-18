# Design — IPI Guard Console

Nội dung thiết kế soạn với sự hỗ trợ của AI.

## Hướng thiết kế
"Console": thiết bị đo của một phòng thí nghiệm cẩn thận. Nền ba bậc, bảng cắt từ một mặt phẳng bằng đường
kẻ 1px, không bóng đổ, không phát sáng, không gradient. Chữ người đọc dùng Be Vietnam Pro; thứ thiết bị đo ghi
(số liệu, mã, trace, thời điểm) dùng IBM Plex Mono. Mỗi màn hình đặt lớn một số đo hoặc một bản ghi; phần còn
lại lùi xuống. Giữ mọi route và chức năng; mỗi con số truy được tới run và trace.

## Nguồn sự thật
- `web/src/tokens.css`: mọi màu (bộ ba RGB, hai chế độ), phông, kích thước khung. Không khai màu ở nơi khác.
- `web/tailwind.config.js`: chỉ ánh xạ token sang lớp Tailwind; thang `slate` trỏ về token trung tính nên tự đảo khi tối.
- `web/src/components/ui.tsx`: bộ thành phần gốc. Trang chỉ ghép thành phần, không tự dựng nút, nhãn, thẻ.
- `web/src/lib/nav.ts`: cấu trúc điều hướng, dùng chung cho thanh bên, đường dẫn vị trí, bảng lệnh, phím tắt.
- `PRODUCT.md`: người dùng, mục đích, nguyên tắc sản phẩm.

## Hai chế độ
- **Paper** (sáng, mặc định khi hệ điều hành sáng): nền giấy ấm `ground`, bảng `surface` sáng hơn một bậc,
  bậc sâu nhất `n-50` cho tiêu đề bảng, mã, hàng được chọn. Hợp máy chiếu.
- **Graphite** (tối): nền than chì ba bậc, chữ nhạt. Hợp vận hành lâu.

## Chữ
Be Vietnam Pro 400/500/600 cho giao diện (đủ dấu tiếng Việt); IBM Plex Mono 400/500 cho số đo, mã, trace,
chữ số có số 0 gạch. Không dùng mono cho nhãn, tiêu đề, nút. Thang chữ duy nhất:
12 · 13 · 14 (thân) · 15 · 16 · 18 · 22 · 28 · 36 · 48 px. Tiêu đề trọng lượng 500, không đậm 700.
Số đo lớn dùng lớp `.reading` (mono, chữ số đều cột). Số trong bảng dùng `num` và canh phải.

## Màu
- **brand = hổ phách**: thao tác chính duy nhất mỗi vùng, mục điều hướng hiện tại, lựa chọn trong `Segmented`,
  tab đang mở, focus. Hổ phách là thứ con người làm; không dùng làm nền diện rộng.
- **canary = lam lạnh**: dấu rò rỉ, và tỉ lệ đo được không mang nghĩa tấn công/phòng thủ (USR, tỉ lệ tới đích).
- Màu kết cục: attack (đỏ) = tấn công thành công · defense (xanh lá) = phòng thủ chặn · refusal (tím) =
  model tự từ chối · payload (cam) = nội dung tiêm · amber = cảnh báo, lỗi hạ tầng.
Màu không bao giờ là kênh duy nhất: kết cục luôn có chữ (`Status`, `Badge`), điểm biểu đồ có nhãn trực tiếp.
Đánh dấu trạng thái là vạch dọc 3px cạnh chữ, không dùng chấm tròn.

## Khung ứng dụng
Không thanh bên: nội dung dùng hết bề ngang (tối đa 1440px), hợp máy chiếu. Thanh trên dính, hai tầng:
- Tầng trên (56px): biểu tượng, các bước của luồng: Tổng quan, ô số 1 "Thí nghiệm", ô số 2 "Phân tích",
  "Hệ thống" (tham chiếu, không đánh số). Bước hiện tại gạch chân hổ phách, ô số tô hổ phách. Bên phải: tìm
  kiếm ⌘K, làm mới, sáng/tối, trình bày.
- Tầng dưới (44px, nền bảng): các trang của bước hiện tại dạng tab gạch chân (ở chi tiết run: đường dẫn về
  danh sách), phạm vi dữ liệu, trạng thái dịch vụ.
Chân trang: trạng thái kết nối và hai phiên bản đang ghim. Dưới 768px các bước gập vào ngăn kéo bên trái.
Bảng lệnh ⌘K / Ctrl+K: trang, lô, mã run, tìm run. Phím tắt `g` + chữ đổi trang; ↑/↓ hoặc J/K trong trace.
Chế độ trình bày: ẩn thao tác phụ (`data-chrome`), phóng nội dung 1.2 lần; Esc để thoát.

## Bố cục màn hình
- **Hàng câu hỏi (`Question`)** là đơn vị của trang phân tích, kiểu báo cáo khoa học: cột trái 320px dính khi
  cuộn gồm câu hỏi (kèm mã RQ nếu có), câu trả lời ngắn bằng số đo lớn (`Reading`), cách đọc bằng chứng và điều
  khiển; cột phải là bằng chứng (bảng, biểu đồ). Các hàng ngăn bằng đường kẻ 1px. Dùng ở Tổng quan (ba câu:
  tấn công lọt bao nhiêu, agent còn hữu dụng không, số liệu lấy từ đâu), Tấn công (RQ1, RQ2), Phòng thủ (RQ3,
  RQ4, đánh đổi, chặn nhầm), Hệ thống, Cấu hình, Quy trình.
- **Thí nghiệm:** ba bước thiết lập là ba cột ngang (kịch bản, phòng thủ, thiết lập), thanh tóm tắt và nút chạy
  trải ngang bên dưới; sơ đồ phòng thủ và diễn biến trực tiếp trải hết chiều ngang.
- **Chi tiết run:** cột trái 360px dính là hồ sơ run (kết luận, mục tiêu đạt, câu hỏi của nhân viên, thông số);
  cột phải là các tab bằng chứng.
- **Lượt chạy:** cột lọc dọc 248px dính bên trái, danh sách bên phải.
- **Hệ thống:** sơ đồ kiến trúc là hình chính, trải ngang, tiêu đề đứng ngoài khung như chú thích hình.

## Thành phần
`PageHeader`: tiêu đề 28px và một câu lede luôn hiện, nói trang này trả lời câu hỏi gì; giải thích dài vào `InfoDot`.
Khối nội dung: `Card` viền 1px, bo 10px; trong hàng câu hỏi, thẻ không mang tiêu đề riêng. Chỉ số đứng cạnh nhau
cắt từ một mặt phẳng, ngăn bằng khe 1px.
`Metric`: nhãn, số đo `.reading` 48px, mẫu số và CI xuống dòng riêng; `step` đánh số khi các chỉ số kể một
câu chuyện (tấn công → phòng thủ → hữu dụng). Bảng `table-base`: tiêu đề dính trên bậc sâu, hàng ~44px.
Nút: primary nền hổ phách chữ `accent-ink`, secondary viền mảnh, ghost; cao 36px (nhỏ 32px), vùng chạm 44px trên
thiết bị con trỏ thô. `Badge` là chip trạng thái: nền nhạt, viền 1px cùng sắc. `Tabs` gạch chân hổ phách cho các
mặt của một đối tượng, `Segmented` cho chế độ xem. Tải dữ liệu bằng khung giữ chỗ (`Skeleton`), không vòng xoay
giữa trang. Biểu đồ vẽ bằng SVG tự viết (`components/charts.tsx`), không thư viện biểu đồ.
Nhãn kết luận viết hoa toàn bộ từ backend hiển thị dạng câu (`sentence()` ở `lib/format.ts`).

## Trung thực số liệu
Chưa đo không bao giờ hiện thành 0%: ô chưa đo ghi "chưa đo", ô không áp dụng ghi "không có". Mọi tỉ lệ kèm
mẫu số và khoảng tin cậy Wilson 95%. `blocked_by` (phòng thủ · model từ chối · harness) luôn gọi tên riêng.
Phiên bản chưa tải hiện "—", không đoán. Bản dựng lại (vd mô tả tool K2a) ghi rõ là dựng lại.

## Chữ trong giao diện
Câu văn không dùng gạch ngang dài; dùng dấu phẩy, hai chấm hoặc chấm câu. Ký hiệu khoảng mã của dự án
(D1–D4, A1–A3, T1–T8) và khoảng số (CI 5%–7%) giữ gạch nối ngắn.

## Tương tác và trợ năng
Chữ phụ dùng token `--text-muted` (tương phản ≥ 5.8:1 trên mọi bậc nền ở cả hai chế độ).
Focus hiển thị rõ, viền hổ phách; mọi thao tác dùng được bằng bàn phím; tooltip mở được bằng focus. Mọi điều
khiển có trạng thái hover, active, focus, disabled. Không cuộn ngang trang ở 375px. Chuyển động 140ms ease-out,
chỉ đổi màu và opacity, tắt khi `prefers-reduced-motion`. Thanh cuộn, vùng chọn chữ, con trỏ nhập lấy màu từ token.

## Luồng thí nghiệm
Điều hướng theo Thí nghiệm → Phân tích → Hệ thống; thao tác chạy đứng trước danh sách lô.
Trang Thí nghiệm đánh số ba bước thiết lập (kịch bản, phòng thủ, thiết lập), có tóm tắt kịch bản, tên model,
phòng thủ và số lượt ngay trước nút chạy. Kết quả hoàn tất đứng trước thiết lập: đối chứng tắt phòng thủ bên trái,
bản bật bên phải; kết cục → bước quyết định đã ghi trong trace → bằng chứng mở rộng → chi tiết. Không suy diễn nhân quả.
Trạng thái tải có nhãn nhìn thấy; lỗi có hành động thử lại, chi tiết kỹ thuật thu gọn.
