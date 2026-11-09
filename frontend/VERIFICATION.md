# Kiểm tra frontend — 2026-11-09

- `npm test`: 9/9 qua. Bao gồm request envelope, actor theo tình huống, nguồn có sẵn
  trong response, metadata-only artifact, trace, đổi actor, retry giữ nguyên request ID,
  chống gửi trùng và trạng thái LLM fallback.
- `npm run build`: TypeScript và Vite build thành công.
- `.venv/bin/python -m pytest -q`: 106/106 qua; một cảnh báo deprecation từ Starlette TestClient/httpx.
- Gọi qua Vite proxy với fake LLM: cả sáu mẫu khớp workflow/status thực tế:

| Mẫu | Workflow | Status | Reason |
| --- | --- | --- | --- |
| Chuẩn bị TRIP-2026-002 | pre_trip | completed | CHECKLIST_READY |
| Kiểm tra TRIP-2026-001 | pre_trip | awaiting_approval | APPROVAL_PENDING |
| Delay TRIP-2026-002 | in_trip | completed | ESCALATION_DRAFT_READY |
| Hủy TRIP-2026-003 | in_trip | needs_human | CANCELLED_REQUIRES_HUMAN |
| EXP-2026-001 | post_trip | completed | NO_ISSUE_FOUND |
| Reviewer EXP-2026-003 | post_trip | needs_human | FLAGS_FOR_REVIEW |

Browser local: đã gửi mẫu pre-trip, mở metadata nguồn, bảng kết quả, trace và danh sách
bản nháp. Bố cục 390×844 không tràn ngang (`scrollWidth = innerWidth = 390`).
Desktop kiểm tra tại viewport 1280 không có phần tử tràn ngang.

Lượt thật qua UI: `gemini-3.5-flash-lite`, `llm.status=ok`, 192 input tokens,
8 output tokens, `CHECKLIST_READY`, artifact `not_sent`. Đây là một lượt kiểm tra
kết nối; không phải đánh giá chất lượng model trên toàn bộ tình huống.

CSS gốc và Dialog khớp từng byte với miniproject4. Không thay đổi backend,
workflow, fixture hay triển khai RAG. Key không nằm trong source frontend.

Giới hạn hiện tại: actor giả lập, lịch sử chỉ trong tab, API chỉ trả metadata artifact
và metadata citation. Nội dung draft/đoạn trích chưa thể đọc đầy đủ qua response hiện tại.
