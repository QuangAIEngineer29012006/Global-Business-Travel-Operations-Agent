# Agent Design & Contracts

Tài liệu thiết kế nền tảng cho Global Business Travel Operations Agent. Mục đích là thống nhất kiến trúc, contract và ranh giới trước khi triển khai mock systems hoặc ba workflow nghiệp vụ.

## Tài liệu

1. [Architecture](./01-architecture.md): thành phần, luồng điều khiển, nguồn sự thật và ranh giới hệ thống.
2. [Agent contract](./02-agent-contract.md): vai trò, yêu cầu, response, run state và terminal outcomes.
3. [Tool contract](./03-tool-contract.md): registry, allowlist, dispatcher, schema, lỗi, budget và retry.
4. [Domain data contract](./04-domain-data-contract.md): entity, identifiers, quan hệ, metadata và yêu cầu dataset; đây là schema spec, chưa phải dữ liệu mock.
5. [Workflow integration requirements](./05-workflow-integration.md): yêu cầu mà ba workflow phải tuân thủ khi tích hợp với Agent.

## Thứ tự đọc và triển khai

Đọc architecture và Agent contract trước; thống nhất tool/data contracts giữa các thành viên; sau đó mới tạo mock systems, rồi triển khai workflow. Nếu cần thay đổi contract, cập nhật tài liệu này trước khi sửa implementation phụ thuộc vào nó.

## Phạm vi

Prototype học tập chạy trên dữ liệu và dịch vụ giả lập. Không tích hợp production và không thực hiện giao dịch hoặc liên lạc thật. Tài liệu trong thư mục này là yêu cầu thiết kế; không chứa dữ liệu mock thực tế.
