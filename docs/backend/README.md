# Backend travel agent

Nhánh `backend` được tạo từ `huy`. Backend này gồm FastAPI, CLI, model adapter, tool registry/dispatcher,
SQLite cho state/draft và ba workflow có kiểm soát. Đây là prototype đang phát triển;
báo cáo evaluation đầy đủ và adapter tới dữ liệu của workflow gốc chưa hoàn tất.

## Quan hệ với code trên `huy`

| Thành phần | Cách chạy / nguồn dữ liệu |
|---|---|
| Workflow gốc `src/workflows.py`, `src/dev_systems.py` | Giữ nguyên; dùng `data/mock-systems/` và `demo.py` |
| Backend mới `backend/`, `travel_agent/` | Dùng `data/training.json`, `data/policies.json`; sandbox ở `workspace/` |
| Test gốc | Giữ nguyên `tests/test_workflows.py` |
| Test backend | `tests/test_backend_workflows.py`, `test_safety.py`, `test_state_and_retries.py`, `test_api_and_gemini.py` |

Hai bộ fixture có ID trùng nhưng nội dung khác. Ví dụ, `TRIP-2026-001` ở fixture gốc đang pending,
còn trong fixture backend là approved. Không dùng kết quả từ backend để suy ra trạng thái của fixture gốc.
Backend dùng role `reviewer`, workflow `expense`, traveler ID `TRV-*`; workflow gốc dùng
`travel_operations_reviewer`, `post_trip`, `EMP-*`. Việc chuẩn hóa contract này còn cần làm khi tích hợp.

## Cài đặt

Python 3.12 đã được dùng để kiểm thử. Tại thư mục gốc repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Trên Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Mặc định `LLM_PROVIDER=fake`: simulator tạo function calls bằng quy tắc, không phải LLM.
Chế độ này chạy offline, không cần API key và không đại diện cho chất lượng Gemini.

## Chạy backend và demo

```bash
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

Mở tài liệu tương tác tại `http://127.0.0.1:8000/docs`.

CLI cho cả ba workflow và một số nhánh dừng an toàn:

```bash
python -m travel_agent demo
python -m travel_agent run "Chuẩn bị công tác TRIP-2026-001"
python -m travel_agent run "TRIP-2026-002 bị delay"
python -m travel_agent run "Rà soát chi phí EXP-2026-003"
```

Demo ghi bằng chứng chạy cục bộ vào `artifacts/demo.json`. Không commit dữ liệu runtime này.
Tổng và ngưỡng chi phí sử dụng integer minor units, tỷ lệ dùng basis points.

## Gọi API

Tạo session với một identity giả lập có sẵn, rồi truyền Bearer token:

```python
import requests

base = "http://127.0.0.1:8000"
session = requests.post(base + "/api/sessions", json={"user_id": "demo-an"}).json()
headers = {"Authorization": "Bearer " + session["token"]}
result = requests.post(base + "/api/runs", headers=headers, json={
    "message": "Chuẩn bị công tác TRIP-2026-001",
    "request_id": "example-request-001",
}).json()
print(result["state"]["outcome"])
print(result["response"]["summary"])
```

Gửi lại cùng request ID, session và nội dung trả run cũ; nội dung khác với cùng key bị từ chối.
Dùng request ID mới cho lần đọc trạng thái mới từ mock source.

| Endpoint | Mục đích |
|---|---|
| `GET /api/health` | Trạng thái, provider và model |
| `GET /api/training-users` | Identity/role mô phỏng có sẵn |
| `POST /api/sessions` | Tạo session; đây không phải đăng nhập production |
| `DELETE /api/sessions/current` | Thu hồi session |
| `POST /api/runs` | Chạy workflow |
| `GET /api/runs/{run_id}` | Xem run trong đúng session |
| `GET /api/drafts/{draft_id}` | Xem draft trong đúng session |
| `GET/PUT/DELETE /api/preferences` | Xem/lưu/xóa preference; lưu cần `remember: true` |
| `POST /api/mock-approvals/{trip_id}` | Approver mô phỏng quyết định record đang pending |
| `GET /api/tools` | Registry và JSON schemas |

## Function calling và giới hạn

Model chỉ đề xuất tool name/arguments. Dispatcher kiểm tra registry, workflow/phase allowlist,
role, JSON Schema, scope của ID, budget và output schema. Workflow sở hữu dependency và điểm dừng.
State tách `user_id`, `session_id`, `run_id`; session chỉ giữ ID đang hoạt động, không dùng làm nguồn facts.
SQLite chỉ lưu token hash; mặc định không lưu full raw conversation.

Draft tools có idempotency, luôn `not_sent`. Approval pending/rejected dừng trước draft write.
Không có tool booking, payment, refund, gửi email, publish, arbitrary shell, URL hoặc SQL.
Policy claims được trích nguyên câu từ corpus training đã kiểm tra; cơ chế này chưa phải bộ kiểm tra
entailment tổng quát cho tài liệu bất kỳ. Không dùng corpus hư cấu này để tư vấn du lịch thực tế.

Nếu bật Gemini, tự điền `GEMINI_MODEL` hỗ trợ function calling và `GEMINI_API_KEY` vào `.env`,
đổi `LLM_PROVIDER=gemini`. Adapter dùng native `functionCall` / `functionResponse`, giữ model content
và thought signatures trong history tạm thời. Tham chiếu:
[Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling).
Chỉ transport giả lập được kiểm thử ở bản bàn giao này; chưa gọi Gemini thật.

## Kiểm thử

```bash
python -m pytest -q
```

Lệnh chạy cả test gốc và test backend. Bao gồm ba workflow, quyền truy cập, input/output validation,
policy injection/conflict/no-evidence, budgets/retry, idempotency khi mất phản hồi sau commit,
memory isolation, API và payload Gemini giả lập. Test đều dùng sandbox tạm.

## Phần còn lại

- Nối backend với logical schema và fixture của nhánh `huy`, thống nhất roles/workflow names/IDs.
- Hoàn thiện test matrix, metrics, traces và báo cáo baseline/before-after/regression theo PDF.
- Kiểm thử Gemini thật khi có model/key phù hợp và ghi rõ kết quả tách biệt với simulator.
