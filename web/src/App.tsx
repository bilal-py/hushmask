import { useEffect, useState } from 'react'
import { api, type Info } from './api'
import { Apps } from './Apps'
import { Playground } from './Playground'

type Page = 'playground' | 'apps'

function pageFromHash(): Page {
  return window.location.hash === '#/apps' ? 'apps' : 'playground'
}

export function App() {
  const [page, setPage] = useState<Page>(pageFromHash)
  const [info, setInfo] = useState<Info | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onHash = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    api.info().then(setInfo, (err) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
          <a href="#/" className="flex items-center gap-2.5 text-lg font-bold tracking-tight">
            <Logo />
            hushmask
          </a>
          <nav className="flex gap-1 text-sm">
            {(
              [
                ['playground', 'Playground', '#/'],
                ['apps', 'Apps', '#/apps'],
              ] as const
            ).map(([id, label, href]) => (
              <a
                key={id}
                href={href}
                aria-current={page === id ? 'page' : undefined}
                className={`rounded-md px-3 py-1.5 ${page === id ? 'bg-paper font-medium' : 'text-ink-soft hover:text-ink'}`}
              >
                {label}
              </a>
            ))}
          </nav>
          {info && <ModeNote info={info} />}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        {error && (
          <div role="alert" className="max-w-xl">
            <h1 className="text-2xl font-bold">Can't reach hushmask</h1>
            <p className="mt-2 text-ink-soft">
              The dashboard talks to <code className="font-mono">hushmask serve</code> on this machine. Start it and
              reload this page. ({error})
            </p>
          </div>
        )}
        {info && (page === 'apps' ? <Apps info={info} /> : <Playground info={info} />)}
      </main>
    </div>
  )
}

function ModeNote({ info }: { info: Info }) {
  const text = {
    apps: 'Apps saved on this machine',
    config: 'Apps from a config file',
    passthrough: 'Forwarding to one provider',
  }[info.mode]
  return <p className="ml-auto text-sm text-ink-soft">{text}</p>
}

function Logo() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
      <rect x="2" y="4" width="20" height="2.5" rx="1.25" fill="var(--ink-soft)" />
      <rect x="2" y="10" width="20" height="4" rx="1" fill="var(--ink)" />
      <rect x="2" y="17.5" width="12" height="2.5" rx="1.25" fill="var(--ink-soft)" />
    </svg>
  )
}
