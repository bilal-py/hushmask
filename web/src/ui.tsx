import { useId, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { KNOWN_TYPES, swatch, TOKEN_PATTERN, tokenType } from './entities'
import { inputClass } from './lib'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'quiet' | 'danger' }

export function Button({ variant = 'quiet', className = '', ...props }: ButtonProps) {
  const look = {
    primary: 'bg-ink text-paper hover:opacity-90',
    quiet: 'border border-line bg-surface hover:border-ink-soft',
    danger: 'border border-line bg-surface text-danger hover:border-danger',
  }[variant]
  return (
    <button
      className={`inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${look} ${className}`}
      {...props}
    />
  )
}

export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line bg-surface p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={`rounded px-3 py-1.5 text-sm ${
            value === option.value ? 'bg-ink font-medium text-paper' : 'text-ink-soft hover:text-ink'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  hint?: ReactNode
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className={`flex items-start gap-3 ${disabled ? 'opacity-60' : ''}`}>
      <button
        id={id}
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`mt-0.5 h-5 w-9 shrink-0 rounded-full p-0.5 transition-colors ${checked ? 'bg-ink' : 'bg-line'}`}
      >
        <span
          className={`block h-4 w-4 rounded-full bg-surface transition-transform ${checked ? 'translate-x-4' : ''}`}
        />
      </button>
      <label htmlFor={id} className="text-sm">
        <span className="font-medium">{label}</span>
        {hint && <span className="block text-ink-soft">{hint}</span>}
      </label>
    </div>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="font-medium">{label}</span>
      {hint && <span className="mt-0.5 block text-ink-soft">{hint}</span>}
      <span className="mt-1.5 block">{children}</span>
    </label>
  )
}

/** The "always hide" list: values like "PERSON=Lena Hoffmann". */
export function KnownValuesInput({ values, onChange }: { values: string[]; onChange: (values: string[]) => void }) {
  const [type, setType] = useState('PERSON')
  const [draft, setDraft] = useState('')

  const add = () => {
    const value = draft.trim()
    if (!value) return
    const spec = `${type}=${value}`
    if (!values.includes(spec)) onChange([...values, spec])
    setDraft('')
  }

  return (
    <div>
      {values.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-1.5">
          {values.map((spec) => {
            const [kind, ...rest] = spec.split('=')
            const label = KNOWN_TYPES.find(([t]) => t === kind)?.[1] ?? kind
            return (
              <li
                key={spec}
                className="inline-flex items-center gap-2 rounded-md border border-line bg-surface py-1 pr-1 pl-2 text-sm"
              >
                <span aria-hidden className="h-3 w-3 rounded-sm" style={{ background: swatch(kind) }} />
                <span className="sr-only">{label}:</span>
                <span>{rest.join('=')}</span>
                <button
                  onClick={() => onChange(values.filter((v) => v !== spec))}
                  aria-label={`Stop always hiding ${rest.join('=')}`}
                  className="rounded px-1.5 text-ink-soft hover:bg-paper hover:text-ink"
                >
                  ×
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <div className="flex gap-2">
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          aria-label="Kind of value"
          className={`${inputClass} w-auto`}
        >
          {KNOWN_TYPES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          placeholder="e.g. your full name"
          aria-label="Value to always hide"
          className={inputClass}
        />
        <Button onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  )
}

export function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="text-sm">
      <span className="font-medium">{label}</span>
      <div className="mt-1 flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md border border-line bg-paper px-3 py-2 font-mono text-[0.8125rem]">
          {value}
        </code>
        <Button
          onClick={async () => {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
    </div>
  )
}

/** Text with each token drawn as redaction tape. */
export function MaskedText({
  text,
  active,
  onActive,
}: {
  text: string
  active?: string | null
  onActive?: (token: string | null) => void
}) {
  const parts = text.split(TOKEN_PATTERN)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span
            key={i}
            className="tape"
            data-active={active?.toLowerCase() === part.toLowerCase()}
            style={{ '--swatch': swatch(tokenType(part)) } as React.CSSProperties}
            onMouseEnter={() => onActive?.(part)}
            onMouseLeave={() => onActive?.(null)}
          >
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}

export function Pane({ title, dim, children }: { title: string; dim?: boolean; children: ReactNode }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-line bg-surface">
      <h2 className="border-b border-line px-4 py-2 text-sm font-medium text-ink-soft">{title}</h2>
      <div className={`flex-1 transition-opacity ${dim ? 'opacity-60' : ''}`}>{children}</div>
    </div>
  )
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-sm text-danger">
      {children}
    </p>
  )
}
