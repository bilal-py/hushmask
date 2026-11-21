import { useEffect, useState } from 'react'
import { api, type Info, type Preview } from './api'
import { describeCounts, swatch, typeName } from './entities'
import { HighlightEditor } from './HighlightEditor'
import { RoundTripPanel } from './RoundTrip'
import { usePersistentState } from './lib'
import { ErrorText, KnownValuesInput, MaskedText, Pane, Segmented, Toggle } from './ui'

const SAMPLE = `HDFC BANK statement for Rahul Sharma, A/c No. 50100123456789
12/11/2026  UPI/rahul.sharma@okhdfcbank/SWIGGY         450.00 Dr
13/11/2026  POS 4111 1111 1111 1111 AMAZON PAY       1,299.00 Dr
14/11/2026  NEFT FROM PRIYA MEHTA SALARY            85,000.00 Cr
15/11/2026  IMPS TO AMIT KUMAR RENT NOV             18,000.00 Dr
16/11/2026  STARBUCKS RESERVE                          380.00 Dr

Hi team, please reimburse Neha Gupta (neha@corp.in, +91 98765 43210)
for the Paris trip. Her manager is Dr. Vikram Singh.`

const PRESET_HINTS: Record<string, string> = {
  finance: 'Keeps merchants, amounts and cities, so the AI can still categorize spending.',
  strict: 'Hides every kind of value hushmask can find.',
}

const DETECTOR_NAMES: Record<string, string> = { known: 'your list', gliner: 'names model' }

export function Playground({ info }: { info: Info }) {
  const [text, setText] = usePersistentState('text', SAMPLE)
  const [preset, setPreset] = usePersistentState('preset', 'finance')
  const [known, setKnown] = usePersistentState<string[]>('known', ['PERSON=Rahul Sharma'])
  const [ner, setNer] = usePersistentState('ner', false)
  const [preview, setPreview] = useState<(Preview & { source: string }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [active, setActive] = useState<string | null>(null)
  const useNer = ner && info.ner.available

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(async () => {
      setBusy(true)
      try {
        const result = await api.preview(text, preset, known, useNer)
        if (!cancelled) {
          setPreview({ ...result, source: text })
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setBusy(false)
      }
    }, 300)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [text, preset, known, useNer])

  // Highlights only make sense for the exact text they were computed on.
  const current = preview && preview.source === text ? preview : null
  const counts: Record<string, number> = {}
  for (const e of current?.entities ?? []) counts[e.type] = (counts[e.type] ?? 0) + 1
  const presetNames = Object.keys(info.presets).sort((a) => (a === 'finance' ? -1 : 1))

  return (
    <div className="space-y-10">
      <section className="space-y-6">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-bold tracking-tight">See what the AI gets</h1>
          <p className="mt-2 text-ink-soft">
            Type or paste anything. Highlighted values stay on this machine. The right side is exactly what an AI
            provider would receive.
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[auto_1fr]">
          <div className="space-y-2">
            <Segmented
              label="What to hide"
              options={presetNames.map((p) => ({ value: p, label: p === 'finance' ? 'Finance' : 'Strict' }))}
              value={preset}
              onChange={setPreset}
            />
            <p className="max-w-xs text-sm text-ink-soft">{PRESET_HINTS[preset]}</p>
          </div>
          <div className="grid gap-6 sm:grid-cols-2">
            <div>
              <p className="mb-1.5 text-sm font-medium">Always hide</p>
              <KnownValuesInput values={known} onChange={setKnown} />
            </div>
            <Toggle
              checked={useNer}
              onChange={setNer}
              disabled={!info.ner.available}
              label="Find names nobody listed"
              hint={
                info.ner.available
                  ? info.ner.loaded || !ner
                    ? 'Runs a local model on this machine. Slower, catches third-party names.'
                    : 'Loading the model. The first time takes a few seconds.'
                  : 'Needs the model extra: uv sync --extra ner'
              }
            />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Pane title="Your text">
            <HighlightEditor text={text} onChange={setText} entities={current?.entities ?? null} active={active} />
          </Pane>
          <Pane title="What the AI receives" dim={busy || !current}>
            <div className="doc h-full min-h-[27rem] overflow-auto">
              {current ? <MaskedText text={current.masked} active={active} onActive={setActive} /> : text}
            </div>
          </Pane>
        </div>

        <div className="flex flex-wrap items-baseline justify-between gap-3 text-sm">
          {error ? (
            <ErrorText>{error}</ErrorText>
          ) : current ? (
            <p>
              {current.entities.length === 0
                ? 'Nothing to hide in this text.'
                : `Hiding ${current.entities.length} ${current.entities.length === 1 ? 'value' : 'values'}: ${describeCounts(counts)}.`}{' '}
              <span className="text-ink-soft">Checked in {current.took_ms} ms. Hover a token to find its source.</span>
            </p>
          ) : (
            <p className="text-ink-soft">Checkingâ€¦</p>
          )}
          {text !== SAMPLE && (
            <button className="text-ink-soft underline hover:text-ink" onClick={() => setText(SAMPLE)}>
              Reset to sample
            </button>
          )}
        </div>

        {current && current.entities.length > 0 && (
          <details className="rounded-lg border border-line bg-surface">
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium">What was found, and how</summary>
            <table className="w-full text-left text-sm">
              <thead className="text-ink-soft">
                <tr className="border-t border-line">
                  <th className="px-4 py-2 font-normal">Kind</th>
                  <th className="px-4 py-2 font-normal">Value</th>
                  <th className="px-4 py-2 font-normal">Sent as</th>
                  <th className="px-4 py-2 font-normal">Found by</th>
                </tr>
              </thead>
              <tbody>
                {current.entities.map((e) => (
                  <tr
                    key={e.start}
                    className="border-t border-line hover:bg-paper"
                    onMouseEnter={() => setActive(e.token)}
                    onMouseLeave={() => setActive(null)}
                  >
                    <td className="px-4 py-2">
                      <span className="inline-flex items-center gap-2">
                        <span aria-hidden className="h-3 w-3 rounded-sm" style={{ background: swatch(e.type) }} />
                        {typeName(e.type)}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono text-[0.8125rem]">{e.text}</td>
                    <td className="px-4 py-2 font-mono text-[0.8125rem]">{e.token}</td>
                    <td className="px-4 py-2 text-ink-soft">{DETECTOR_NAMES[e.detector] ?? 'pattern'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </section>

      <RoundTripPanel info={info} text={text} />
    </div>
  )
}
