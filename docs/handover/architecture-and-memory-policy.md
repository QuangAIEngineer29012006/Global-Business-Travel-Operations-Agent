# Tài liệu Bàn giao: Kiến trúc Hệ thống, Sơ đồ Workflow, Tool Registry & Memory Policy

Tài liệu này tổng hợp toàn bộ thiết kế kiến trúc, luồng điều phối 3 workflows bắt buộc, danh mục Tool Registry/Schemas/Allowlist và chính sách Quản lý State/Memory của **Global Business Travel Operations Agent**.

---

## 1. Sơ đồ Kiến trúc Tổng thể (System Architecture)

Hệ thống được thiết kế theo nguyên tắc **Defense-in-Depth (Phòng thủ nhiều lớp)**:
- **Mock-only & Draft-only Side Effects:** Mọi thao tác đọc/ghi chỉ diễn ra trên hệ thống giả lập (`data/mock-systems/` và SQLite `agent_state.sqlite`). Không đặt vé, không thanh toán, không hoàn tiền, không gửi email/tin nhắn thật.
- **Deterministic Orchestration & Guarded Tool Execution:** LLM không được tự ý gọi tool ngoài allowlist hoặc thay đổi kết quả nghiệp vụ/số tiền/trạng thái phê duyệt.
- **Policy is Evidence, Not Authority:** Mọi hướng dẫn quy định đều phải đính kèm citation (`chunk_id`, `doc_id`, `source`, `section`, `version`) và vượt qua bước lọc Prompt Injection + kiểm tra xung đột phiên bản.

```mermaid
flowchart TB
    subgraph ClientLayer["1. Giao diện & Entrypoints"]
        UI["React/Vite Frontend (frontend/)"]
        CLI["CLI Demo & Eval Scripts (demo.py, scripts/)"]
        NB["Jupyter Notebook (notebooks/)"]
    end

    subgraph APILayer["2. Backend & LLM Presentation Layer (backend/)"]
        FASTAPI["FastAPI Server (POST /api/runs, POST /api/approval-requests)"]
        LLMSVC["LLMService (Presentation Plan / Text Rewrite)"]
        FC["Native Function Calling Adapter (tool_turn)"]
        STATE["SQLite StateStore (agent_state.sqlite)"]
    end

    subgraph CoreAgent["3. Bounded Workflow Orchestrator (src/workflows.py)"]
        ROUTER["Deterministic Router & Input Sanitizer"]
        PRE["Workflow 1: pre_trip"]
        INT["Workflow 2: in_trip"]
        POST["Workflow 3: post_trip"]
        EXEC["Guarded Executor (Step/Retrieval Budget & Retry)"]
    end

    subgraph DispatcherLayer["4. Tool Registry & Security Guard (src/dev_systems.py)"]
        REG["Static Tool Registry & JSON Schema Validator"]
        ALLOW["Workflow Allowlist & Actor Role/Scope Guard"]
    end

    subgraph DataLayer["5. Mock Systems & Hybrid RAG (data/mock-systems/, src/policy_search.py)"]
        MOCK_DB["Mock Domain Stores (Trips, Profiles, Itineraries, Approvals, Expenses)"]
        HYBRID_RAG["Hybrid Policy Search (SQLite FTS5 + Multilingual MiniLM)"]
        DRAFT_WS["Draft Workspace & Approval Simulation Store"]
    end

    UI --> FASTAPI
    CLI --> LLMSVC
    CLI --> ROUTER
    NB --> LLMSVC

    FASTAPI --> LLMSVC
    FASTAPI --> FC
    LLMSVC <--> STATE
    LLMSVC --> ROUTER
    FC --> EXEC

    ROUTER --> PRE & INT & POST
    PRE & INT & POST --> EXEC
    EXEC --> ALLOW
    ALLOW --> REG
    REG --> MOCK_DB
    REG --> HYBRID_RAG
    REG --> DRAFT_WS
    DRAFT_WS <--> STATE
```

---

