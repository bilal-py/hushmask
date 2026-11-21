import { useEffect, useState } from 'react'

export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const saved = localStorage.getItem(`hushmask:${key}`)
      return saved === null ? initial : (JSON.parse(saved) as T)
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(`hushmask:${key}`, JSON.stringify(value))
    } catch {
      // Private window or blocked storage: the page still works, it just won't remember.
    }
  }, [key, value])
  return [value, setValue] as const
}

export const inputClass =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm placeholder:text-ink-soft/70 focus:border-ink-soft'
