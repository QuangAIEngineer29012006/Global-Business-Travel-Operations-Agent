# Global Business Travel Operations Agent

Prototype học tập cho Agent hỗ trợ vận hành công tác quốc tế trên dữ liệu giả lập. Thiết kế dùng workflow có giới hạn (`pre_trip`, `in_trip`, `post_trip`), function calling theo allowlist, Agentic RAG có policy grounding & citation, quản lý state/session cô lập, artifact dạng bản nháp (`draft`) kèm mô phỏng phê duyệt (`pending`) và bộ Evaluation Matrix 20 test cases có trace phục vụ kiểm toán. **Không thực hiện đặt dịch vụ, thanh toán, hoàn tiền hoặc gửi liên lạc thật.**

---

## Danh mục Bàn giao (Handover Checklist)

| Hạng mục bàn giao theo yêu cầu | Vị trí File / Artifact trong Repository | Trạng thái |
| :--- | :--- | :---: |
| **1. Source code & Notebook chạy được** | [`src/workflows.py`](src/workflows.py), [`src/dev_systems.py`](src/dev_systems.py), [`src/policy_search.py`](src/policy_search.py), [`backend/`](backend/), [`frontend/`](frontend/), [`notebooks/travel_agent_demo_and_eval.ipynb`](notebooks/travel_agent_demo_and_eval.ipynb) | ✅ Hoàn tất |
| **2. Demo ngắn cho 3 Workflow** | [`demo.py`](demo.py) (CLI 3 workflows), [`scripts/demo_llm.py`](scripts/demo_llm.py) (LLM + native function calling), [`notebooks/travel_agent_demo_and_eval.ipynb`](notebooks/travel_agent_demo_and_eval.ipynb) | ✅ Hoàn tất |
| **3. Mock Datasets & Policy Corpus** | [`data/mock-systems/`](data/mock-systems/) (8 travel requests, 6 traveler profiles, 6 itineraries, 5 approvals, 3 expense reports, 5 policy docs / 9 chunks, [`fixture-manifest.csv`](data/mock-systems/fixture-manifest.csv)) | ✅ Hoàn tất |
| **4. Tool Schemas / Registry / Allowlist** | [`src/dev_systems.py`](src/dev_systems.py), [`docs/agent-design/03-tool-contract.md`](docs/agent-design/03-tool-contract.md), [`docs/handover/architecture-and-memory-policy.md`](docs/handover/architecture-and-memory-policy.md) | ✅ Hoàn tất |
| **5. Sơ đồ Kiến trúc & Workflow** | [`docs/handover/architecture-and-memory-policy.md`](docs/handover/architecture-and-memory-policy.md), [`docs/agent-design/01-architecture.md`](docs/agent-design/01-architecture.md), [`docs/agent-design/06-workflows.md`](docs/agent-design/06-workflows.md) | ✅ Hoàn tất |
| **6. Memory & State Policy** | [`backend/state_store.py`](backend/state_store.py), [`docs/handover/architecture-and-memory-policy.md`](docs/handover/architecture-and-memory-policy.md), [`docs/agent-design/02-agent-contract.md`](docs/agent-design/02-agent-contract.md) | ✅ Hoàn tất |
| **7. Test Matrix ($\ge 15$ cases), Traces & Metrics** | **20 kịch bản** tại [`src/eval_harness.py`](src/eval_harness.py), [`scripts/run_evaluation.py`](scripts/run_evaluation.py), [`tests/test_evaluation_matrix.py`](tests/test_evaluation_matrix.py), [`artifacts/eval_metrics.json`](artifacts/eval_metrics.json), [`artifacts/eval_traces.json`](artifacts/eval_traces.json) | ✅ Hoàn tất (20/20 PASS) |
| **8. Báo cáo Phân tích Lỗi (Debug RCA) & Cải tiến** | [`docs/evaluation/test-matrix-and-report.md`](docs/evaluation/test-matrix-and-report.md), [`artifacts/gemini_live_smoke.json`](artifacts/gemini_live_smoke.json) | ✅ Hoàn tất |

---

## Hướng dẫn Chạy nhanh (Quickstart)

### 1. Cài đặt môi trường & Khởi tạo SQLite Database

Từ thư mục gốc dự án (Python 3.10+):

```powershell
pip install -r requirements.txt -r requirements-dev.txt
python scripts/preprocess_to_sqlite.py
```

