export type Actor = { role: 'employee' | 'travel_operations_reviewer' | 'approver'; actor_id: string }
export type Citation = { chunk_id: string; doc_id: string; source: string; section: string; version: string; excerpt?: string; category?: string }
export type Artifact = {
  draft_id: string; artifact_type: string; status: string; delivery_status: string; source_ids?: string[];
  content?: Record<string, unknown>
}
export type Trace = {
  trace_id: string; phase: string; action: string; observation_status: string; transition?: string;
  retry_count?: number; safe_args?: Record<string, unknown>; budget?: Record<string, unknown>
}
export type Run = {
  request_id: string; run_id: string; workflow: string; status: string; reason_code: string; message: string;
  data: Record<string, unknown>; evidence: Citation[]; artifacts: Artifact[]; next_action: string | null;
  steps: number; trace: Trace[];
  llm: { status: string; provider_model: string; calls: number; message: string; input_tokens: number | null;
    output_tokens: number | null; retry_count: number; error_code: string | null }
}
export type Health = { status: string; provider: string; model_id: string; training_only: boolean }
export type Scenario = { id: string; title: string; category: string; description: string; reference: string; actor: Actor; prompt: string; label: string }

export const statusLabels: Record<string, string> = {
  completed: 'Hoàn tất trong sandbox', awaiting_approval: 'Chờ phê duyệt', needs_input: 'Cần bổ sung',
  needs_human: 'Cần người phụ trách', rejected: 'Từ chối truy cập', failed_validation: 'Dữ liệu chưa hợp lệ',
  partial: 'Hoàn tất một phần', failed_delivery: 'Chưa xác nhận kết quả',
}
export const workflowLabels: Record<string, string> = { pre_trip: 'Trước chuyến đi', in_trip: 'Trong chuyến đi', post_trip: 'Sau chuyến đi', direct: 'Hỗ trợ văn bản', policy_qa: 'Hỏi đáp chính sách', unrouted: 'Cần mã tham chiếu' }
export const artifactLabels: Record<string, string> = { travel_checklist: 'Checklist công tác', disruption_escalation_note: 'Ghi chú chuyển cấp', expense_review: 'Rà soát chi phí' }
export const actors: { label: string; value: Actor }[] = [
  ...['001', '002', '003', '004', '005', '006'].map(id => ({ label: `Nhân viên EMP-${id}`, value: { role: 'employee' as const, actor_id: `EMP-${id}` } })),
  { label: 'Travel Operations · REV-001', value: { role: 'travel_operations_reviewer', actor_id: 'REV-001' } },
  { label: 'Approver · APR-USER-001', value: { role: 'approver', actor_id: 'APR-USER-001' } },
]
export const actorKey = (actor: Actor) => `${actor.role}:${actor.actor_id}`

export const scenarios: Scenario[] = [
  { id: 'pre', title: 'Chuẩn bị chuyến công tác', category: 'Trước chuyến đi', description: 'Kiểm tra yêu cầu và chuẩn bị checklist với nguồn policy của bộ training.', reference: 'TRIP-2026-002', actor: actors[1].value, prompt: 'Tôi chuẩn bị công tác với mã TRIP-2026-002. Tôi cần chuẩn bị gì?', label: '01 / PRE-TRIP' },
  { id: 'pending', title: 'Kiểm tra điều kiện phê duyệt', category: 'Trước chuyến đi', description: 'Xem workflow phản ánh trạng thái approval và bước cần người phụ trách xử lý.', reference: 'TRIP-2026-001', actor: actors[0].value, prompt: 'Kiểm tra yêu cầu công tác TRIP-2026-001 đã đủ điều kiện chưa?', label: '02 / APPROVAL' },
  { id: 'delay', title: 'Hỗ trợ khi chuyến bay trễ', category: 'Trong chuyến đi', description: 'Đọc itinerary giả lập và chuẩn bị support draft cho Travel Operations.', reference: 'TRIP-2026-002', actor: actors[1].value, prompt: 'Chuyến bay của TRIP-2026-002 bị delay. Tôi nên làm gì?', label: '03 / IN-TRIP' },
  { id: 'cancel', title: 'Chuyển cấp khi chuyến bay hủy', category: 'Trong chuyến đi', description: 'Phân biệt dữ kiện hành trình với hướng dẫn và nội dung cần reviewer xem xét.', reference: 'TRIP-2026-003', actor: actors[2].value, prompt: 'Chuyến bay của TRIP-2026-003 bị hủy. Hãy hỗ trợ tôi.', label: '04 / ESCALATION' },
  { id: 'expense', title: 'Rà soát báo cáo chi phí', category: 'Sau chuyến đi', description: 'Tổng tiền do tool tính, policy đi kèm nguồn và kết quả ở dạng review draft.', reference: 'EXP-2026-001', actor: actors[2].value, prompt: 'Rà soát báo cáo chi phí EXP-2026-001 trước khi tôi nộp.', label: '05 / EXPENSE' },
  { id: 'review', title: 'Kiểm tra mục cần reviewer', category: 'Sau chuyến đi', description: 'Dùng vai trò reviewer để xem flags và các mục cần kiểm tra trong báo cáo.', reference: 'EXP-2026-003', actor: actors[6].value, prompt: 'Rà soát báo cáo chi phí EXP-2026-003 trước khi tôi nộp.', label: '06 / REVIEW' },
]
