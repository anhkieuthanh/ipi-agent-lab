# Product

> Nội dung soạn với sự hỗ trợ của AI (Claude), từ phỏng vấn TA và tài liệu đồ án.

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **TA (sinh viên thực hiện)** vận hành hằng ngày: chạy thí nghiệm, theo dõi lô, đọc trace từng
  lượt chạy, đối chiếu số liệu trước khi đưa vào báo cáo.
- **GVHD và hội đồng chấm** xem qua máy chiếu khi họp hướng dẫn và khi bảo vệ: cần nắm câu chuyện
  tấn công, phòng thủ, kết quả trong vài phút và đọc được số từ xa.

## Product Purpose

IPI Guard Console là giao diện của testbed đánh giá và phòng chống tấn công tiêm nhiễm gián tiếp
(Indirect Prompt Injection) trên AI agent dùng RAG và MCP tool-calling. Nó cho chạy một kịch bản
thật, xem agent bị tiêm qua kênh nào, phòng thủ D1–D4 chặn ở bước nào, và tổng hợp ASR/DSR/ARR/USR
theo model, kênh, kỹ thuật. Thành công là: người xem hiểu một lượt tấn công từ đầu đến cuối và tin
được mọi con số vì truy được tới run và trace.

## Positioning

Testbed agent doanh nghiệp Việt có kiểm soát, đo lặp lại được, đánh giá phòng thủ theo cặp an toàn
và hữu dụng, có tính đến kẻ tấn công thích ứng. Mọi số liệu là số đo thật trên harness đã pin phiên bản.

## Operating Context

- Chạy cục bộ: API FastAPI cổng 8610 (Docker `ipi-console`), giao diện Vite 5180 khi phát triển.
- Demo trước GVHD chỉ chạy thật, không có chế độ model mô phỏng.
- Có chế độ trình bày cho máy chiếu.
- Dữ liệu khách hàng là mô phỏng (Faker `vi_VN`, seed cố định).

## Capabilities and Constraints

- Mười trang: Tổng quan, Chạy thí nghiệm, Lô thực nghiệm, Tấn công, Phòng thủ, Lượt chạy, Chi tiết
  lượt chạy, Sơ đồ hệ thống, Cấu hình, Quy trình.
- Thuật ngữ cố định: TS1–TS3, A1–A3, G1–G3, K1–K5, T1–T8, D1–D4, CT-01–CT-06, U1–U5.
- `blocked_by ∈ {defense, model_refusal, harness}` luôn tách riêng; "model từ chối" không bao giờ
  hiện thành "phòng thủ chặn".
- Chưa đo không hiện thành 0%. Tỉ lệ kèm mẫu số và khoảng tin cậy Wilson 95%.
- Giao diện tiếng Việt.

## Evidence on Hand

Số liệu thật từ `results/` và trace qua API. Không có logo, lời chứng thực, hay số liệu ngoài harness;
không được bịa.

## Product Principles

1. Số liệu trung thực trước, đẹp sau: mỗi con số truy được nguồn, mẫu số luôn đi kèm.
2. Kể đúng một câu chuyện mỗi màn hình: tấn công vào đâu, phòng thủ làm gì, kết cục ra sao.
3. Đọc được từ xa: hội đồng nhìn qua máy chiếu phải thấy ngay điều chính.
4. Phân biệt rõ ai chặn: phòng thủ, model tự từ chối, hay harness.

## Accessibility & Inclusion

Màu không là kênh duy nhất cho kết cục. Dùng được bằng bàn phím. Tương phản đủ cho máy chiếu.
