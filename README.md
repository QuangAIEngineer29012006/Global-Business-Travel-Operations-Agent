# Global Business Travel Operations Agent

Prototype học tập cho Agent hỗ trợ vận hành công tác quốc tế trên dữ liệu giả lập. Thiết kế dùng workflow có giới hạn, function calling theo allowlist, policy evidence, artifact dạng draft và trace phục vụ đánh giá. Không thực hiện đặt dịch vụ, thanh toán, hoàn tiền hoặc liên lạc thật.

## Backend trên nhánh `backend`

Backend FastAPI, CLI và adapter Gemini function calling nằm trong `backend/` và `travel_agent/`.
Xem [hướng dẫn backend](docs/backend/README.md) để cài đặt, chạy demo và gọi API.

Phần này được bổ sung từ nhánh `huy`. Workflow ở `src/`, fixture trong `data/mock-systems/`
và bài test gốc `tests/test_workflows.py` được giữ nguyên. Backend hiện chạy bộ fixture riêng
`data/training.json` và `data/policies.json`; chưa nối adapter với bộ fixture của workflow gốc.

## Cấu trúc

- `docs/agent-design/`: tài liệu kiến trúc và contract.
- `data/mock-systems/`: fixture giả lập CSV, JSON và Markdown; nội dung dữ liệu bằng tiếng Việt, schema/ID/enum giữ tiếng Anh.
- `scripts/preprocess_to_sqlite.py`: kiểm tra, chuẩn hóa và nạp fixture vào SQLite bằng Python standard library.
- `data/processed/`: database và báo cáo validation được sinh; database không đưa vào Git.

## Tạo database cục bộ

Từ thư mục gốc dự án:

```powershell
python scripts/preprocess_to_sqlite.py
```

Có thể truyền đường dẫn riêng bằng `--source data/mock-systems --output data/processed/travel_agent.sqlite`. Script không sửa fixture nguồn; lỗi đọc/validation được ghi vào `data/processed/validation_report.json`.

## An toàn dữ liệu

Mọi nhân vật, khoản chi và policy đều hư cấu. Không thêm PII thật, credential, thông tin thanh toán hoặc policy production.
