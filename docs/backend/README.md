# Backend: phạm vi LLM

Backend này bổ sung lớp LLM lên code có sẵn của `huy`, theo request/response ở
[contract 02](../agent-design/02-agent-contract.md) và cách phân công trong
[workflow contract 06](../agent-design/06-workflows.md). Không triển khai RAG, database,
session/auth, approval simulation hay workflow mới trong phần backend.

## Luồng tích hợp

```text
request theo contract 02
  -> src/workflows.run_agent(request, dispatcher)
  -> workflow đọc fixture / tính toán / tạo draft bằng tool hiện có
  -> LLM chọn và sắp xếp các điểm cần trình bày (tối đa 1 lượt)
  -> response gốc + trường llm
```

`src/workflows.py`, `src/dev_systems.py`, `data/mock-systems/` và test workflow gốc được giữ nguyên.
Vì vậy `TRIP-2026-001` vẫn pending; roles là `employee`, `travel_operations_reviewer`, `approver`;
workflow là `pre_trip`, `in_trip`, `post_trip`; traveler ID dùng `EMP-*`.

| File | Trách nhiệm |
|---|---|
| `backend/config.py` | Provider, key, model, timeout, retry |
| `backend/llm_client.py` | Gemini text/structured output/native function calling và simulator offline |
| `backend/prompts.py` | Prompt trình bày, viết lại text và function calling |
| `backend/models.py` | Schema request theo contract; validation kết quả trình bày |
| `backend/service.py` | Gọi workflow chung, giới hạn model calls, fallback |
| `backend/function_calling.py` | Adapter một lượt model proposal → dispatcher → function response |
| `backend/main.py` | API `GET /api/health`, `POST /api/runs` |

## Cài đặt và chạy

Đã kiểm tra trên Python 3.12. Tại thư mục gốc:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
python scripts/demo_llm.py
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

Windows PowerShell dùng `python -m venv .venv`, `.\.venv\Scripts\Activate.ps1` và
`Copy-Item .env.example .env` thay cho các lệnh tương ứng. Mở `http://127.0.0.1:8000/docs` để thử API.
`python demo.py` vẫn chạy workflow gốc như trên `huy`.

Mặc định `LLM_PROVIDER=fake`: chỉ mô phỏng offline, không có HTTP/model thật.
Để dùng Gemini, đặt `LLM_PROVIDER=gemini`, điền `GEMINI_MODEL` hỗ trợ structured output và
`GEMINI_API_KEY` trong `.env`. Không đưa `.env` lên Git. Không tự mặc định một model chưa xác minh khả dụng.

## API đúng contract

Không cần tạo session/token riêng cho bản training. Actor và session ID giả lập được truyền theo contract 02:

```python
import requests

result = requests.post("http://127.0.0.1:8000/api/runs", json={
    "request_id": "REQ-2026-001",
    "actor": {"role": "employee", "actor_id": "EMP-001"},
    "session_id": "SES-001",
    "message": "Tôi chuẩn bị công tác Singapore, đã đủ điều kiện chưa?",
    "context": {"trip_id": "TRIP-2026-001"}
}).json()
print(result["status"])          # awaiting_approval
print(result["llm"]["message"]) # phần trình bày cho user
```

Response giữ nguyên các trường `request_id`, `run_id`, `workflow`, `status`, `message`, `data`, `evidence`,
`artifacts`, `next_action`, `reason_code`, `steps`, `trace` của workflow. Trường bổ sung `llm` có
`status` (`ok`, `fallback`, `skipped`), `message`, `calls`, token usage, retry count và error code.

Giá trị `llm.calls=1` nghĩa một lượt gọi logic; transport có tối đa `LLM_MAX_RETRIES + 1` lần thử.
Chế độ fake không gọi HTTP. Input sai/quyền không hợp lệ, greeting hoặc response không cần highlight có thể dùng 0 lượt.

## Vai trò thực tế của LLM

