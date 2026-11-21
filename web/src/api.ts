// Typed client for the hushmask dashboard API. Shapes mirror src/hushmask/proxy/admin.py.

export type Mode = 'apps' | 'config' | 'passthrough'

export interface Upstream {
  label: string
  url: string
  key_env: string
}

export interface Info {
  mode: Mode
  editable: boolean
  store_path: string | null
  ner: { available: boolean; loaded: boolean; model: string }
  presets: Record<string, string[]>
  entity_types: string[]
  upstreams: Upstream[]
}

export interface FoundEntity {
  type: string
  start: number
  end: number
  text: string
  detector: string
  token: string
}

export interface Preview {
  masked: string
  entities: FoundEntity[]
  took_ms: number
}

export interface AppStats {
  requests: number
  masked: Record<string, number>
  blocked_leaks: number
  blocked_unmaskable: number
  unknown_tokens: number
  upstream_errors: number
}

export interface AppView {
  name: string
  key: string | null
  upstream_url: string
  upstream_api_key_env: string | null
  has_stored_api_key: boolean
  api_key_ready: boolean
  preset: string
  known: string[]
  ner: boolean
  allow_images: boolean
  placeholder_note: boolean
  stats: AppStats
}

export interface AppSpec {
  name?: string
  upstream_url?: string
  upstream_api_key?: string | null
  upstream_api_key_env?: string | null
  preset?: string
  known?: string[]
  ner?: boolean
  allow_images?: boolean
  placeholder_note?: boolean
}

export interface ChatMessage {
  role: string
  content: string
}

export type RoundTrip =
  | {
      ok: true
      sent_messages: ChatMessage[]
      masked_answer: string
      restored_answer: string
      masked_counts: Record<string, number>
      unknown_tokens: string[]
      took_ms: number
    }
  | { ok: false; status: number; error: string; took_ms: number }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/hushmask/api${path}`, {
    ...init,
    // The server only answers requests carrying this header, which other websites can't add.
    headers: { 'Content-Type': 'application/json', 'X-Hushmask-Admin': '1', ...init.headers },
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`
    throw new ApiError(response.status, detail)
  }
  return body as T
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: JSON.stringify(body ?? {}) })

export const api = {
  info: () => call<Info>('/info'),
  preview: (text: string, preset: string, known: string[], ner: boolean) =>
    call<Preview>('/preview', json('POST', { text, preset, known, ner })),
  roundTrip: (body: { app: string; model: string; text: string; instruction: string; api_key?: string }) =>
    call<RoundTrip>('/roundtrip', json('POST', body)),
  apps: () => call<AppView[]>('/apps'),
  createApp: (spec: AppSpec) => call<AppView>('/apps', json('POST', spec)),
  updateApp: (name: string, spec: AppSpec) => call<AppView>(`/apps/${name}`, json('PUT', spec)),
  rotateKey: (name: string) => call<AppView>(`/apps/${name}/rotate-key`, json('POST')),
  deleteApp: (name: string) => call<void>(`/apps/${name}`, { method: 'DELETE' }),
}
