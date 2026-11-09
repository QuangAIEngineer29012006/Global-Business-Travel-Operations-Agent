# 05 — Yêu cầu tích hợp workflow

Tài liệu này giúp các workflow owner triển khai đúng kiến trúc/contract. Đây là yêu cầu tích hợp; chưa mô tả hay tạo dataset thực tế.

## 1. Quy tắc chung cho mọi workflow

- Khai báo workflow name, actor roles được phép, required inputs/context, allowlisted tools và terminal outcomes.
- Kiểm tra ID/required fields trước khi gọi tools; thiếu thông tin thì hỏi, không phỏng đoán.
- Đọc business facts từ mock source of truth trong run hiện tại.
- Policy claim phải có citation; tách rõ observed facts khỏi policy guidance.
- Mọi tool call qua dispatcher; xử lý structured errors theo retryability.
- Cập nhật run state, step budget và trace ở từng transition.
- Action-like output chỉ là draft/simulation. Không tuyên bố gửi/publish/thanh toán/đặt dịch vụ thật.
- Khi evidence, approval hoặc input không đủ, kết thúc rõ ràng bằng `needs_input`, `needs_human`, `awaiting_approval` hoặc status phù hợp.

## 2. Pre-trip planning and compliance

**Input:** `trip_id` hoặc yêu cầu đủ dữ kiện để xác định trip; nếu thiếu/ambiguous, hỏi lại.

**Tối thiểu:** validate ID → đọc trip → đọc approval status → retrieval policy liên quan destination/trip category → validate requirements dựa trên facts + evidence → tạo travel checklist draft nếu phù hợp.

**Không được:** nói trip đã approved nếu source không trả `approved`; tạo claim policy không có citation; coi policy là authorization để book.

**Expected output:** checklist draft và citations hoặc câu hỏi/needs-human outcome.

## 3. In-trip disruption support

**Input:** `trip_id` và disruption signal; nếu thiếu, hỏi lại.

**Tối thiểu:** validate ID → đọc itinerary → phân loại disruption từ itinerary observation → retrieval relevant travel/emergency policy khi cần → tạo escalation/support draft hoặc needs-human.

**Không được:** tự rebook, đổi chuyến, đặt khách sạn, chi tiền hoặc liên hệ nhà cung cấp.

**Expected output:** phân biệt itinerary facts với policy guidance; escalation draft có sources; status rõ ràng.

## 4. Post-trip expense pre-check

**Input:** `report_id`.

**Tối thiểu:** validate ID → đọc report → chạy deterministic summary/validation → retrieve policy cho category liên quan → tạo review draft nêu facts, evidence và items cần reviewer kiểm tra.

**Không được:** quyết định trả tiền/hoàn tiền hoặc tuyên bố expense đã approved; LLM không tính tổng từ raw text thay cho deterministic tool.

**Expected output:** tổng và flags từ tool, citations hỗ trợ policy notes, draft review và terminal status.

## 5. Idempotency và partial failure

- Ghi nhận trạng thái `draft_created`, `awaiting_approval`, `approved`, `publish_requested` và `published` tách biệt; project này không có publish thật.
- Retry cùng request/intent phải không tạo duplicate artifact.
- Nếu tạo draft thành công nhưng bước sau lỗi, trả `partial` cùng artifact ID đã có.
- Nếu delivery simulation lỗi, phản ánh `failed_delivery`; không xóa/che giấu artifact đã tạo.

## 6. Interface checklist cho workflow owner

Trước khi báo hoàn tất, mỗi workflow cung cấp:

- Workflow contract (role/input/required context/tools/outcomes).
- Một happy path và các safe-failure branches.
- Tool sequence và dependency rõ ràng.
- Ví dụ request/response có evidence/artifact reference.
- Trace sample đủ để đánh giá transitions và budget.
- Test case IDs do evaluation owner dùng.
