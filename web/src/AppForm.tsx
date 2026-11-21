import { useState } from 'react'
import { api, type AppSpec, type AppView, type Info } from './api'
import { inputClass } from './lib'
import { Button, ErrorText, Field, KnownValuesInput, Segmented, Toggle } from './ui'

type KeySource = 'env' | 'stored' | 'none'

/** Create a new app, or edit one when `app` is given. */
export function AppForm({
  info,
  app,
  onSaved,
  onCancel,
}: {
  info: Info
  app?: AppView
  onSaved: (app: AppView) => void
  onCancel: () => void
}) {
  const firstUpstream = info.upstreams[0]
  const [name, setName] = useState('')
  const [url, setUrl] = useState(app?.upstream_url ?? firstUpstream.url)
  const [keySource, setKeySource] = useState<KeySource>(
    app ? (app.upstream_api_key_env ? 'env' : app.has_stored_api_key ? 'stored' : 'none') : 'env',
  )
  const [envName, setEnvName] = useState(app?.upstream_api_key_env ?? firstUpstream.key_env)
  const [storedKey, setStoredKey] = useState('')
  const [preset, setPreset] = useState(app?.preset ?? 'finance')
  const [known, setKnown] = useState<string[]>(app?.known ?? [])
  const [ner, setNer] = useState(app?.ner ?? false)
  const [allowImages, setAllowImages] = useState(app?.allow_images ?? false)
  const [note, setNote] = useState(app?.placeholder_note ?? true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const provider = info.upstreams.find((u) => u.url === url.replace(/\/+$/, ''))

  const pickProvider = (value: string) => {
    const choice = info.upstreams.find((u) => u.url === value)
    if (!choice) return
    setUrl(choice.url)
    if (choice.key_env) {
      setKeySource('env')
      setEnvName(choice.key_env)
    } else {
      setKeySource('none')
    }
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    const spec: AppSpec = {
      upstream_url: url,
      upstream_api_key_env: keySource === 'env' ? envName : null,
      preset,
      known,
      ner,
      allow_images: allowImages,
      placeholder_note: note,
    }
    if (keySource === 'stored') {
      if (storedKey) spec.upstream_api_key = storedKey
    } else {
      spec.upstream_api_key = null
    }
    try {
      onSaved(app ? await api.updateApp(app.name, spec) : await api.createApp({ name, ...spec }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault()
        save()
      }}
    >
      <div className="grid gap-5 md:grid-cols-2">
        {!app && (
          <Field label="Name" hint="Lowercase letters, digits and dashes. Part of the app's key.">
            <input
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value.toLowerCase())}
              placeholder="spence"
              required
              autoFocus
            />
          </Field>
        )}
        <Field label="AI provider">
          <select
            className={inputClass}
            value={provider?.url ?? 'other'}
            onChange={(e) => pickProvider(e.target.value)}
          >
            {info.upstreams.map((u) => (
              <option key={u.url} value={u.url}>
                {u.label}
              </option>
            ))}
            <option value="other">Other (OpenAI-compatible)</option>
          </select>
        </Field>
        <Field label="Provider base URL">
          <input className={`${inputClass} font-mono`} value={url} onChange={(e) => setUrl(e.target.value)} required />
        </Field>
      </div>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium">Provider API key</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          {(
            [
              ['env', 'From an environment variable'],
              ['stored', 'Saved in the apps file'],
              ['none', 'No key (e.g. Ollama)'],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="inline-flex items-center gap-2">
              <input
                type="radio"
                name="key-source"
                checked={keySource === value}
                onChange={() => setKeySource(value)}
                className="accent-[var(--ink)]"
              />
              {label}
            </label>
          ))}
        </div>
        {keySource === 'env' && (
          <input
            className={`${inputClass} max-w-sm font-mono`}
            value={envName}
            onChange={(e) => setEnvName(e.target.value)}
            aria-label="Environment variable name"
            placeholder="GEMINI_API_KEY"
            required
          />
        )}
        {keySource === 'stored' && (
          <div className="max-w-sm space-y-1">
            <input
              type="password"
              className={inputClass}
              value={storedKey}
              onChange={(e) => setStoredKey(e.target.value)}
              aria-label="API key"
              placeholder={app?.has_stored_api_key ? 'Saved. Type to replace it.' : 'Paste the key'}
              required={!app?.has_stored_api_key}
              autoComplete="off"
            />
            <p className="text-sm text-ink-soft">
              Stored as plain text in {info.store_path ?? 'the apps file'}. An environment variable is safer.
            </p>
          </div>
        )}
      </fieldset>

      <div className="space-y-2">
        <p className="text-sm font-medium">What to hide</p>
        <Segmented
          label="What to hide"
          options={[
            { value: 'finance', label: 'Finance' },
            { value: 'strict', label: 'Strict' },
          ]}
          value={preset}
          onChange={setPreset}
        />
      </div>

      <div>
        <p className="mb-1.5 text-sm font-medium">Always hide</p>
        <KnownValuesInput values={known} onChange={setKnown} />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Toggle
          checked={ner}
          onChange={setNer}
          disabled={!info.ner.available}
          label="Find names nobody listed"
          hint={info.ner.available ? 'Local model, adds a moment per request.' : 'Needs: uv sync --extra ner'}
        />
        <Toggle
          checked={allowImages}
          onChange={setAllowImages}
          label="Send images unmasked"
          hint="Images can't be masked. Off means they're refused."
        />
        <Toggle
          checked={note}
          onChange={setNote}
          label="Explain placeholders to the AI"
          hint="A short instruction to copy them exactly."
        />
      </div>

      {error && <ErrorText>{error}</ErrorText>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={saving}>
          {app ? 'Save changes' : 'Create app'}
        </Button>
        <Button type="button" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
