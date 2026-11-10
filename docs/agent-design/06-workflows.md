# 06 — Workflow contract (pre_trip, in_trip, post_trip)

Code: `src/workflows.py` · mock dev: `src/dev_systems.py` · test: `tests/test_workflows.py` (chạy `python tests/test_workflows.py`).
Workflow là orchestration deterministic; LLM (nếu dùng) chỉ viết lại narrative từ response, không quyết định routing, approval, số liệu hay citation.

## 1. Contract chung

| Mục | Nội dung |
|---|---|
| Roles | `employee` (chỉ trip/report của mình), `travel_operations_reviewer`, `approver` |
| Input | request envelope (02 §2); ID lấy từ `context`, fallback từ message, `trip_id` fallback từ session (chỉ khi message có từ khóa liên quan) |
| Router | text user chỉ chọn workflow + ID, không chọn tool. Có `EXP`/`RPT` hoặc từ khóa chi phí → `post_trip`; từ khóa delay/hủy → `in_trip`; còn lại → `pre_trip` |
| Budget | `max_steps=12`, `max_retries=2` (chỉ lỗi `retryable`), `max_retrieval=6`, rewrite query ≤ 1 lần/branch |
| Draft | `create_*_draft(payload, source_ids, idempotency_key)`; key = `{request_id}:{workflow}:{id}:{intent}`, storage bền vững ở API runtime và scope theo actor |
| Approval request | `request_approval(trip_id, action_summary, idempotency_key)` chỉ khi user yêu cầu rõ; tạo `pending`, không approve/reject |

## 2. Tool sequence và terminal outcomes

**pre_trip** — allowlist: `get_trip_request`, `get_approval_status`, `search_travel_policy`, `create_travel_checklist_draft`, `request_approval` (explicit request only)

`get_trip_request → (kiểm travel_status, required_fields) → get_approval_status → search ×3–4 (travel, visa, insurance, approval nếu chưa approved) → create_travel_checklist_draft`

`request_approval` là tool mô phỏng tùy chọn cho yêu cầu rõ ràng của user; workflow checklist không tự gọi tool này. Caller phải bind đủ `trip_id`, `action_summary`, `idempotency_key`; dispatcher xác minh actor scope và chỉ ghi trạng thái `pending`. REST caller dùng `POST /api/approval-requests`.

| Điều kiện | status / reason_code |
|---|---|
| trip `cancelled`/`rejected` | `needs_human` / `TRIP_CANCELLED`, `TRIP_REJECTED` (không tạo draft) |
| trip `in_progress`/`completed` | `failed_validation` / `TRIP_NOT_PRE_TRIP` |
| thiếu field trong `required_fields` (vd `cost_center`) | `needs_input` / `MISSING_REQUIRED_FIELDS` |
| approval `rejected`, hoặc trip `approved` nhưng approval system không trả `approved` | `needs_human` / `APPROVAL_REJECTED`, `APPROVAL_STATUS_MISMATCH` |
| không có approval record | `needs_human` / `NO_APPROVAL_RECORD` (vẫn tạo draft) |
| thiếu/xung đột evidence travel hoặc visa | `needs_human` / `POLICY_EVIDENCE_INSUFFICIENT` (draft ghi `limitations`) |
| approval `pending` | `awaiting_approval` / `APPROVAL_PENDING` |
| approval `approved` + đủ evidence | `completed` / `CHECKLIST_READY` |

**in_trip** — allowlist: `get_itinerary`, `search_travel_policy`, `create_escalation_or_support_draft`

`get_itinerary → extract_disruptions (code) → search insurance ("chuyển cấp") → create_escalation_or_support_draft`

| Điều kiện | status / reason_code |
|---|---|
| itinerary không có delay/cancel | `completed` / `NO_DISRUPTION_OBSERVED` (không xác nhận lời user, không tạo draft) |
| có segment `cancelled` | `needs_human` / `CANCELLED_REQUIRES_HUMAN` (có draft) |
| delay + guidance có evidence | `completed` / `ESCALATION_DRAFT_READY` |
| delay nhưng policy không đủ | `needs_human` / `POLICY_INSUFFICIENT` |

