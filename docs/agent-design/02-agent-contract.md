# 02 — Agent Contract

## 1. Actor roles

| Role | Quyền prototype |
|---|---|
| `employee` | Đọc dữ liệu mock theo actor scope; chạy workflow hỗ trợ; yêu cầu draft |
| `travel_operations_reviewer` | Đọc/rà soát dữ liệu và draft trong phạm vi mock; yêu cầu escalation draft |
| `approver` | Đọc trạng thái approval giả lập trong scope demo; prototype không cung cấp tool để approve/reject |

Mọi record mock cần có ownership/scope để kiểm tra truy cập. Nếu không triển khai authentication thật, actor role/scope phải được truyền rõ trong request fixture và chỉ dùng cho demo/test.

## 2. Request envelope

Request chuẩn cần chứa:

```json
{
  "request_id": "REQ-2026-001",
  "actor": { "role": "employee", "actor_id": "EMP-001" },
  "session_id": "SES-001",
  "message": "Help me prepare for my trip",
  "context": { "trip_id": "TRIP-2026-001" }
}
```

- `request_id`: định danh request duy nhất.
- `actor.role`, `actor_id`: vai trò và scope của người gọi.
- `session_id`: scope hội thoại; không dùng thay actor identity.
- `message`: yêu cầu nguyên gốc.
- `context`: ID đã có; trường có thể vắng mặt nếu workflow sẽ hỏi người dùng.
- `actor_id` và `session_id` là khóa scope cho mock state trong prototype, không phải credential hay cơ chế authentication.

Unknown properties bị từ chối hoặc bỏ qua theo schema cấp API; không bao giờ dùng field chưa xác thực để cấp quyền.

## 3. Response envelope

```json
{
  "request_id": "REQ-2026-001",
  "run_id": "RUN-2026-001",
  "workflow": "pre_trip",
  "status": "completed",
  "message": "Checklist draft created.",
  "data": {},
  "evidence": [],
  "artifacts": [],
  "next_action": null
}
```

- `data` chỉ gồm dữ kiện quan sát được từ tools và kết quả tính xác định.
- `evidence` gồm policy citations khi có claim policy.
- `artifacts` chỉ tham chiếu draft giả lập, kèm trạng thái delivery.
- `next_action` diễn tả câu hỏi, human review hoặc approval simulation cần tiếp tục.

## 4. Terminal outcomes

| Status | Ý nghĩa |
|---|---|
| `completed` | Workflow hoàn tất trong phạm vi; có thể đã tạo draft |
| `needs_input` | Thiếu ID hoặc trường cần thiết; chờ user bổ sung |
| `needs_human` | Cần reviewer/human phán đoán hoặc evidence chưa đủ |
| `awaiting_approval` | Approval simulation đang pending; chưa có approval |
| `failed_validation` | Input/ID/schema/domain validation thất bại |
| `partial` | Một phần hoàn tất, phần khác lỗi hoặc hết budget |
| `failed_delivery` | Draft delivery simulation thất bại; không ngụ ý publish thật |
| `rejected` | Yêu cầu ngoài phạm vi hoặc bị policy access guard từ chối |

Không diễn đạt `pending` hoặc `rejected` như `approved`. `completed` không có nghĩa hành động production đã diễn ra.

## 5. Run state

Mỗi run lưu tối thiểu:

- `run_id`, `request_id`, `session_id`, actor scope tối thiểu.
- `workflow`, `phase`, `step_count`, `max_steps`.
- Tool calls/observations có lọc, `trace_id`.
- Evidence references và artifact IDs.
- `terminal_status`, reason code và timestamps.

Run state chỉ phục vụ điều phối và audit. Business facts phải đọc lại từ mock source of truth.

### 5.1. Lưu run

Prototype lưu một bản tóm tắt cho mỗi execution gồm `run_id`, `request_id`, actor/session scope giả lập, workflow, phase kết thúc, `steps`, `max_steps`, `terminal_status`, `reason_code`, timestamp hoàn tất, artifact IDs, evidence chunk IDs và safe trace. Tool observation trong trace chỉ ghi `ok`, error code, source system và tên các field trả về; không ghi giá trị business hay raw tool payload. Không lưu raw message, token/API key hoặc toàn bộ business response vào run store.

## 6. Session state và persistent preferences

- Session state được phân vùng theo cặp `(actor_id, session_id)`. Dữ liệu chỉ phục vụ tiếp nối hội thoại trong đúng scope đó.
- Prototype hiện cho phép lưu `active_trip_id` sau khi một workflow trip hợp lệ chạy; đây chỉ là context để phân giải yêu cầu tiếp theo còn thiếu ID. Trước mọi kết luận, workflow vẫn đọc trip/approval/itinerary từ mock tools.
- Session khác hoặc actor khác không được đọc/ghi context của nhau. Khi không có session state, Agent phải yêu cầu ID thay vì dùng state của scope khác.
- Persistent preference được phân vùng theo actor giả lập và chỉ dùng allowlist `response_language`, `preferred_output_format`. Chỉ lưu sau thao tác yêu cầu lưu rõ ràng; không trích xuất preference ngầm từ hội thoại.
- API training cung cấp thao tác xem, lưu/cập nhật và xóa preference. Các endpoint nhận actor ID giả lập nên không tạo security boundary; chỉ dùng dữ liệu tổng hợp, không dùng PII.
- Từ chối key ngoài allowlist, value rỗng/quá dài và dữ liệu có key nhạy cảm (passport, visa, payment, account, token, password, secret, address). Không lưu raw conversation.
- Run state, session state và preference có storage riêng về mặt logic. Không dùng preference/session summary để thay thế facts mới từ mock systems.

## 7. Evidence contract

Policy claim phải có citation tối thiểu gồm `source`, `doc_id`, `section`/`page`, `version`, `chunk_id`. Citation phải được truyền từ retrieval result tới response; không tạo citation suy diễn. Retrieval score không tự chứng minh evidence đủ mạnh. Nếu evidence không hỗ trợ claim, không nêu claim.

## 8. Permission invariants

- Agent không tự phê duyệt expense/trip.
- Agent không booking, payment, refund, external communication, production update hoặc tùy ý truy cập file/network/shell.
- Action-like request chỉ có thể tạo draft/approval simulation và phải nêu rõ trạng thái.