## 2. Sơ đồ Luồng 3 Workflows Bắt buộc (Workflow Diagrams)

### 2.1. Workflow 1 — Trước chuyến đi (`pre_trip`)

```mermaid
flowchart TD
    A["Nhận Request (trip_id, actor)"] --> B["get_trip_request(trip_id)"]
    B -->|NOT_FOUND| B1["needs_input (TRIP_NOT_FOUND)"]
    B -->|UNAUTHORIZED| B2["rejected (UNAUTHORIZED)"]
    B -->|OK| C{"Kiểm tra travel_status"}
    C -->|rejected / cancelled| C1["needs_human (TRIP_REJECTED / TRIP_CANCELLED)<br/>Không tạo draft"]
    C -->|in_progress / completed| C2["failed_validation (TRIP_NOT_PRE_TRIP)"]
    C -->|draft / submitted / pending / approved| D{"Đủ required_fields?<br/>(vd: cost_center)"}
    D -->|Thiếu field| D1["needs_input (MISSING_REQUIRED_FIELDS)<br/>Dừng sớm, không gọi tiếp"]
    D -->|Đủ field| E["get_approval_status(trip_id)"]
    E --> F{"Đối chiếu Approval"}
    F -->|status = rejected| F1["needs_human (APPROVAL_REJECTED)"]
    F -->|trip=approved nhưng approval!=approved| F2["needs_human (APPROVAL_STATUS_MISMATCH)"]
    F -->|Hợp lệ / pending / none| G["search_travel_policy (travel, visa, insurance, approval)<br/>Kèm lọc Injection & rewrite tối đa 1 lần"]
    G --> H["create_travel_checklist_draft (idempotent, delivery_status=not_sent)"]
    H --> I{"Đánh giá kết quả cuối"}
    I -->|approval = none| I1["needs_human (NO_APPROVAL_RECORD)"]
    I -->|Thiếu/xung đột policy bắt buộc| I2["needs_human (POLICY_EVIDENCE_INSUFFICIENT)"]
    I -->|approval = pending| I3["awaiting_approval (APPROVAL_PENDING)"]
    I -->|approval = approved & đủ evidence| I4["completed (CHECKLIST_READY)"]
```

### 2.2. Workflow 2 — Trong chuyến đi (`in_trip`)

```mermaid
flowchart TD
    A["Nhận Request (trip_id, actor)"] --> B["get_itinerary(trip_id)"]
    B -->|Lỗi đọc / Quyền| B1["needs_input / rejected / needs_human"]
    B -->|OK| C{"Phát hiện Disruption<br/>từ Itinerary?"}
    C -->|disruption_status = none| C1["completed (NO_DISRUPTION_OBSERVED)<br/>Không xác nhận lời user, không tạo draft"]
    C -->|delayed / cancelled| D["search_travel_policy(category='insurance', query='chuyển cấp...')"]
    D --> E["Kiểm tra Claim-Evidence ('chuyển cấp') & Version Conflict"]
    E --> F["create_escalation_or_support_draft<br/>(Tách observed_facts & policy_guidance, ghi rõ actions_not_taken)"]
    F --> G{"Loại sự cố & Evidence"}
    G -->|Có chặng bay cancelled| G1["needs_human (CANCELLED_REQUIRES_HUMAN)<br/>Không tự đặt lại vé/khách sạn"]
    G -->|Thiếu evidence bảo hiểm| G2["needs_human (POLICY_INSUFFICIENT)"]
    G -->|delayed & đủ evidence| G3["completed (ESCALATION_DRAFT_READY)"]
```

### 2.3. Workflow 3 — Sau chuyến đi (`post_trip`)

