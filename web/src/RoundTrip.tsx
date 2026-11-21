import { useEffect, useState } from 'react'
import { api, type AppView, type Info, type RoundTrip } from './api'
import { describeCounts } from './entities'
import { inputClass, usePersistentState } from './lib'
import { Button, ErrorText, Field, MaskedText, Pane } from './ui'

/** Send the playground text through a real app and show each stage of the trip. */
export function RoundTripPanel({ info, text }: { info: Info; text: string }) {
  const [apps, setApps] = useState<AppView[] | null>(null)
  const [appName, setAppName] = usePersistentState('rt-app', '')
  const [model, setModel] = usePersistentState('rt-model', 'qwen2.5:7b')
  const [instruction, setInstruction] = usePersistentState(
    'rt-instruction',
    'List each transaction with its date, who it was with, the amount and a spending category.',
  )
  const [apiKey, setApiKey] = useState('')
  const [result, setResult] = useState<RoundTrip | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [active, setActive] = useState<string | null>(null)

  useEffect(() => {
    api.apps().then(setApps, (err) => setError(String(err)))
  }, [])

  const selected = apps?.find((a) => a.name === appName) ?? apps?.[0]

  const send = async () => {
    if (!selected) return
    setSending(true)
    setError(null)
    try {
      setResult(
        await api.roundTrip({
          app: selected.name,
          model,
          text,
          instruction,
          ...(info.mode === 'passthrough' && apiKey ? { api_key: apiKey } : {}),
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="space-y-5 border-t border-line pt-10">
      <div className="max-w-2xl">
        <h2 className="text-2xl font-bold tracking-tight">Send it to an AI</h2>
        <p className="mt-2 text-ink-soft">
          Runs the text above through one of your apps, the same way a real request would go, and shows what left
          this machine, what came back, and what you get.
        </p>
      </div>

      {apps && apps.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line px-4 py-6 text-sm">
          Add an app first. It tells hushmask which AI provider to use.{' '}
          <a href="#/apps" className="font-medium underline">
            Go to Apps
          </a>
        </p>
      ) : (
        <div className="grid items-end gap-4 md:grid-cols-[minmax(10rem,14rem)_minmax(10rem,14rem)_1fr_auto]">
          <Field label="App">
            <select
              className={inputClass}
              value={selected?.name ?? ''}
              onChange={(e) => setAppName(e.target.value)}
              disabled={!apps}
            >
              {apps?.map((a) => (
                <option key={a.name} value={a.name}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Model">
            <input className={inputClass} value={model} onChange={(e) => setModel(e.target.value)} />
          </Field>
          <Field label="Instruction">
            <input className={inputClass} value={instruction} onChange={(e) => setInstruction(e.target.value)} />
          </Field>
          <Button variant="primary" onClick={send} disabled={!selected || sending || !text.trim() || !model.trim()}>
            {sending ? 'Waiting for the AI…' : 'Send through hushmask'}
          </Button>
          {info.mode === 'passthrough' && (
            <Field label="Provider API key" hint="Used for this request only, never saved. Leave empty for Ollama.">
              <input
                type="password"
                className={inputClass}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                autoComplete="off"
              />
            </Field>
          )}
        </div>
      )}

      {selected && !selected.api_key_ready && selected.upstream_api_key_env && (
        <p className="text-sm text-danger">
          {selected.upstream_api_key_env} isn't set where hushmask runs, so the provider will likely refuse the request.
        </p>
      )}
      {error && <ErrorText>{error}</ErrorText>}

      {result && !result.ok && (
        <div className="rounded-lg border border-danger/40 bg-surface p-4 text-sm">
          <p className="font-medium text-danger">The request failed with status {result.status}.</p>
          <pre className="mt-2 overflow-auto font-mono text-[0.8125rem] whitespace-pre-wrap text-ink-soft">
            {result.error}
          </pre>
        </div>
      )}

      {result && result.ok && (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <Pane title="What left this machine">
              <div className="doc max-h-[28rem] overflow-auto">
                {result.sent_messages.map((m, i) => (
                  <div key={i} className="mb-3">
                    <span className="font-sans text-xs text-ink-soft">{m.role === 'system' ? 'instruction' : 'text'}</span>
                    <div>
                      <MaskedText text={m.content} active={active} onActive={setActive} />
                    </div>
                  </div>
                ))}
              </div>
            </Pane>
            <Pane title="What the AI answered">
              <div className="doc max-h-[28rem] overflow-auto">
                <MaskedText text={result.masked_answer} active={active} onActive={setActive} />
              </div>
            </Pane>
            <Pane title="What you get back">
              <div className="doc max-h-[28rem] overflow-auto">{result.restored_answer}</div>
            </Pane>
          </div>
          <p className="text-sm">
            Hid {describeCounts(result.masked_counts) || 'nothing'}.{' '}
            <span className="text-ink-soft">Round trip took {(result.took_ms / 1000).toFixed(1)} s.</span>
            {result.unknown_tokens.length > 0 && (
              <span className="block text-danger">
                The AI wrote {result.unknown_tokens.length} placeholder
                {result.unknown_tokens.length === 1 ? '' : 's'} that hushmask never sent (
                {result.unknown_tokens.join(', ')}). They were left as they are.
              </span>
            )}
          </p>
        </>
      )}
    </section>
  )
}
