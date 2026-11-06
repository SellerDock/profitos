import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { loadAnalytics } from './analytics'

describe('loadAnalytics', () => {
  let scripts: Array<{ id: string; async: boolean; src: string; dataset: Record<string, string> }>
  beforeEach(() => {
    scripts = []
    vi.stubGlobal('window', {})
    vi.stubGlobal('document', {
      getElementById: (id: string) => scripts.find(script => script.id === id),
      createElement: () => ({ id: '', async: false, src: '', dataset: {} }),
      head: { appendChild: (script: typeof scripts[number]) => scripts.push(script) },
    })
  })
  afterEach(() => vi.unstubAllGlobals())
  it('does nothing without configuration', () => {
    loadAnalytics()
    expect(scripts).toHaveLength(0)
  })
  it('loads and initializes Google Analytics once', () => {
    const config = { ga_id: 'G-ABC123', ahrefs_key: null }
    loadAnalytics(config)
    loadAnalytics(config)
    expect(scripts).toHaveLength(1)
    expect(scripts[0].src).toBe('https://www.googletagmanager.com/gtag/js?id=G-ABC123')
    expect(scripts[0].async).toBe(true)
    expect(Array.from(window.dataLayer![1] as ArrayLike<unknown>)).toEqual(['config', 'G-ABC123'])
  })
  it('loads Ahrefs with its key', () => {
    loadAnalytics({ ga_id: null, ahrefs_key: 'test_key' })
    expect(scripts[0].src).toBe('https://analytics.ahrefs.com/analytics.js')
    expect(scripts[0].dataset.key).toBe('test_key')
    expect(scripts[0].async).toBe(true)
  })
})
