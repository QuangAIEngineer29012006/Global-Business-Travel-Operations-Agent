# 02 — Agent Contract

## 1. Actor roles

| Role | Quyền prototype |
|---|---|
| `employee` | Đọc dữ liệu mock theo actor scope; chạy workflow hỗ trợ; yêu cầu draft |
| `travel_operations_reviewer` | Đọc/rà soát dữ liệu và draft trong phạm vi mock; yêu cầu escalation draft |
| `approver` | Tạo hoặc cập nhật approval simulation theo contract; không tạo quyết định production |

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

## 6. Memory rules

- Session state có thể giữ ngữ cảnh ngắn hạn như `active_trip_id` trong đúng session.
- Persistent preference chỉ lưu tối thiểu (ví dụ `response_language`, `preferred_output_format`) khi user yêu cầu.
- Tách `session_id` và `run_id`.
- Không lưu passport, visa, payment card, bank account, token, địa chỉ thật hoặc raw conversation đầy đủ.
- Có chức năng xem/xóa preference trong môi trường training.

## 7. Evidence contract

Policy claim phải có citation tối thiểu gồm `source`, `doc_id`, `section`/`page`, `version`, `chunk_id`. Citation phải được truyền từ retrieval result tới response; không tạo citation suy diễn. Retrieval score không tự chứng minh evidence đủ mạnh. Nếu evidence không hỗ trợ claim, không nêu claim.

## 8. Permission invariants

- Agent không tự phê duyệt expense/trip.
- Agent không booking, payment, refund, external communication, production update hoặc tùy ý truy cập file/network/shell.
- Action-like request chỉ có thể tạo draft/approval simulation và phải nêu rõ trạng thái.
