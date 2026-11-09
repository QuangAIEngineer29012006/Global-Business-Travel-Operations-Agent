# Bộ dữ liệu giả lập

Các fixture phục vụ huấn luyện prototype. Toàn bộ nhân vật, đơn vị, nội dung chính sách, số tiền, lịch trình và sự kiện đều hư cấu; không đại diện cho đặt chỗ thật hay chính sách có thẩm quyền.

## Thành phần và định dạng

- `travel-requests/travel_requests.csv`: 8 yêu cầu chuyến đi.
- `traveler-profiles/traveler_profiles.json`: 6 hồ sơ thuộc nhiều phòng ban; chỉ có sở thích không nhạy cảm.
- `itineraries/itineraries.json`: 6 lịch trình dạng lồng nhau, có các ca delay và cancellation.
- `approvals/approvals.csv`: quyết định chuyến đi và expense giả lập ở trạng thái pending, approved, rejected.
- `expenses/expense_reports.json`: 3 báo cáo gồm chứng từ đầy đủ, thiếu chứng từ và cần reviewer rà soát.
- `policy-knowledge-base/documents/*.md`: 5 tài liệu chính sách giả lập, tổng cộng 9 chunks thuộc travel, expense, visa, insurance và approval.
- `policy-knowledge-base/chunk_metadata.csv`: chỉ mục metadata để truy xuất và tạo citations.
- `draft-workspace/drafts.json`: kho draft sandbox ban đầu đang rỗng.
- `fixture-manifest.csv`: mô tả các kịch bản và nhánh workflow dự kiến.

## Quy ước dữ liệu

Tên cột/field, ID, enum trạng thái và tên tool giữ tiếng Anh để khớp schema code. Nội dung mô tả cho người dùng và văn bản policy dùng tiếng Việt. Ngày theo ISO-8601; ID chỉ là mã giả lập.

## Quan hệ dữ liệu

`trip_requests.traveler_id` trỏ tới traveler profile. Mỗi itinerary liên kết một trip. Expense report liên kết trip và traveler. Approval liên kết trip hoặc report. `chunk_id` trong metadata phải khớp chunk trong tài liệu policy.

## Ghi chú nạp dữ liệu

- Đọc CSV và JSON bằng UTF-8; JSON có thể là mảng ở cấp cao nhất.
- Front matter YAML trong tài liệu Markdown chứa metadata tài liệu. Heading chunk chứa `chunk_id` và section; cần giữ `doc_id`, `source`, `version`, `category`, `chunk_id` và section khi index.
- Ngưỡng expense trong policy là giả lập, chỉ để kiểm thử truy xuất và gắn cờ reviewer.

## Giới hạn

Dataset không có tư vấn thị thực theo quốc gia, dữ liệu du lịch trực tiếp, chính sách thật, quy đổi tiền tệ, kết luận phạm vi bảo hiểm, credential production hoặc PII. Không dùng nội dung này làm hướng dẫn có thẩm quyền.
