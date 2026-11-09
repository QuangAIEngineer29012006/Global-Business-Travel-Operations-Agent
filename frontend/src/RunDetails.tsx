import { useState } from 'react'
import { Dialog } from './Dialog'
import { Artifact, Citation, Run, artifactLabels, statusLabels, workflowLabels } from './types'

export function Status({ value }: { value: string }) {
  const tone = value === 'completed' ? 'ok' : ['rejected', 'failed_validation', 'failed_delivery'].includes(value) ? 'deny' : 'warn'
  return <span className={`knowledge-status knowledge-${tone}`}>{statusLabels[value] || value}</span>
}

function policyText(run: Run, citation: Citation) {
  for (const artifact of run.artifacts) {
    const content = artifact.content || {}
    for (const field of ['policy_guidance', 'policy_notes']) {
      const entries = content[field]
      if (Array.isArray(entries)) for (const entry of entries) {
        if (entry && typeof entry === 'object' && entry.citation?.chunk_id === citation.chunk_id && typeof entry.text === 'string') return entry.text
      }
    }
  }
  return null
}

export function EvidenceList({ run, onOpen }: { run: Run; onOpen: (citation: Citation) => void }) {
  return <ol className="citation-list" aria-label="Nguồn trích dẫn">
    {run.evidence.map((citation, i) => <li key={`${citation.chunk_id}-${i}`}>
      <button className="citation-item-btn" onClick={() => onOpen(citation)}>
        <span className="citation-title"><b>{citation.section || citation.doc_id}</b></span>
        <span className="citation-meta">{citation.chunk_id} · {citation.doc_id} · v{citation.version}</span>
      </button>
    </li>)}
  </ol>
}

export function SourceDialog({ run, citation, onClose }: { run: Run; citation: Citation; onClose: () => void }) {
  const text = policyText(run, citation)
  return <Dialog label="Nguồn trích dẫn" backdrop="overlay" className="source-modal" onClose={onClose}>
    <button className="modal-close" aria-label="Đóng nguồn" onClick={onClose}>×</button>
    <div className="source-header"><span className="eyebrow">{citation.doc_id} · v{citation.version}</span><h2>{citation.section}</h2></div>
    <div className="source-card"><p className="source-text">{text || 'Response hiện tại chỉ có metadata nguồn, chưa có nội dung đoạn trích.'}</p></div>
    <p className="source-path">{citation.source} · {citation.chunk_id}</p>
  </Dialog>
}

export function ArtifactCard({ artifact, onOpen }: { artifact: Artifact; onOpen: () => void }) {
  return <button className="artifact-card" onClick={onOpen}>
    <span className="eyebrow">{artifactLabels[artifact.artifact_type] || artifact.artifact_type}</span>
    <strong>{artifact.draft_id}</strong>
    <span>Bản nháp · {artifact.delivery_status === 'not_sent' ? 'Chưa gửi' : artifact.delivery_status}</span>
    <span className="artifact-source">{artifact.source_ids?.length ? `Nguồn: ${artifact.source_ids.join(', ')}` : 'API hiện trả mã và trạng thái bản nháp.'}</span>
    <span className="text-link">Xem thông tin</span>
  </button>
}

export function RunDialog({ run, onClose, onSource }: { run: Run; onClose: () => void; onSource: (citation: Citation) => void }) {
  const [tab, setTab] = useState('summary')
  return <Dialog label="Chi tiết kết quả" backdrop="overlay" className="run-modal" onClose={onClose}>
    <button className="modal-close" aria-label="Đóng kết quả" onClick={onClose}>×</button>
    <span className="eyebrow">{workflowLabels[run.workflow] || run.workflow}</span>
    <h2>Kết quả xử lý</h2><Status value={run.status}/>
    <nav className="detail-tabs" aria-label="Nội dung kết quả">
      {[['summary', 'Tổng quan'], ['sources', `Nguồn (${run.evidence.length})`], ['trace', 'Trace']].map(([key, label]) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}
    </nav>
    {tab === 'summary' && <div className="detail-body"><p>{run.llm.message || run.message}</p>
      {run.next_action && <p className="next-action"><b>Bước tiếp theo:</b> {run.next_action}</p>}
      <dl className="run-metrics"><div><dt>Model</dt><dd>{run.llm.provider_model}</dd></div><div><dt>Token vào / ra</dt><dd>{run.llm.input_tokens ?? '–'} / {run.llm.output_tokens ?? '–'}</dd></div><div><dt>Lượt tool</dt><dd>{run.steps}</dd></div><div><dt>Trình bày LLM</dt><dd>{run.llm.status}</dd></div></dl>
      {run.llm.status === 'fallback' && <p className="inline-error">LLM chưa trình bày được. Kết quả workflow vẫn được giữ nguyên. {run.llm.error_code}</p>}
      <details><summary>Dữ kiện và bản nháp từ workflow</summary><pre>{JSON.stringify({ data: run.data, artifacts: run.artifacts }, null, 2)}</pre></details>
      <small className="run-id">{run.run_id} · {run.reason_code}</small>
    </div>}
    {tab === 'sources' && <div className="detail-body">{run.evidence.length ? <EvidenceList run={run} onOpen={onSource}/> : <p>Yêu cầu này không có trích dẫn policy.</p>}</div>}
    {tab === 'trace' && <div className="detail-body"><ol className="trace-list">{run.trace.map((step, i) => <li key={`${step.trace_id}-${i}`}><b>{step.action}</b><span>{step.phase} · {step.observation_status}</span><small>{step.transition}</small></li>)}</ol></div>}
  </Dialog>
}