Workflow vẫn quyết định routing, trạng thái, phép tính, citation và draft. LLM nhận một danh sách câu
đã được dựng từ kết quả workflow, trả JSON `highlight_ids` để lựa chọn/thứ tự trình bày. Backend chỉ
render các câu đã xác minh; model không được thêm số tiền, đổi pending thành approved hay bịa citation.
Đây là trình bày có ràng buộc, không phải một bộ viết narrative tự do hay kiểm tra entailment tổng quát.
Nếu model lỗi hoặc trả ID ngoài danh sách, response giữ nguyên kết quả nghiệp vụ và đánh dấu `llm.status=fallback`.

Yêu cầu `Viết lại: ...` hoặc `Viết lại chuyên nghiệp: ...` gọi text generation một lần và không gọi tool/retrieval.
Nó chỉ biên tập text người dùng cung cấp, không chứng thực trạng thái nghiệp vụ. Simulator ghi rõ chưa viết lại bằng LLM.
Backend không lưu raw conversation, không tạo persistent memory riêng. Memory owner có thể truyền session dict vào
`LLMService.run(request, session=...)`; API này không tự lưu context giữa các request.

## Native function calling để nhóm tích hợp

`GeminiClient.propose_tool()` gửi `functionDeclarations` và đọc native `functionCall`.
`tool_turn()` chạy tối đa một proposal và một lời gọi dispatcher. Nó giới hạn tên tool, buộc arguments theo ID
caller đã bind; dispatcher hiện có tiếp tục kiểm tra workflow/role/schema/domain. Function response và model content,
kể cả thought signature, được giữ nguyên trong history tạm, không ghi log hoặc file mặc định.

```bash
python scripts/demo_llm.py --function-call
```

Lệnh cần Gemini đã cấu hình; chỉ đọc `TRIP-2026-001` qua `get_trip_request`, không ghi dữ liệu.
Adapter không có vòng lặp tự trị hoặc write tools trong demo. Caller điều phối chịu trách nhiệm budget cho nhiều lượt.
Tham chiếu chính thức: [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling).

Theo contract 06 hiện tại, API dùng workflow deterministic và **không gọi native function calling cho từng bước**.
Việc nối model đề xuất mọi tool call theo mục 7 PDF là phần tích hợp toàn nhóm; backend không tuyên bố đã hoàn thành
toàn bộ yêu cầu Agentic RAG hay function-calling orchestration của project. `search_travel_policy` hiện do dispatcher
có sẵn của `huy` cung cấp; người phụ trách RAG có thể thay implementation qua dependency injection.

## Kiểm thử và giới hạn

```bash
python -m pytest -q
```

Test gồm workflow gốc, request mẫu contract, đúng fixture/role, giới hạn 0–1 lượt model, lỗi JSON/schema,
fallback không đổi approval/số liệu/citation, text rewrite không retrieval, timeout/retry, function calling
native qua HTTP mock, arguments bị cấm và thought signature round-trip.

Ngày 09/11/2026 đã chạy Gemini thật với `gemini-3.5-flash-lite`: **8/8 smoke cases pass**
(ba workflow, pending approval, text rewrite giữ yêu cầu hỗ trợ, native function call, function response round-trip,
và endpoint API với Gemini). Bằng chứng, latency và token usage ở
[`artifacts/gemini_live_smoke.json`](../../artifacts/gemini_live_smoke.json).
Lần chạy thật phát hiện prompt rewrite trả lời như nhân viên hỗ trợ; đã sửa để giữ góc nhìn người viết và đủ ý gốc.

Chạy lại khi muốn kiểm tra API thật (cần cài cả `requirements-dev.txt`):

```bash
python scripts/smoke_gemini.py --live
```

Lệnh dùng quota Gemini và dừng ngay khi một case fail; không lưu API key hoặc thought signature vào báo cáo.
`.env` cục bộ được chuyển từ project LLM trước, chỉ lấy các biến LLM cần thiết, có quyền file `600` và được Git bỏ qua.
Kết quả smoke chỉ xác nhận các ví dụ training này, không thay thế evaluation chất lượng trên tập độc lập.
Auth/session, persistence/draft idempotency lâu dài, phê duyệt, evaluation toàn project và RAG thuộc lớp chung.
Hành vi checklist pending của workflow gốc được giữ theo contract 06; nhóm cần thống nhất điểm này với câu chữ
approval/write boundary ở PDF trước khi nghiệm thu toàn project.
