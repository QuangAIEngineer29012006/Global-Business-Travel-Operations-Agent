export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  let response: Response
  try { response = await fetch(path, { ...init, headers }) }
  catch { throw new ApiError('Không thể kết nối máy chủ. Hãy kiểm tra backend rồi thử lại.', 0) }
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(data?.error?.message || 'Máy chủ chưa xử lý được yêu cầu. Vui lòng thử lại.', response.status)
  if (!data) throw new ApiError('Máy chủ trả về dữ liệu không hợp lệ. Vui lòng thử lại.', response.status)
  return data as T
}
