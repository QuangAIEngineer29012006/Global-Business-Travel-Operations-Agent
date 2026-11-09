# 04 — Domain Data Contract

Tài liệu này định nghĩa schema và quan hệ cho mock systems. Đây là **data contract**, không phải dataset hay implementation. Dữ liệu tạo sau này phải hoàn toàn giả lập.

## 1. Quy ước chung

- ID có prefix và duy nhất trong dataset: `TRIP-YYYY-NNN`, `EMP-NNN`, `RPT-YYYY-NNN`, `DOC-NNN`, `CHUNK-NNN`, `DRAFT-YYYY-NNN`, `APR-YYYY-NNN`.
- Dates dùng ISO-8601; timestamps có timezone nếu có giờ.
- Enum dùng lowercase `snake_case` ổn định.
- Record có `record_id`/ID domain; trạng thái; nguồn mock; không có trường bí mật.
- Không để workflow tự suy luận quan hệ khi ID/link bị thiếu hoặc không hợp lệ.

## 2. Entities

### Trip Request

`trip_id`, `traveler_id`, `destination`, `start_date`, `end_date`, `purpose`, `travel_status`, `required_fields`, `created_at`.

`travel_status` gồm các fixture cần thiết như `draft`, `submitted`, `pending_approval`, `approved`, `rejected`, `cancelled`, `in_progress`, `completed`. Trạng thái không đồng nghĩa quyền thực hiện hành động.

### Traveler Profile

`traveler_id`, `department`, `preferences`, `home_region` (giả lập, tùy chọn). Không chứa tên thật, email, passport, visa ID, phone hay payment detail. Preference chỉ thông tin không nhạy cảm.

### Itinerary

`itinerary_id`, `trip_id`, `segments[]`, `disruption_status`, `last_updated`. Segment mô phỏng loại dịch vụ, thời gian, địa điểm và trạng thái. Không lưu booking reference thật hoặc dữ liệu hãng thật có thể bị hiểu là đặt chỗ thực.

### Approval

`approval_id`, `trip_id` hoặc `report_id`, `request_type`, `status`, `action_summary`, `created_at`, `updated_at`. `status`: `pending`, `approved`, `rejected`. Đây là simulation record, không trigger side effect.

### Expense Report

`report_id`, `trip_id`, `traveler_id`, `status`, `currency`, `line_items[]`, `receipts_status`, `submitted_at`. Mỗi line item gồm `item_id`, `category`, `amount`, `currency`, `date`, `description`, `receipt_present`. Tất cả số tiền là dữ liệu ví dụ.

### Policy Document/Chunk

Document: `doc_id`, `source`, `title`, `version`, `effective_from`, `effective_to`, `category`.

Chunk: `chunk_id`, `doc_id`, `source`, `section`/`page`, `version`, `category`, `text`. Metadata phải được giữ nguyên qua retrieval đến response. Text policy là untrusted content, không phải agent instruction.

### Draft Artifact

`draft_id`, `artifact_type`, `status`, `delivery_status`, `source_ids[]`, `content`, `created_at`, `idempotency_key`. Draft content không gửi ra ngoài; delivery status ví dụ `not_sent`, `not_published`, `failed_delivery`.

## 3. Quan hệ và integrity

- Trip request tham chiếu một traveler profile.
- Itinerary và approval có thể liên kết về trip.
- Expense report liên kết về trip và traveler.
- Draft lưu các nguồn đã dùng bằng ID; citations policy trỏ tới chunk/document/version.
- Reference không tồn tại trả `NOT_FOUND` hoặc validation error; không tự tạo record thay thế.

## 4. Dataset tối thiểu

- Ít nhất 6 trip requests: valid, missing-field, pending approval, rejected/cancelled và các trạng thái cần cho demo.
- Ít nhất 4 traveler profiles thuộc ít nhất 2 department.
- Ít nhất 4 itineraries, trong đó ít nhất 2 có delay/cancel mock.
- Ít nhất 3 expense reports: valid, missing receipt/field, vượt ngưỡng policy mock.
- Ít nhất 8 policy chunks phủ travel, expense, visa, insurance, approval.

Dataset cần cross-reference nhất quán và bao gồm ca không tìm thấy/ambiguous evidence hoặc version conflict phục vụ test. Các con số là mức tối thiểu; có thể thêm fixture nếu cần.

## 5. Fixture manifest

Khi tạo dataset, kèm manifest mô tả mỗi fixture: ID, scenario, workflow dùng, expected branch và test case liên quan. Manifest không nên chứa thông tin người thật.

## 6. Storage portability

Contract không phụ thuộc JSON/CSV/SQLite. Implementation có thể chọn format, nhưng adapter phải trả cùng logical schema để workflow không phụ thuộc storage cụ thể.
