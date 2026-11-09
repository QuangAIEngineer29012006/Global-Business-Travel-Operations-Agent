import { ReactNode, useEffect, useRef } from 'react'

// Open dialogs, innermost last: only the top one reacts to Escape/Tab, and page scroll is restored
// only when the last one closes (stacked dialogs may unmount in any order).
const openDialogs: object[] = []
let pageOverflow = ''

export function Dialog({ label, backdrop, className, onClose, children }: {
  label: string; backdrop: string; className: string; onClose: () => void; children: ReactNode
}) {
  const panel = useRef<HTMLElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    if (!openDialogs.length) pageOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.current?.focus()
    const token = {}
    openDialogs.push(token)
    const handle = (event: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== token) return
      if (event.key === 'Escape') { event.preventDefault(); close.current(); return }
      if (event.key !== 'Tab') return
      const focusable = Array.from(panel.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]'
      ) || []).filter(element => element.getClientRects().length > 0)
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (!first) { event.preventDefault(); return }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', handle)
    return () => {
      openDialogs.splice(openDialogs.indexOf(token), 1)
      if (!openDialogs.length) document.body.style.overflow = pageOverflow
      document.removeEventListener('keydown', handle)
      previous?.focus()
    }
  }, [])
  return <div className={backdrop} onMouseDown={event => { if (event.target === event.currentTarget) close.current() }}>
    <section ref={panel} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} className={className}>{children}</section>
  </div>
}