```mermaid
flowchart TD
    A["Nhận Request (report_id, actor)"] --> B["get_expense_report(report_id)"]
    B -->|Lỗi đọc / Quyền| B1["needs_input / rejected"]
    B -->|OK| C{"Kiểm tra cấu trúc<br/>line_items"}
    C -->|Rỗng hoặc thiếu field/amount lỗi| C1["needs_input (EMPTY_REPORT / MISSING_EXPENSE_FIELDS)<br/>Dừng trước khi tính tổng"]
    C -->|Hợp lệ| D["calculate_expense_summary(report_id)<br/>(Tính tổng Decimal xác định & kiểm tra ngưỡng 75 / 120 USD)"]
    D --> E["Đối chiếu tổng của Tool với tổng line_items"]
    E --> F["search_travel_policy(category='expense')<br/>Kiểm tra chunk chứa đúng con số ngưỡng (75, 120)"]
    F --> G["create_expense_review_draft<br/>(Kèm disclaimer không tự duyệt/hoàn tiền)"]
    G --> H{"Đánh giá Flags & Tổng"}
    H -->|Tổng không khớp| H1["needs_human (TOTAL_MISMATCH)"]
    H -->|Có flag hoặc thiếu evidence ngưỡng| H2["needs_human (FLAGS_FOR_REVIEW / POLICY_EVIDENCE_INSUFFICIENT)"]
    H -->|Không có flag & đủ evidence| H3["completed (NO_ISSUE_FOUND)"]
```

---

## 3. Danh mục Tool Registry, Schemas & Workflow Allowlist

