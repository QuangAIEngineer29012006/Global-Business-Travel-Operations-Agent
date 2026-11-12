import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import App from './App'
import { Run } from './types'

const result: Run = {
  request_id: 'REQ-TEST', run_id: 'RUN-TEST', workflow: 'pre_trip', status: 'awaiting_approval',
  reason_code: 'APPROVAL_PENDING', message: 'Yêu cầu đang chờ phê duyệt, chưa được duyệt.',
  data: { approval_status: 'pending' }, evidence: [{ chunk_id: 'CHUNK-001', doc_id: 'DOC-001', source: 'training.md', section: 'Checklist', version: '1.0' }],
  artifacts: [{ draft_id: 'DRAFT-TEST', artifact_type: 'travel_checklist', status: 'draft_created', delivery_status: 'not_sent', source_ids: ['TRIP-2026-001'],
    content: { policy_guidance: [{ text: 'Policy fixture: cần kiểm tra giấy tờ.', citation: { chunk_id: 'CHUNK-001' } }] } }],
  next_action: 'Chờ người phê duyệt quyết định.', steps: 7,
  trace: [{ trace_id: 'TRACE-1', action: 'get_trip_request', phase: 'fetch_trip', observation_status: 'ok' }],
  llm: { status: 'ok', provider_model: 'fake-test', calls: 1, message: 'Yêu cầu đang chờ phê duyệt, chưa được duyệt.', input_tokens: 20, output_tokens: 5, retry_count: 0, error_code: null },
}
const response = (body: unknown, ok = true, status = 200) => ({ ok, status, json: async () => body })
let fetcher: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetcher = vi.fn(async (path: string) => path === '/api/health'
    ? response({ status: 'ok', provider: 'fake', model_id: 'fake-test', training_only: true })
    : response(structuredClone(result)))
  vi.stubGlobal('fetch', fetcher)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

async function openChat() {
  render(<App/>); await screen.findByText('Mô phỏng offline · fake')
  fireEvent.click(screen.getByRole('button', { name: 'Mở trợ lý' }))
  return screen.getByRole('dialog', { name: 'Trợ lý công tác' })
}
async function send(message = 'Chuẩn bị TRIP-2026-001') {
  fireEvent.change(screen.getByRole('textbox', { name: 'Tin nhắn' }), { target: { value: message } })
  fireEvent.click(screen.getByRole('button', { name: 'Gửi' }))
  await screen.findByText('Yêu cầu đang chờ phê duyệt, chưa được duyệt.')
}
const runCalls = () => fetcher.mock.calls.filter(([path]) => path === '/api/runs')