Draft tách `observed_facts` (itinerary) và `policy_guidance` (kèm citation), có `actions_not_taken`.

**post_trip** — allowlist: `get_expense_report`, `calculate_expense_summary`, `search_travel_policy`, `create_expense_review_draft`

`get_expense_report → structural check (code) → calculate_expense_summary → đối chiếu tổng → search expense (rule chứng từ; rule ăn uống nếu có meals) → create_expense_review_draft`

| Điều kiện | status / reason_code |
|---|---|
| report rỗng / line item thiếu field cấu trúc | `needs_input` |
| tổng tool ≠ tổng line items | `needs_human` / `TOTAL_MISMATCH` |
| có flag (thiếu chứng từ, vượt ngưỡng ăn uống) hoặc evidence không hỗ trợ ngưỡng | `needs_human` / `FLAGS_FOR_REVIEW`, `POLICY_EVIDENCE_INSUFFICIENT` |
| không flag | `completed` / `NO_ISSUE_FOUND` |

Claim–evidence: chunk chỉ được dùng nếu chứa thuật ngữ và con số ngưỡng mà tool áp dụng (vd "chứng từ" + "75", "ăn uống" + "120").

## 3. Lỗi chung
`NOT_FOUND → needs_input` · `INVALID_ARGUMENT → failed_validation` · `UNAUTHORIZED → rejected` · `TIMEOUT/TOOL_UNAVAILABLE` hết retry → `needs_human` (hoặc `partial` nếu đã có draft) · hết budget → `partial` / `BUDGET_EXCEEDED` · draft lỗi → `partial` / `DRAFT_FAILED` · `delivery_status=failed_delivery` → `failed_delivery`.

## 4. Ví dụ + trace (TC-PRE-001: TRIP-2026-001, EMP-001)

Response: `status=awaiting_approval`, `reason_code=APPROVAL_PENDING`, `artifacts=[DRAFT-2026-001 travel_checklist, draft_created, not_sent]`, evidence `CHUNK-002, 001, 005, 006, 008, 009`.

| step | phase | action | safe args | observation | budget |
|---|---|---|---|---|---|
| 1 | fetch_trip | get_trip_request | trip_id=TRIP-2026-001 | ok | 1/12 |
| 2 | fetch_approval | get_approval_status | trip_id=TRIP-2026-001 | ok (pending) | 2/12 |
| 3–6 | retrieve | search_travel_policy | category=travel / visa / insurance / approval | ok | 6/12 |
| 7 | draft | create_travel_checklist_draft | payload=<dict>, key=REQ-2026-001:pre_trip:… | ok | 7/12 |
| 7 | terminal | — | reason_code=APPROVAL_PENDING | end | 7/12 |

## 5. Fixture → nhánh kỳ vọng

| Fixture | Workflow | Kết quả |
|---|---|---|
| TRIP-2026-002 (approved) | pre_trip | `completed` |
| TRIP-2026-001 (pending) | pre_trip | `awaiting_approval` |
| TRIP-2026-004 / 007 (thiếu `cost_center`) | pre_trip | `needs_input` |
| TRIP-2026-005 / 006 (rejected / cancelled) | pre_trip | `needs_human` |
| TRIP-2026-002 (delayed) / 008 (delayed) | in_trip | `completed` |
| TRIP-2026-003 (cancelled) | in_trip | `needs_human` |
| EXP-2026-001 | post_trip | `completed` (tổng 70.5) |
| EXP-2026-002 (lodging thiếu chứng từ) | post_trip | `needs_human` |
| EXP-2026-003 (meals 155 > 120, thiếu chứng từ) | post_trip | `needs_human` (tổng 1135.0) |

## 6. Điểm cần chốt với owner khác
- Quang: format report ID (`EXP-` trong fixture vs `RPT-` trong 04); tên 3 tool draft; dispatcher thật nhận `(tool, args, ctx)`; fixture chưa có chunk injection/version-conflict (test đang tự chèn).
- Vinh: schema `payload` của từng draft; `artifact_type` đang dùng `travel_checklist`, `disruption_escalation_note`, `expense_review`.
- Minh: `session` chỉ giữ `active_trip_id`; facts luôn đọc lại từ mock.
