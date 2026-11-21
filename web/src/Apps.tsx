import { useCallback, useEffect, useState } from 'react'
import { api, type AppView, type Info } from './api'
import { AppForm } from './AppForm'
import { describeCounts } from './entities'
import { Button, CopyField, ErrorText } from './ui'

export function Apps({ info }: { info: Info }) {
  const [apps, setApps] = useState<AppView[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const baseUrl = `${window.location.origin}/v1`

  const load = useCallback(() => {
    api.apps().then(setApps, (err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 5000) // stats change as apps send requests
    return () => clearInterval(timer)
  }, [load])

  const replace = (app: AppView) => setApps((list) => (list ?? []).map((a) => (a.name === app.name ? app : a)))

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-bold tracking-tight">Apps</h1>
          <p className="mt-2 text-ink-soft">
            Each app talks to hushmask with its own key instead of the provider's, and gets its own rules. In the
            app, set the base URL to <code className="font-mono text-ink">{baseUrl}</code>.
          </p>
        </div>
        {info.editable && !adding && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            Add app
          </Button>
        )}
      </div>

      {info.mode === 'config' && (
        <p className="rounded-lg border border-line bg-surface px-4 py-3 text-sm">
          These apps come from a config file. Edit the file and restart hushmask to change them.
        </p>
      )}
      {info.mode === 'passthrough' && (
        <p className="rounded-lg border border-line bg-surface px-4 py-3 text-sm">
          hushmask was started with <code className="font-mono">--upstream</code>, so it forwards every request to one
          provider with the caller's own key. Start it without <code className="font-mono">--upstream</code> to manage
          apps here.
        </p>
      )}
      {error && <ErrorText>{error}</ErrorText>}

      {adding && (
        <section className="rounded-lg border border-ink-soft bg-surface p-5">
          <h2 className="mb-5 text-lg font-bold">New app</h2>
          <AppForm
            info={info}
            onCancel={() => setAdding(false)}
            onSaved={(app) => {
              setApps((list) => [...(list ?? []), app].sort((a, b) => a.name.localeCompare(b.name)))
              setAdding(false)
              setOpen(app.name)
            }}
          />
        </section>
      )}

      {apps && apps.length === 0 && !adding && (
        <div className="rounded-lg border border-dashed border-line px-5 py-10 text-center">
          <p className="font-medium">No apps yet</p>
          <p className="mt-1 text-sm text-ink-soft">
            Add one for each program that should talk to an AI through hushmask.
          </p>
        </div>
      )}

      {apps && apps.length > 0 && (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {apps.map((app) => (
            <AppRow
              key={app.name}
              app={app}
              info={info}
              baseUrl={baseUrl}
              open={open === app.name}
              onToggle={() => setOpen(open === app.name ? null : app.name)}
              onChanged={replace}
              onDeleted={() => setApps((list) => (list ?? []).filter((a) => a.name !== app.name))}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function AppRow({
  app,
  info,
  baseUrl,
  open,
  onToggle,
  onChanged,
  onDeleted,
}: {
  app: AppView
  info: Info
  baseUrl: string
  open: boolean
  onToggle: () => void
  onChanged: (app: AppView) => void
  onDeleted: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const provider = info.upstreams.find((u) => u.url === app.upstream_url)?.label ?? new URL(app.upstream_url).host
  const hidden = Object.values(app.stats.masked).reduce((a, b) => a + b, 0)
  const problems = app.stats.blocked_leaks + app.stats.blocked_unmaskable + app.stats.upstream_errors

  const act = async (fn: () => Promise<void>) => {
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <li>
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-x-6 gap-y-1 px-5 py-4 text-left hover:bg-paper/60 md:grid-cols-[minmax(8rem,1fr)_minmax(8rem,1fr)_minmax(10rem,1.2fr)_auto]"
      >
        <span className="text-base font-bold">{app.name}</span>
        <span className="text-sm text-ink-soft md:order-none">
          {provider}, {app.preset === 'finance' ? 'Finance' : 'Strict'}
          {app.ner ? ', names model' : ''}
        </span>
        <span className="text-sm">
          {app.stats.requests === 0
            ? 'No requests yet'
            : `${app.stats.requests} ${app.stats.requests === 1 ? 'request' : 'requests'}, ${hidden} values hidden`}
          {problems > 0 && <span className="block text-danger">{problems} refused or failed</span>}
        </span>
        <span className="text-sm text-ink-soft" aria-hidden>
          {open ? 'Close' : 'Open'}
        </span>
        {!app.api_key_ready && app.upstream_api_key_env && (
          <span className="col-span-full text-sm text-danger">
            {app.upstream_api_key_env} isn't set where hushmask runs.
          </span>
        )}
      </button>

      {open && (
        <div className="space-y-6 border-t border-line px-5 py-5">
          {editing ? (
            <AppForm
              info={info}
              app={app}
              onCancel={() => setEditing(false)}
              onSaved={(updated) => {
                onChanged(updated)
                setEditing(false)
              }}
            />
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-2">
                <CopyField label="Base URL for the app" value={baseUrl} />
                {app.key && <CopyField label="API key for the app" value={app.key} />}
              </div>
              <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-ink-soft">Provider</dt>
                  <dd className="font-mono text-[0.8125rem]">{app.upstream_url}</dd>
                </div>
                <div>
                  <dt className="text-ink-soft">Always hidden</dt>
                  <dd>{app.known.length ? app.known.map((k) => k.split('=').slice(1).join('=')).join(', ') : 'Nothing listed'}</dd>
                </div>
                <div>
                  <dt className="text-ink-soft">Hidden so far</dt>
                  <dd>{hidden ? describeCounts(app.stats.masked) : 'Nothing yet'}</dd>
                </div>
                <div>
                  <dt className="text-ink-soft">Refused or failed</dt>
                  <dd>
                    {problems === 0
                      ? 'None'
                      : [
                          app.stats.blocked_leaks && `${app.stats.blocked_leaks} stopped by the leak check`,
                          app.stats.blocked_unmaskable && `${app.stats.blocked_unmaskable} with images or files`,
                          app.stats.upstream_errors && `${app.stats.upstream_errors} provider errors`,
                        ]
                          .filter(Boolean)
                          .join(', ')}
                  </dd>
                </div>
              </dl>
              <p className="text-sm text-ink-soft">Counts reset when hushmask restarts. Values are never recorded.</p>
              {error && <ErrorText>{error}</ErrorText>}
              {info.editable && (
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => setEditing(true)}>Edit</Button>
                  <Button
                    onClick={() =>
                      act(async () => {
                        if (confirm(`Make a new key for ${app.name}? The old key stops working right away.`))
                          onChanged(await api.rotateKey(app.name))
                      })
                    }
                  >
                    Make a new key
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() =>
                      act(async () => {
                        if (confirm(`Delete ${app.name}? Programs using its key will stop working.`)) {
                          await api.deleteApp(app.name)
                          onDeleted()
                        }
                      })
                    }
                  >
                    Delete app
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </li>
  )
}
