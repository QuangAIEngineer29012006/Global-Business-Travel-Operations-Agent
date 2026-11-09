# Travel Operations frontend

Chuyển từ `miniproject4/LLM-mini-project/frontend`: giữ nguyên `src/styles.css`,
`src/Dialog.tsx`, cấu hình React/Vite và phong cách nền sáng, màu lime, card và chat drawer.
`App.tsx`, API client và kiểu dữ liệu được thay để dùng contract travel.

## Chạy local

Cần Node >= 22.12 và môi trường Python theo [hướng dẫn backend](../docs/backend/README.md).
Chạy hai terminal từ thư mục gốc repo.

Terminal 1:

```sh
.venv/bin/python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

Trên Windows dùng `.venv\Scripts\python.exe` thay cho `.venv/bin/python`.
Backend đọc `.env` ở gốc repo. `LLM_PROVIDER=fake` chạy offline;
`LLM_PROVIDER=gemini` dùng model/key đã cấu hình theo hướng dẫn backend.

Terminal 2:

```sh
cd frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Mở <http://127.0.0.1:5173>. Vite proxy `/api` đến `http://127.0.0.1:8000`.
Có thể đổi đích bằng biến môi trường `API_PROXY_TARGET` trước khi khởi động Vite.
Key Gemini chỉ nằm ở backend; không tạo biến `VITE_*` chứa key.

## Cách thử

1. Chọn một trong sáu tình huống. Giao diện chọn actor giả lập tương ứng và điền tin nhắn.
2. Bấm gửi. Kết quả chỉ lấy từ `POST /api/runs`.
3. Mở nguồn, chi tiết kết quả hoặc trace. Tab Kết quả cho tải response JSON.
4. Tab Bản nháp hiển thị mã, loại và trạng thái artifact.

Các tình huống gồm checklist đã duyệt, chờ duyệt, delay, hủy chuyến,
expense không có vấn đề và expense cần reviewer. Danh sách này chỉ là mẫu yêu cầu;
trạng thái kết quả không được gán sẵn ở frontend.

Vai trò là lựa chọn giả lập, không phải đăng nhập. Đổi vai trò hoặc mở phiên mới
xóa lịch sử UI. Reload cũng xóa lịch sử; không có lưu hội thoại hoặc dữ liệu vào localStorage.
Backend hiện yêu cầu mã TRIP/EXP trong mỗi yêu cầu nghiệp vụ; vẫn có thể nhờ viết lại văn bản.

Response hiện chỉ có metadata artifact, không có toàn bộ nội dung bản nháp.
Nguồn hiển thị metadata citation và chỉ hiển thị đoạn trích nếu response có cung cấp;
không dựng nội dung nguồn hoặc thêm endpoint RAG. Toàn bộ nghiệp vụ vẫn chạy trên mock systems.

## Kiểm tra

```sh
npm test
npm run build
```

`npm run build` tạo `dist/`. Để chạy bản build local có backend proxy:

```sh
npm run preview -- --port 5173 --strictPort
```

Khi deploy cần reverse proxy `/api` về backend. Lựa chọn actor giả lập này phục vụ demo nội bộ.