Mọi lời gọi công cụ đều đi qua `Executor.call()` ([`src/workflows.py`](file:///c:/Users/damlo/OneDrive/Documents/GitHub/Global-Business-Travel-Operations-Agent/src/workflows.py)) và `MockSystems.__call__()` ([`src/dev_systems.py`](file:///c:/Users/damlo/OneDrive/Documents/GitHub/Global-Business-Travel-Operations-Agent/src/dev_systems.py)) theo thứ tự kiểm tra nghiêm ngặt:
1. Tên tool tồn tại trong `registry` tĩnh.
2. Tool nằm trong `workflow_allowlist` của workflow hiện hành.
3. Vai trò (`actor.role`) được phép gọi và `actor.actor_id` có quyền trên bản ghi (`_scope_ok`).
4. Tham số khớp tuyệt đối với JSON Schema (`additionalProperties: false`).
5. Kiểm tra ngân sách (`max_steps=12`, `max_retrieval=6`, `max_retries=2`).

| Tên Tool | Phân loại (`permission_class`) | Workflow Allowlist | Vai trò được phép (`roles`) | Input Schema (`additionalProperties: false`) | Idempotent |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `get_trip_request` | `read_only` | `pre_trip`, `in_trip` | `employee`, `travel_operations_reviewer`, `approver` | `{"trip_id": "^TRIP-\\d{4}-\\d{3}$"}` | Có |
| `get_traveler_profile` | `read_only` | `pre_trip` | `employee`, `travel_operations_reviewer`, `approver` | `{"traveler_id": "^EMP-\\d{3}$"}` | Có |
| `get_itinerary` | `read_only` | `in_trip` | `employee`, `travel_operations_reviewer`, `approver` | `{"trip_id": "^TRIP-\\d{4}-\\d{3}$"}` | Có |
| `get_approval_status` | `read_only` | `pre_trip` | `employee`, `travel_operations_reviewer`, `approver` | `{"trip_id": "^TRIP-\\d{4}-\\d{3}$"}` | Có |
| `search_travel_policy` | `read_only` | `pre_trip`, `in_trip`, `post_trip` | `employee`, `travel_operations_reviewer`, `approver` | `{"query": "str(2..200)", "category": "travel\|expense\|visa\|insurance\|approval", "max_results": "int(1..5)"}` | Có |
| `get_expense_report` | `read_only` | `post_trip` | `employee`, `travel_operations_reviewer`, `approver` | `{"report_id": "^(EXP\|RPT)-\\d{4}-\\d{3}$"}` | Có |
| `calculate_expense_summary` | `deterministic` | `post_trip` | `employee`, `travel_operations_reviewer`, `approver` | `{"report_id": "^(EXP\|RPT)-\\d{4}-\\d{3}$"}` | Có |
| `create_travel_checklist_draft` | `draft_only` | `pre_trip` | `employee`, `travel_operations_reviewer` | `{"payload": "object", "source_ids": "array<str>", "idempotency_key": "str(4..120)"}` | Có (theo `(actor_id, key)`) |
| `create_escalation_or_support_draft` | `draft_only` | `in_trip` | `employee`, `travel_operations_reviewer` | `{"payload": "object", "source_ids": "array<str>", "idempotency_key": "str(4..120)"}` | Có (theo `(actor_id, key)`) |
| `create_expense_review_draft` | `draft_only` | `post_trip` | `employee`, `travel_operations_reviewer` | `{"payload": "object", "source_ids": "array<str>", "idempotency_key": "str(4..120)"}` | Có (theo `(actor_id, key)`) |
| `request_approval` | `approval_simulation` | `pre_trip` (chỉ khi `explicit_approval_request=True`) | `employee`, `travel_operations_reviewer` | `{"trip_id": "^TRIP-\\d{4}-\\d{3}$", "action_summary": "str(8..240)", "idempotency_key": "str(4..120)"}` | Có (chỉ tạo `status=pending`) |

---

## 4. Chính sách Quản lý State & Memory (Memory Policy)

Được triển khai tại [`backend/state_store.py`](file:///c:/Users/damlo/OneDrive/Documents/GitHub/Global-Business-Travel-Operations-Agent/backend/state_store.py) và [`src/workflows.py`](file:///c:/Users/damlo/OneDrive/Documents/GitHub/Global-Business-Travel-Operations-Agent/src/workflows.py):

1. **Tách biệt 4 lớp trạng thái (State Separation):**
   - **Run State (`RunState` & bảng `runs`):** Tồn tại riêng cho từng `run_id`. Ghi nhận `workflow`, `phase`, `step_count`, `retrieval_calls`, `outcome`, `reason_code`, danh sách `artifact_ids`, `evidence_chunk_ids` và `trace` đã làm sạch.
   - **Session Context (bảng `sessions`):** Khóa chặt theo cặp `(actor_id, session_id)`. Chỉ được phép giữ khóa `active_trip_id` hợp lệ (`^TRIP-\d{4}-\d{3}$`) để hỗ trợ hội thoại nối tiếp trong cùng phiên của cùng một người dùng.
   - **User Preferences (bảng `preferences`):** Chỉ lưu các tùy chọn không nhạy cảm nằm trong allowlist (`seat_preference`, `meal_preference`, `Departure_time_preference`, `route_preference`, `checkin_preference`, `preferred_language`, `notification_format`) khi có hành động opt-in rõ ràng.
   - **Sandbox Workspace (bảng `drafts` và `approval_simulations`):** Lưu bản nháp với `delivery_status="not_sent"` và các bản ghi yêu cầu phê duyệt giả lập (`status="pending"`), khóa idempotency theo `(actor_id, idempotency_key)`.

2. **Không dùng Memory cũ làm nguồn sự thật (Memory is Never Source of Truth):**
   - Ngay cả khi `active_trip_id` được lấy từ `session`, Agent **bắt buộc** gọi lại `get_trip_request`, `get_approval_status`, `get_itinerary` hoặc `get_expense_report` từ Mock System trong mỗi lượt chạy.
   - Nếu trạng thái phê duyệt trong Mock System đổi từ `pending` sang `rejected` (được kiểm chứng bởi `EVAL-018`), lượt chạy tiếp theo lập tức phản ánh `APPROVAL_REJECTED`.

3. **Cô lập dữ liệu & Bảo vệ quyền riêng tư (Isolation & Redaction):**
   - Session của `EMP-001` không bao giờ nhìn thấy được bởi `EMP-002`.
   - Bộ lọc `_safe()` trong `RunState` và `_sanitize_trace()` trong `StateStore` tự động thay thế mọi khóa nhạy cảm (`passport`, `visa_no`, `card`, `account`, `token`, `password`, `secret`, `address`, `payload`, `action_summary`) bằng `"[redacted]"` trước khi lưu xuống SQLite hoặc trả về API.
