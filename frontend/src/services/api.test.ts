import { describe, expect, it } from 'vitest'
import { apiUrl } from './api'

describe('API URLs', () => {
  it('uses the configured base and preserves query parameters', () => {
    const url = new URL(apiUrl('/search', { q: 'medical diagnosis', top_k: 5 }))
    expect(url.pathname).toBe('/search')
    expect(url.searchParams.get('q')).toBe('medical diagnosis')
    expect(url.searchParams.get('top_k')).toBe('5')
  })
})
