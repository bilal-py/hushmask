import { useRef } from 'react'
import type { FoundEntity } from './api'
import { swatch } from './entities'

/**
 * An editable document with highlighter marks behind the text. A transparent textarea sits on top of a
 * layer that draws the same text with marks; both use the `.doc` metrics, so they line up exactly.
 */
export function HighlightEditor({
  text,
  onChange,
  entities,
  active,
}: {
  text: string
  onChange: (text: string) => void
  entities: FoundEntity[] | null
  active: string | null
}) {
  const backdrop = useRef<HTMLDivElement>(null)
  const pieces: React.ReactNode[] = []
  let pos = 0
  for (const entity of entities ?? []) {
    pieces.push(text.slice(pos, entity.start))
    pieces.push(
      <span
        key={entity.start}
        className="mark"
        data-active={active?.toLowerCase() === entity.token.toLowerCase()}
        style={{ '--swatch': swatch(entity.type) } as React.CSSProperties}
      >
        {text.slice(entity.start, entity.end)}
      </span>,
    )
    pos = entity.end
  }
  pieces.push(text.slice(pos))

  return (
    <div className="relative h-full min-h-[27rem]">
      <div ref={backdrop} aria-hidden className="doc pointer-events-none absolute inset-0 overflow-hidden text-transparent">
        {pieces}
        {/* keeps the layer as tall as the textarea when the text ends with a newline */}
        {'\n '}
      </div>
      <textarea
        value={text}
        onChange={(e) => onChange(e.target.value)}
        onScroll={(e) => {
          if (backdrop.current) backdrop.current.scrollTop = e.currentTarget.scrollTop
        }}
        spellCheck={false}
        aria-label="Text to mask"
        className="doc relative block h-full min-h-[27rem] w-full resize-none bg-transparent text-ink caret-ink outline-none"
      />
    </div>
  )
}
