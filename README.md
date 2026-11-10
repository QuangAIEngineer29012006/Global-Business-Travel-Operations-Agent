# Global Business Travel Operations Agent

Prototype học tập cho Agent hỗ trợ vận hành công tác quốc tế trên dữ liệu giả lập. Thiết kế dùng workflow có giới hạn, function calling theo allowlist, policy evidence, artifact dạng draft và trace phục vụ đánh giá. Không thực hiện đặt dịch vụ, thanh toán, hoàn tiền hoặc liên lạc thật.

## Backend trên nhánh `backend`

Backend FastAPI, adapter Gemini và SQLite-backed sandbox stores nằm trong `backend/`.
Xem [hướng dẫn backend](docs/backend/README.md) để cài đặt, chạy demo và gọi API.

Backend dùng trực tiếp workflow ở `src/workflows.py` và dispatcher/fixture của `huy`.
Phần LLM chỉ hỗ trợ trình bày kết quả; không có dataset, database, workflow hoặc RAG thứ hai.
Native function calling được cung cấp dưới dạng adapter một lượt, có thể nối với dispatcher của nhóm.

## Frontend demo

Giao diện React/Vite được chuyển từ miniproject4 và nối với backend travel hiện tại.
Có chat, sáu tình huống mẫu, kết quả, metadata bản nháp, citation và trace.
Xem [cách chạy frontend](frontend/README.md). Frontend không bổ sung RAG mới.

## Cấu trúc

- `docs/agent-design/`: tài liệu kiến trúc và contract.
- `data/mock-systems/`: fixture giả lập CSV, JSON và Markdown; nội dung dữ liệu bằng tiếng Việt, schema/ID/enum giữ tiếng Anh.
- `scripts/preprocess_to_sqlite.py`: kiểm tra fixture, nạp dữ liệu và tạo hybrid policy index trong SQLite.
- `data/processed/`: database và báo cáo validation được sinh; database không đưa vào Git. API runtime dùng `agent_state.sqlite` để lưu run/session state, draft workspace và approval simulation.
- Backend lưu run summary, session context và preference opt-in trong `data/processed/agent_state.sqlite` mặc định; đổi vị trí bằng `AGENT_STATE_DB`.

## Tạo database cục bộ

Từ thư mục gốc dự án:

```powershell
pip install -r requirements.txt
python scripts/preprocess_to_sqlite.py
```

Có thể truyền đường dẫn riêng bằng `--source data/mock-systems --output data/processed/travel_agent.sqlite`. Script không sửa fixture nguồn; lỗi đọc/validation được ghi vào `data/processed/validation_report.json`.

Preprocessing builds a SQLite FTS5 index and semantic embeddings for policy chunks.
Hybrid search uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`;
its first use downloads and caches the model. Set `POLICY_EMBEDDING_MODEL` to
select another compatible local model. To run without semantic embeddings, set
`POLICY_SEMANTIC_MODE=keyword` for keyword-only indexing and retrieval.

## An toàn dữ liệu

Mọi nhân vật, khoản chi và policy đều hư cấu. Không thêm PII thật, credential, thông tin thanh toán hoặc policy production.
