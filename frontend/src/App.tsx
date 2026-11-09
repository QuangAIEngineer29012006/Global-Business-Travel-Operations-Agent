import { FormEvent, ReactNode, useEffect, useRef, useState } from 'react'
import { Dialog } from './Dialog'
import { request } from './api'
import { ArtifactCard, EvidenceList, RunDialog, SourceDialog, Status } from './RunDetails'
import { Actor, Citation, Health, Run, Scenario, actorKey, actors, artifactLabels, scenarios, workflowLabels } from './types'

type Message = { role: 'user' | 'assistant'; text: string; result?: Run; error?: boolean; retry?: { text: string; request_id: string } }
type Page = 'demo' | 'runs' | 'drafts'

function Icon({ name }: { name: 'chat' | 'arrow' | 'search' | 'close' }) {
  const paths = { chat: 'M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z', arrow: 'M5 12h14m-6-6 6 6-6 6', search: 'm21 21-5-5M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0Z', close: 'm6 6 12 12M6 18 18 6' }
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>
}

export default function App() {
  const [page, setPage] = useState<Page>('demo')
  const [health, setHealth] = useState<Health | null>(null)
  const [connecting, setConnecting] = useState(true)
  const [connectionError, setConnectionError] = useState('')
  const [actor, setActor] = useState<Actor>(actors[1].value)
  const [session, setSession] = useState(() => crypto.randomUUID())
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('Tất cả')
  const [chatOpen, setChatOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [runs, setRuns] = useState<Run[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [source, setSource] = useState<{ run: Run; citation: Citation } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const mutation = useRef(false)
  const pending = useRef<{ text: string; request_id: string } | null>(null)
  const noticeTimer = useRef<ReturnType<typeof setTimeout>>()

  async function checkHealth() {
    setConnecting(true); setConnectionError('')
    try { setHealth(await request<Health>('/api/health')) }
    catch (error) { setHealth(null); setConnectionError((error as Error).message) }
    finally { setConnecting(false) }
  }
  useEffect(() => { void checkHealth(); return () => clearTimeout(noticeTimer.current) }, [])
  useEffect(() => { messagesEnd.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' }) }, [messages, busy, chatOpen])

  function flash(text: string) {
    clearTimeout(noticeTimer.current); setNotice(text)
    noticeTimer.current = setTimeout(() => setNotice(''), 4500)
  }
  function changeActor(next: Actor) {
    if (mutation.current) return
    if (actorKey(next) !== actorKey(actor)) {
      setActor(next); setInput(''); setSession(crypto.randomUUID()); setMessages([]); setRuns([]); setSelectedRun(null); setSource(null)
      pending.current = null
    }
  }
  function chooseScenario(scenario: Scenario) {
    if (mutation.current) return
    changeActor(scenario.actor); setInput(scenario.prompt); setChatOpen(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }
  function newSession() {
    if (mutation.current) return
    setSession(crypto.randomUUID()); setMessages([]); setRuns([]); setInput(''); pending.current = null
    flash('Đã mở phiên demo trống cho vai trò hiện tại.')
  }
  async function submitText(text: string, requestId?: string) {
    text = text.trim()
    if (!text || mutation.current) return
    mutation.current = true; setBusy(true); setInput('')
    setMessages(current => [...current, { role: 'user', text }])
    const attempt = requestId ? { text, request_id: requestId } : pending.current?.text === text ? pending.current : { text, request_id: crypto.randomUUID() }
    pending.current = attempt
    try {
      const result = await request<Run>('/api/runs', { method: 'POST', body: JSON.stringify({
        request_id: attempt.request_id, actor, session_id: session, message: text, context: {},
      }) })
      setRuns(current => [result, ...current])
      setMessages(current => [...current, { role: 'assistant', text: result.llm.message || result.message, result }])
      pending.current = null
    } catch (error) {
      setInput(text)
      setMessages(current => [...current, { role: 'assistant', text: (error as Error).message, error: true, retry: attempt }])
    } finally { mutation.current = false; setBusy(false); setTimeout(() => inputRef.current?.focus(), 0) }
  }
  function send(event: FormEvent) { event.preventDefault(); void submitText(input) }
  function openRun(run: Run) { setChatOpen(false); setSelectedRun(run) }
  function download(run: Run) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `${run.run_id}.json`; link.click(); URL.revokeObjectURL(url)
    flash('Đã tải kết quả JSON của lượt chạy.')
  }
  const shown = scenarios.filter(s => (category === 'Tất cả' || s.category === category) && `${s.title} ${s.reference} ${s.description}`.toLocaleLowerCase('vi').includes(query.toLocaleLowerCase('vi')))
  const artifacts = [...new Map(runs.flatMap(run => run.artifacts.map(artifact => [artifact.draft_id, { artifact, run }] as const))).values()]
  const providerLabel = !health ? 'Chưa kết nối backend' : health.provider === 'gemini' ? `Gemini · ${health.model_id}` : 'Mô phỏng offline · fake'

  return <div className="app-shell travel-app">
    <a className="skip-link" href="#main-content">Đến nội dung chính</a>
    <div className="announcement"><span className="announcement-item">Môi trường training · dữ liệu giả lập</span><span className="announcement-item">Mọi artifact chỉ là bản nháp, chưa gửi ra ngoài</span></div>
    <header className="header wrap">
      <div className="header-left">
        <button className="brand" onClick={() => setPage('demo')} aria-label="Trang chủ Travel Operations"><span className="brand-mark">t.</span><span className="brand-name">travel<span className="brand-light">operations</span></span></button>
        <nav className="main-nav" aria-label="Điều hướng chính">
          <button aria-current={page === 'demo' ? 'page' : undefined} className={page === 'demo' ? 'nav-active' : ''} onClick={() => setPage('demo')}>Tình huống demo</button>
          <button aria-current={page === 'runs' ? 'page' : undefined} className={page === 'runs' ? 'nav-active' : ''} onClick={() => setPage('runs')}>Kết quả ({runs.length})</button>
          <button aria-current={page === 'drafts' ? 'page' : undefined} className={page === 'drafts' ? 'nav-active' : ''} onClick={() => setPage('drafts')}>Bản nháp ({artifacts.length})</button>
        </nav>
      </div>
      <button className="button button-dark header-chat" onClick={() => setChatOpen(true)}><Icon name="chat"/> Mở trợ lý</button>
    </header>
    <div className="wrap actor-bar">
      <label>Vai trò giả lập<select aria-label="Vai trò giả lập" disabled={busy} value={actorKey(actor)} onChange={e => changeActor(actors.find(a => actorKey(a.value) === e.target.value)!.value)}>{actors.map(a => <option key={actorKey(a.value)} value={actorKey(a.value)}>{a.label}</option>)}</select></label>
      <span className="backend-state" role="status">{connecting ? 'Đang kết nối backend…' : providerLabel}</span>
      <button className="text-link" disabled={busy} onClick={newSession}>Phiên mới</button>
    </div>
    {connectionError && <div className="wrap connection-error" role="alert"><span>{connectionError}</span><button className="text-link" disabled={connecting} onClick={() => void checkHealth()}>Kết nối lại</button></div>}
    {notice && <div className="toast-container"><div className="toast toast-notice" role="status">{notice}</div></div>}

    {page === 'demo' && <main id="main-content">
      <section className="hero wrap">
        <div className="hero-copy"><span className="eyebrow">CÔNG TÁC QUỐC TẾ / BẢN DEMO</span><h1>Mỗi chuyến đi,<br/>một kế hoạch <em>rõ ràng.</em></h1>
          <p>Chuẩn bị trước chuyến đi, xử lý gián đoạn và rà soát chi phí. Bắt đầu từ một mã tham chiếu trong bộ dữ liệu training.</p>
          <div className="hero-cta-group"><button className="button button-dark hero-btn" onClick={() => document.getElementById('catalog')?.scrollIntoView({ behavior: 'smooth' })}>Chọn tình huống <Icon name="arrow"/></button><button className="button button-secondary" onClick={() => setChatOpen(true)}><Icon name="chat"/> Hỏi trợ lý</button></div>
          <div className="hero-proof"><span>Dữ kiện từ mock systems</span><span>Policy kèm nguồn trích dẫn</span></div>
        </div>
        <div className="hero-visual demo-visual">
          <div className="travel-ticket"><div className="ticket-heading"><span>TRAVEL OPERATIONS</span><span>TRAINING</span></div><span className="eyebrow">MẪU YÊU CẦU / TRƯỚC CHUYẾN ĐI</span><strong>TRIP-2026-002</strong><p>Tôi cần chuẩn bị gì<br/>cho chuyến công tác này?</p><div className="ticket-divider"/><dl><div><dt>Actor giả lập</dt><dd>EMP-002</dd></div><div><dt>Đầu ra</dt><dd>Checklist draft</dd></div></dl><button className="ticket-action" disabled={busy} onClick={() => chooseScenario(scenarios[0])}>Thử mẫu yêu cầu này <Icon name="arrow"/></button></div>
          <p className="visual-caption">Chọn mẫu để điền tin nhắn. Kết quả chỉ xuất hiện sau khi gửi tới backend.</p>
        </div>
      </section>
      <section className="benefits wrap" aria-label="Ba giai đoạn công tác">{[['01', 'Trước chuyến đi', 'Yêu cầu, approval và checklist'], ['02', 'Trong chuyến đi', 'Itinerary, delay và chuyển cấp'], ['03', 'Sau chuyến đi', 'Chi phí, chứng từ và review draft']].map(([n, title, description]) => <div key={n}><span className="stage-number">{n}</span><div><b>{title}</b><small>{description}</small></div></div>)}</section>
      <section id="catalog" className="catalog wrap">
        <div className="section-heading"><div><span className="eyebrow">CHỌN MỘT ĐIỂM BẮT ĐẦU</span><h2>Tình huống demo</h2></div><span className="product-count">{shown.length} tình huống</span></div>
        <div className="catalog-toolbar"><div className="category-tabs">{['Tất cả', 'Trước chuyến đi', 'Trong chuyến đi', 'Sau chuyến đi'].map(c => <button key={c} aria-pressed={category === c} className={category === c ? 'category-active' : ''} onClick={() => setCategory(c)}>{c}</button>)}</div>
          <label className="header-search scenario-search"><Icon name="search"/><input aria-label="Tìm tình huống" placeholder="Tên tình huống hoặc mã…" value={query} onChange={e => setQuery(e.target.value)}/>{query && <button aria-label="Xóa tìm kiếm" onClick={() => setQuery('')}><Icon name="close"/></button>}</label>
        </div>
        {shown.length ? <div className="product-grid scenario-grid">{shown.map(s => <button key={s.id} className="product-card scenario-card" disabled={busy} onClick={() => chooseScenario(s)}>
          <div className={`product-image scenario-visual stage-${s.id}`}><span className="scenario-label">{s.label}</span><strong>{s.reference}</strong><span className="scenario-actor">{s.actor.actor_id} · {s.actor.role === 'employee' ? 'Employee' : 'Reviewer'}</span></div>
          <div className="product-info"><span className="product-category">{s.category}</span><h3>{s.title}</h3><p>{s.description}</p><span className="text-link">Mở mẫu yêu cầu <Icon name="arrow"/></span></div>
        </button>)}</div> : <div className="empty-state"><h3>Không tìm thấy tình huống</h3><p>Thử tên khác hoặc xóa bộ lọc.</p><button className="button button-dark" onClick={() => { setQuery(''); setCategory('Tất cả') }}>Xóa bộ lọc</button></div>}
      </section>
    </main>}

    {page === 'runs' && <main id="main-content" className="wrap history-page"><span className="eyebrow">PHIÊN HIỆN TẠI / {actor.actor_id}</span><h1>Kết quả xử lý</h1><p className="page-description">Các lượt chạy trong tab này. Mở chi tiết để xem dữ kiện, nguồn và trace.</p>
      {runs.length ? <div className="run-list">{runs.map((run, i) => <article className="run-row" key={`${run.run_id}-${i}`}><div><span className="eyebrow">{workflowLabels[run.workflow] || run.workflow}</span><h3>{run.message}</h3><small>{run.run_id}</small></div><Status value={run.status}/><div className="run-actions"><button className="button button-secondary" onClick={() => setSelectedRun(run)}>Chi tiết</button><button className="text-link" onClick={() => download(run)}>Tải JSON</button></div></article>)}</div> : <div className="empty-state"><h3>Chưa có lượt chạy nào</h3><p>Gửi một yêu cầu để xem kết quả ở đây.</p><button className="button button-dark" onClick={() => { setPage('demo'); setChatOpen(true) }}>Gửi yêu cầu đầu tiên</button></div>}
    </main>}

    {page === 'drafts' && <main id="main-content" className="wrap history-page"><span className="eyebrow">SANDBOX / CHƯA GỬI</span><h1>Bản nháp</h1><p className="page-description">Mã và trạng thái checklist, support note, expense review từ workflow. API hiện chưa trả toàn bộ nội dung bản nháp.</p>
      {artifacts.length ? <div className="artifact-grid">{artifacts.map(({ artifact, run }) => <ArtifactCard key={artifact.draft_id} artifact={artifact} onOpen={() => setSelectedRun(run)}/>)}</div> : <div className="empty-state"><h3>Chưa có bản nháp</h3><p>Bản nháp sẽ xuất hiện khi workflow trả về artifact.</p><button className="button button-dark" onClick={() => setPage('demo')}>Chọn tình huống demo</button></div>}
    </main>}

    <footer className="footer"><div className="wrap footer-inner"><button className="brand footer-brand" onClick={() => setPage('demo')}><span className="brand-mark">t.</span><span className="brand-name">travel<span className="brand-light">operations</span></span></button><span className="footer-tagline">Training prototype · Dữ liệu và policy giả lập</span><a className="text-link" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">Tài liệu API</a></div></footer>
    {!chatOpen && <button className="assistant-fab" onClick={() => setChatOpen(true)}><Icon name="chat"/><span>Trợ lý công tác</span></button>}

    {chatOpen && <div className="chat-backdrop overlay" onMouseDown={e => { if (e.target === e.currentTarget) setChatOpen(false) }}>
      <ChatDialog onClose={() => setChatOpen(false)}>
        <div className="chat-head"><div className="assistant-avatar">t.</div><div className="chat-head-info"><b>Trợ lý công tác</b><small>{actor.actor_id} · {health?.provider === 'gemini' ? 'Gemini' : 'Backend training'}</small></div><button className="chat-close-btn" aria-label="Đóng chat" onClick={() => setChatOpen(false)}><Icon name="close"/></button></div>
        <div className="chat-messages" role="log" aria-label="Hội thoại">
          <div className="chat-intro"><span className="eyebrow">TRAVEL OPERATIONS ASSISTANT</span><h3>Mình có thể giúp gì cho bạn?</h3><p>Gửi mã chuyến đi hoặc báo cáo chi phí. Bạn cũng có thể nhờ viết lại một đoạn văn.</p><div className="suggestions"><button disabled={busy} onClick={() => { setInput(`Tôi cần chuẩn bị cho ${actor.actor_id === 'EMP-001' ? 'TRIP-2026-001' : 'TRIP-2026-002'}.`); inputRef.current?.focus() }}>Chuẩn bị công tác</button><button disabled={busy} onClick={() => { setInput('Viết lại chuyên nghiệp: tôi bị trễ chuyến bay, giúp với'); inputRef.current?.focus() }}>Viết lại tin nhắn</button></div></div>
          {messages.map((message, i) => <div key={i} className={`message ${message.role === 'user' ? 'message-user' : ''}`}><span className="message-avatar">{message.role === 'user' ? 'bạn' : 't.'}</span><div className="message-bubble">
            {message.result && <><span className="route-tag">{workflowLabels[message.result.workflow] || message.result.workflow}</span><div className="message-status"><Status value={message.result.status}/></div></>}
            <p role={message.error ? 'alert' : undefined}>{message.text}</p>
            {message.retry && <button className="text-link retry-message" disabled={busy} onClick={() => void submitText(message.retry!.text, message.retry!.request_id)}>Gửi lại yêu cầu</button>}
            {message.result && <>{message.result.llm.status === 'fallback' && <small className="missing-fields-note">Phần trình bày LLM đang fallback; dữ kiện workflow vẫn được giữ.</small>}{message.result.evidence.length > 0 && <EvidenceList run={message.result} onOpen={citation => setSource({ run: message.result!, citation })}/>}
              {message.result.artifacts.map(a => <div className="chat-order-summary" key={a.draft_id}><strong>{artifactLabels[a.artifact_type] || a.artifact_type}</strong><span>{a.draft_id} · {a.delivery_status === 'not_sent' ? 'Chưa gửi' : a.delivery_status}</span></div>)}
              <button className="message-order" onClick={() => openRun(message.result!)}>Xem kết quả và trace <Icon name="arrow"/></button></>}
          </div></div>)}
          {busy && <div className="chat-typing-container" role="status"><span className="message-avatar">t.</span><span className="chat-typing-row"><span className="typing-dots" aria-hidden="true"><span/><span/><span/></span><span className="typing-label">Đang xử lý yêu cầu…</span></span></div>}
          <div ref={messagesEnd}/>
        </div>
        <form className="chat-compose" onSubmit={send}><input ref={inputRef} aria-label="Tin nhắn" aria-describedby="chat-help" maxLength={2000} value={input} onChange={e => setInput(e.target.value)} placeholder="Nhập yêu cầu kèm mã TRIP hoặc EXP…" disabled={busy}/><button type="submit" disabled={busy || !input.trim()} aria-label="Gửi"><Icon name="arrow"/></button></form>
        <div className="chat-footnote" id="chat-help">Mỗi yêu cầu cần mã tham chiếu. Đổi vai trò hoặc mở phiên mới sẽ xóa lịch sử trong tab.</div>
      </ChatDialog>
    </div>}
    {selectedRun && <RunDialog run={selectedRun} onClose={() => setSelectedRun(null)} onSource={citation => setSource({ run: selectedRun, citation })}/>}
    {source && <SourceDialog run={source.run} citation={source.citation} onClose={() => setSource(null)}/>}
  </div>
}

function ChatDialog({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  return <Dialog label="Trợ lý công tác" backdrop="chat-dialog-host" className="chat-panel" onClose={onClose}>{children}</Dialog>
}
