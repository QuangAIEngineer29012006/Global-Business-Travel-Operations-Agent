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
| `backend/function_calling.py` | Đề xuất tool, kiểm tra arguments đã bind và đóng gói observation cho Gemini |
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
Fallback giữ token usage mà provider đã trả, ngay cả khi JSON/plan không hợp lệ; chỉ để `null` khi chưa có số liệu.

Yêu cầu `Viết lại: ...` hoặc `Viết lại chuyên nghiệp: ...` gọi text generation một lần và không gọi tool/retrieval.
Nó chỉ biên tập text người dùng cung cấp, không chứng thực trạng thái nghiệp vụ. Simulator ghi rõ chưa viết lại bằng LLM.
Backend không lưu raw conversation, không tạo persistent memory riêng. Memory owner có thể truyền session dict vào
`LLMService.run(request, session=...)`; API này không tự lưu context giữa các request.

## Native function calling để nhóm tích hợp

`propose_tool_call()` gửi cho Gemini đúng các khai báo tool được caller cho phép ở phase hiện tại.
Nó nhận đúng một `functionCall`, kiểm tra tên tool và ID đã bind, rồi trả `name` và `arguments` cho caller.
Khi tích hợp với registry có `request_approval`, caller phải đánh dấu yêu cầu rõ ràng và bind toàn bộ
tham số. Demo trên nhánh `backend` chỉ cấp hai tool đọc.

Khi nối vào workflow, kiểm tra budget trước khi gọi model và chạy tool qua `Executor.call()` để
dispatcher kiểm tra quyền, schema và domain. Sau đó dùng `complete_tool_turn()` để kiểm tra
observation và tạo Gemini function response. Ví dụ cho một phase đọc trước chuyến đi:

```python
from backend.function_calling import complete_tool_turn, propose_tool_call, read_tool_declarations

proposal = propose_tool_call(
    client, contents, read_tool_declarations(registry),
    ["get_trip_request", "get_approval_status"],
    bound_arguments={"trip_id": validated_trip_id},
)
observation = executor.call(proposal.name, proposal.arguments, phase="read_trip_status")
turn = complete_tool_turn(contents, proposal, observation)
```

`turn` có observation, token usage và retry count. History dùng để tiếp tục với Gemini trong bộ nhớ,
bao gồm function call ID và thought signature. Trace chỉ cần ghi tên tool, tham số đã lọc,
kết quả kiểm tra và lý do dừng. Nếu adapter trả `LLMError`, orchestrator quyết định dừng
hay chuyển sang luồng đọc bằng code theo budget còn lại.

`tool_turn()` kết hợp hai hàm trên với đúng một lời gọi dispatcher cho CLI và smoke test.

```bash
python scripts/demo_llm.py --function-call
```

Lệnh cần Gemini đã cấu hình. Ví dụ hỏi trạng thái duyệt của `TRIP-2026-001` và cho model chọn giữa
`get_trip_request` và `get_approval_status`. CLI in tool thực sự được chọn và observation.
Ngày 11/11/2026, demo với `gemini-3.5-flash-lite` đã chọn `get_approval_status` và nhận
`pending` từ mock approval system.

## Phần cần bàn giao theo PDF

`POST /api/runs` hiện chạy workflow Python rồi dùng Gemini để trình bày. Các hàm trên là điểm nối
cho người phụ trách orchestrator. Demo CLI xác minh một lượt native tool call.

| Người phụ trách | Việc còn lại và tiêu chí kiểm tra |
|---|---|
| Workflow / orchestrator (§7, §10.1, §16) | Gắn proposal vào ít nhất một luồng nghiệp vụ qua `/api/runs`. Trace thể hiện Gemini đề xuất, executor kiểm tra và chạy tool, rồi workflow quyết định bước tiếp theo. Câu hỏi chỉ xem approval/itinerary đi vào nhánh đọc và không tạo draft. |
| Approval / mock tools (§11.2, §12) | Kiểm tra approval trước khi ghi draft. Với `pending` hoặc `rejected`, assert không gọi tool ghi và không có draft mới. Approval mô phỏng không che bản ghi đã duyệt. Kiểm tra scope của profile tool và trả lỗi có kiểm soát nếu mock tool trả payload sai cấu trúc. |
| Agentic RAG (§10) | Cho phép hỏi policy chung qua retrieval mà không cần mã chuyến nếu câu hỏi không phụ thuộc chuyến đi. Với câu hỏi kết hợp, đọc facts trước và chỉ giữ citation hỗ trợ từng hướng dẫn. Bổ sung ca evidence sai ngữ cảnh, no-result và version conflict. |
| Evaluation / bàn giao (§13–14) | Thêm `argument_accuracy` cho ID và tham số quan trọng, truyền `case_id` vào từng bước trace và đếm số lần retry thực sự. Cập nhật ca pending để kiểm tra không ghi draft. Sau tích hợp, chạy lại offline/live, ghi tỷ lệ fallback và sửa README gốc để khởi động bằng `backend.main:create_app --factory`. |

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