- Lệnh `preprocess_to_sqlite.py` kiểm tra toàn vẹn khóa ngoại của `data/mock-systems/`, nạp dữ liệu vào `data/processed/travel_agent.sqlite`, tạo chỉ mục FTS5 + semantic embeddings và xuất báo cáo `data/processed/validation_report.json`.
- Để chạy thuần từ khóa (không tải model embedding): đặt biến môi trường `POLICY_SEMANTIC_MODE=keyword`.

### 2. Chạy Demo ngắn cho 3 Workflow (`pre_trip`, `in_trip`, `post_trip`)

```powershell
python demo.py
```

Hoặc chạy qua lớp `LLMService` (mặc định dùng offline simulator không cần API key; hỗ trợ `--function-call` khi cấu hình Gemini):

```powershell
python scripts/demo_llm.py
```

### 3. Chạy Bộ Đánh giá (Evaluation Matrix 20 Cases) & Xuất Metrics/Traces

```powershell
python scripts/run_evaluation.py
```

- Xuất báo cáo định lượng ra [`artifacts/eval_metrics.json`](artifacts/eval_metrics.json) và toàn bộ trace đã làm sạch ra [`artifacts/eval_traces.json`](artifacts/eval_traces.json).
- Kết quả đạt **20/20 (100%)** trên cả 5 nhóm chỉ số: Task Completion (100%), Tool Selection & Allowlist (100%), Grounding & Citation Precision (100% trên 42 citations), Safety & Guardrail (100%), trung bình **3.85 bước/run**.

### 4. Chạy Toàn bộ Kiểm thử Tự động (Pytest Suite)

```powershell
python -m pytest -q
```

Bao gồm 4 bộ kiểm thử: `tests/test_workflows.py`, `tests/test_policy_search.py`, `tests/test_llm_backend.py` (`tests/test_llm_client.py`) và `tests/test_evaluation_matrix.py`.

### 5. Chạy Backend FastAPI & Frontend Demo

- **Backend API** (chi tiết tại [`docs/backend/README.md`](docs/backend/README.md)):
  ```powershell
  uvicorn backend.main:app --reload --port 8000
  ```
- **Frontend React/Vite** (chi tiết tại [`frontend/README.md`](frontend/README.md)):
  ```powershell
  cd frontend
  npm install
  npm run dev
  ```

---

## Cấu trúc Thư mục

- `docs/agent-design/`: Tài liệu kiến trúc và contract (`01` đến `06`).
- `docs/handover/`: Sơ đồ kiến trúc Mermaid, luồng 3 workflows, bảng Tool Registry/Allowlist và Memory Policy.
- `docs/evaluation/`: Báo cáo Test Matrix 20 kịch bản, bảng Metrics, Trace mẫu, Nhật ký Debug RCA và Đề xuất cải tiến.
- `docs/backend/`: Hướng dẫn cấu hình Backend FastAPI, Gemini adapter và SQLite `StateStore`.
- `data/mock-systems/`: Fixture giả lập CSV, JSON và Markdown; nội dung tiếng Việt, schema/ID/enum tiếng Anh.
- `src/`: Nhân thực thi gồm `workflows.py`, `dev_systems.py`, `policy_search.py` và `eval_harness.py`.
- `backend/`: FastAPI server, Gemini client, function calling adapter và `state_store.py`.
- `frontend/`: Giao diện React/Vite phục vụ trình diễn trực quan 6 tình huống mẫu, citations và trace.
- `scripts/`: Script tiền xử lý SQLite (`preprocess_to_sqlite.py`), chạy đánh giá (`run_evaluation.py`), demo LLM (`demo_llm.py`) và kiểm thử Gemini thật (`smoke_gemini.py`).
- `notebooks/`: Jupyter Notebook [`travel_agent_demo_and_eval.ipynb`](notebooks/travel_agent_demo_and_eval.ipynb) chạy sẵn kết quả demo & đánh giá.
- `artifacts/`: Lưu trữ kết quả chạy thực nghiệm (`eval_metrics.json`, `eval_traces.json`, `gemini_live_smoke.json`).

---

## An toàn Dữ liệu (Safety & Guardrails)

Mọi nhân vật, khoản chi và quy định đều là dữ liệu hư cấu phục vụ học tập. Không chứa PII thật, credential, thông tin thanh toán hoặc kết nối production.
