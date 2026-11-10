# 03 — Tool Contract

## 1. Registry record

Mỗi tool được khai báo tĩnh với:

```json
{
  "name": "get_trip_request",
  "description": "Read one trip request from the mock Trip system.",
  "workflow_allowlist": ["pre_trip", "in_trip"],
  "permission_class": "read_only",
  "input_schema": {},
  "result_schema": {},
  "max_calls_per_run": 2,
  "idempotent": true
}
```

Registry là nguồn duy nhất các tool có thể gọi. Không sinh tool name từ user input. `additionalProperties` nên là `false`.

## 2. Tool classes

- `read_only`: chỉ đọc mock source.
- `deterministic`: validation hoặc calculation thuần xác định.
- `draft_only`: tạo artifact trong sandbox; cần idempotency key; runtime API lưu bền vững trong SQLite local.
- `approval_simulation`: chỉ tạo record approval giả lập `pending`; không có thao tác approve/reject và không thực hiện downstream action.

Mỗi workflow có allowlist riêng. Tool nằm trong registry nhưng không nằm trong workflow allowlist vẫn phải bị từ chối.

## 3. Dispatcher validation order

1. Tool tồn tại trong registry.
2. Tool được allowlist cho workflow hiện tại.
3. Actor role có quyền gọi tool.
4. Arguments hợp lệ theo JSON Schema, không có trường thừa.
5. Domain validation: ID format, record existence, actor scope, query bounds.
6. Run budget, per-tool budget, retry budget và retrieval top-k.
7. Gọi implementation; không cho model bypass dispatcher.
8. Validate result schema rồi trả structured observation.
9. Ghi safe trace với arguments đã lọc.

Bất cứ bước kiểm tra nào thất bại thì implementation không được chạy.

## 4. Candidate tool catalog

Tên cuối cùng cần được các owner thống nhất trước implementation:

| Tool | Class | Ghi chú |
|---|---|---|
| `get_trip_request(trip_id)` | read_only | Trip facts |
| `get_traveler_profile(traveler_id)` | read_only | Chỉ preference không nhạy cảm |
| `get_itinerary(trip_id)` | read_only | Itinerary/disruption facts |
| `get_approval_status(trip_id)` | read_only | Trạng thái hiện hành từ mock approval store |
| `search_travel_policy(query, category, max_results)` | read_only | Trả chunks cùng metadata nguồn |
| `get_expense_report(report_id)` | read_only | Expense facts/line items |
| `calculate_expense_summary(report_id)` | deterministic | Tính tổng, kiểm tra ngưỡng có cấu hình |
| `request_approval(trip_id, action_summary, idempotency_key)` | approval_simulation | Chỉ tạo record `pending` khi user yêu cầu rõ; employee/reviewer, scope trip và schema được kiểm tra |
| `create_*_draft(payload, source_ids, idempotency_key)` | draft_only | Tên cụ thể và schema do draft owner chốt |

Không đưa arbitrary URL, path, SQL, shell command hoặc code vào arguments.

## 5. Result/error envelope

Success:

```json
{
  "ok": true,
  "data": {},
  "meta": { "source_system": "mock_trip_system", "read_only": true }
}
```

Error:

```json
{
  "ok": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Requested mock record was not found.",
    "retryable": false
  }
}
```

`message` không chứa secrets hay raw stack trace. Dùng error code ổn định, gồm ít nhất `INVALID_ARGUMENT`, `UNAUTHORIZED`, `NOT_FOUND`, `CONFLICT`, `BUDGET_EXCEEDED`, `TIMEOUT`, `TOOL_UNAVAILABLE`, `INTERNAL_ERROR`.

## 6. Budget and retry

- Agent contract phải khai báo `max_steps`; dispatcher kiểm tra trước mỗi lần gọi.
- Retry giới hạn cho lỗi có `retryable=true`; không retry validation, unauthorized hay not found.
- Retrieval có `max_results` và giới hạn số lần gọi.
- Draft/approval writes dùng idempotency key ổn định theo request/workflow/intent; retry trả lại artifact record hiện có thay vì tạo duplicate.
- Idempotency của draft/approval được scope theo actor giả lập; khóa trùng giữa hai actor không làm lộ hoặc trả lại artifact/approval của nhau.
- API runtime lưu draft và approval simulation trong SQLite cục bộ qua StateStore; fixture-only `MockSystems` vẫn hỗ trợ storage trong memory để test cô lập.
- `request_approval` chỉ được gọi khi caller đánh dấu explicit user intent và bind toàn bộ arguments; native function caller không được tự viết `trip_id`, action summary hoặc idempotency key.
- API `POST /api/approval-requests` là explicit caller path cho tool; endpoint không suy ra approval intent từ nội dung chat.
- Giới hạn đạt ngưỡng thì dừng với `partial`/`needs_human` và reason code.

## 7. Trace requirements

Trace entry tối thiểu: `trace_id`, `run_id`, step, workflow/phase, tool name, sanitized arguments, allowlist/validation result, observation summary, retry count, budget remaining, transition và outcome. Không lưu credentials, PII thật hoặc toàn bộ raw conversation.