describe('Travel UI adapted from the commerce frontend', () => {
  it('filters actual demo scenarios and resets an empty search', async () => {
    render(<App/>); await screen.findByText('Mô phỏng offline · fake')
    fireEvent.change(screen.getByRole('textbox', { name: 'Tìm tình huống' }), { target: { value: 'does-not-exist' } })
    expect(screen.getByText('Không tìm thấy tình huống')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Xóa bộ lọc' }))
    expect(screen.getByText('6 tình huống')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Sau chuyến đi' }))
    expect(screen.getByText('2 tình huống')).toBeTruthy()
  })

  it('uses the scenario actor and sends the documented backend envelope', async () => {
    render(<App/>); await screen.findByText('Mô phỏng offline · fake')
    fireEvent.click(screen.getByRole('button', { name: /Kiểm tra điều kiện phê duyệt/ }))
    const input = screen.getByRole('textbox', { name: 'Tin nhắn' }) as HTMLInputElement
    expect(input.value).toContain('TRIP-2026-001')
    fireEvent.click(screen.getByRole('button', { name: 'Gửi' }))
    await screen.findByText('Chờ phê duyệt')
    const body = JSON.parse((runCalls()[0][1] as RequestInit).body as string)
    expect(body.actor).toEqual({ role: 'employee', actor_id: 'EMP-001' })
    expect(body.context).toEqual({})
    expect(body.session_id).toBeTruthy(); expect(body.request_id).toBeTruthy()
    expect(body.message).toContain('TRIP-2026-001')
  })

  it('opens a source already in the response without another backend request', async () => {
    await openChat(); await send()
    fireEvent.click(screen.getByRole('button', { name: /Checklist.*CHUNK-001/ }))
    expect(within(screen.getByRole('dialog', { name: 'Nguồn trích dẫn' })).getByText('Policy fixture: cần kiểm tra giấy tờ.')).toBeTruthy()
    expect(fetcher.mock.calls.length).toBe(2)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Nguồn trích dẫn' })).toBeNull()
    expect(screen.getByRole('dialog', { name: 'Trợ lý công tác' })).toBeTruthy()
  })

  it('shows the cited policy excerpt for a question without a trip or report ID', async () => {
    const answer = 'Theo tài liệu policy: Cần xác minh điều kiện nhập cảnh. [1]'
    const excerpt = 'Nhân viên cần xác minh điều kiện nhập cảnh trước chuyến đi.'
    const policy: Run = { ...structuredClone(result), workflow: 'policy_qa', status: 'completed', reason_code: 'POLICY_ANSWER',
      message: answer, data: {}, artifacts: [], next_action: null,
      evidence: [{ chunk_id: 'CHUNK-005', doc_id: 'DOC-VISA-001', source: 'Hướng dẫn chuẩn bị công tác quốc tế', section: 'Kiểm tra điều kiện nhập cảnh', version: '1.2', excerpt }],
      llm: { ...result.llm, status: 'skipped', calls: 0, message: answer } }
    fetcher.mockImplementation(async (path: string) => path === '/api/health'
      ? response({ status: 'ok', provider: 'fake', model_id: 'fake-test', training_only: true })
      : response(structuredClone(policy)))
    await openChat()
    fireEvent.change(screen.getByRole('textbox', { name: 'Tin nhắn' }), { target: { value: 'Quy định về visa là gì?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi' }))
    await screen.findByText(answer)
    expect(screen.getByText('Nguồn tài liệu')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Kiểm tra điều kiện nhập cảnh.*CHUNK-005/ }))
    expect(within(screen.getByRole('dialog', { name: 'Nguồn trích dẫn' })).getByText(excerpt)).toBeTruthy()
  })

  it('shows the backend result, draft and trace rather than inventing a status', async () => {
    await openChat(); await send()
    fireEvent.click(screen.getByRole('button', { name: /Xem kết quả và trace/ }))
    const dialog = screen.getByRole('dialog', { name: 'Chi tiết kết quả' })
    expect(within(dialog).getByText('Chờ phê duyệt')).toBeTruthy()
    expect(within(dialog).getByText('20 / 5')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Trace' }))
    expect(within(dialog).getByText('get_trip_request')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Đóng kết quả' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bản nháp (1)' }))
    expect(screen.getByRole('button', { name: /DRAFT-TEST/ })).toBeTruthy()
  })

  it('renders metadata-only artifacts returned by the current workflow', async () => {
    fetcher.mockImplementation(async (path: string) => path === '/api/health'
      ? response({ status: 'ok', provider: 'fake', model_id: 'fake-test' })
      : response({ ...result, artifacts: [{ draft_id: 'DRAFT-META', artifact_type: 'travel_checklist', status: 'draft_created', delivery_status: 'not_sent' }] }))
    await openChat(); await send()
    fireEvent.click(screen.getByRole('button', { name: 'Đóng chat' }))
    fireEvent.click(screen.getByRole('button', { name: 'Bản nháp (1)' }))
    expect(screen.getByRole('button', { name: /DRAFT-META/ })).toBeTruthy()
    expect(screen.getByText('API hiện trả mã và trạng thái bản nháp.')).toBeTruthy()
  })

  it('clears actor-scoped UI state on identity change', async () => {
    await openChat(); await send()
    fireEvent.click(screen.getByRole('button', { name: 'Đóng chat' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Vai trò giả lập' }), { target: { value: 'employee:EMP-003' } })
    expect(screen.getByRole('button', { name: 'Kết quả (0)' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Bản nháp (0)' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Mở trợ lý' }))
    expect(screen.queryByText('Yêu cầu đang chờ phê duyệt, chưa được duyệt.')).toBeNull()
  })

  it('shows a failed request and retries the exact original body/key even after input is edited', async () => {
    fetcher.mockImplementation(async (path: string) => path === '/api/health'
      ? response({ status: 'ok', provider: 'fake', model_id: 'fake-test' })
      : response({ error: { message: 'Lỗi kết nối thử nghiệm' } }, false, 503))
    await openChat()
    fireEvent.change(screen.getByRole('textbox', { name: 'Tin nhắn' }), { target: { value: 'Chuẩn bị TRIP-2026-001' } })
    fireEvent.click(screen.getByRole('button', { name: 'Gửi' }))
    await screen.findByRole('alert')
    const first = JSON.parse((runCalls()[0][1] as RequestInit).body as string)
    fireEvent.change(screen.getByRole('textbox', { name: 'Tin nhắn' }), { target: { value: 'Không phải yêu cầu ban đầu' } })
    fetcher.mockImplementation(async () => response(result))
    fireEvent.click(screen.getByRole('button', { name: 'Gửi lại yêu cầu' }))
    await screen.findByText('Chờ phê duyệt')
    const retried = JSON.parse((runCalls()[1][1] as RequestInit).body as string)
    expect(retried).toEqual(first)
  })

  it('blocks double submit and identity changes while a run is pending', async () => {
    let resolve!: (value: unknown) => void
    fetcher.mockImplementation(async (path: string) => path === '/api/health'
      ? response({ status: 'ok', provider: 'fake', model_id: 'fake-test' })
      : new Promise(done => { resolve = done }))
    await openChat()
    fireEvent.change(screen.getByRole('textbox', { name: 'Tin nhắn' }), { target: { value: 'Chuẩn bị TRIP-2026-001' } })
    const button = screen.getByRole('button', { name: 'Gửi' }) as HTMLButtonElement
    fireEvent.click(button); fireEvent.click(button)
    expect(button.disabled).toBe(true)
    expect((screen.getByRole('combobox', { name: 'Vai trò giả lập' }) as HTMLSelectElement).disabled).toBe(true)
    expect(runCalls().length).toBe(1)
    resolve(response(result))
    await screen.findByText('Chờ phê duyệt')
    await waitFor(() => expect(button.disabled).toBe(true)) // composer is empty after success
  })

  it('preserves workflow facts when LLM presentation falls back', async () => {
    fetcher.mockImplementation(async (path: string) => path === '/api/health'
      ? response({ status: 'ok', provider: 'fake', model_id: 'fake-test' })
      : response({ ...result, llm: { ...result.llm, status: 'fallback', error_code: 'llm_timeout' } }))
    await openChat(); await send()
    expect(screen.getByText(/Phần trình bày LLM đang fallback/)).toBeTruthy()
    expect(screen.getByText('Chờ phê duyệt')).toBeTruthy()
  })
})
