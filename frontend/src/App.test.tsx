import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'
import { api } from './services/api'

vi.mock('./services/api', () => ({
  api: {
    stats: vi.fn(), researchers: vi.fn(), researcher: vi.fn(),
    publications: vi.fn(), publication: vi.fn(), search: vi.fn(),
  },
}))

beforeEach(() => {
  window.history.pushState({}, '', '/')
  vi.mocked(api.stats).mockResolvedValue({
    researchers: 77, raw_publications: 1044, unique_publications: 959,
    embedding_eligible: 895, excluded_publications: 64, indexed_publications: 895,
  })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('application routes and states', () => {
  it('shows real dashboard statistics and navigation', async () => {
    render(<App />)
    expect(await screen.findByText('959')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Researchers' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Semantic Search' })).toBeTruthy()
    expect(api.search).not.toHaveBeenCalled()
  })

  it('does not search until submitted, then shows loading and empty states', async () => {
    window.history.pushState({}, '', '/search')
    let finish!: (value: Awaited<ReturnType<typeof api.search>>) => void
    vi.mocked(api.search).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    render(<App />)
    expect(api.search).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Medical image analysis' }))
    await waitFor(() => expect(api.search).toHaveBeenCalled())
    expect(screen.getByText(/Loading semantic model and searching publications/)).toBeTruthy()
    finish({ query: 'Medical image analysis', top_k: 5, results: [] })
    expect(await screen.findByText(/No publications matched this query/)).toBeTruthy()
  })

  it('shows a search API error without fabricating results', async () => {
    window.history.pushState({}, '', '/search?q=water&top_k=5')
    vi.mocked(api.search).mockRejectedValue(new Error('Semantic search unavailable'))
    render(<App />)
    expect(await screen.findByText('Semantic search unavailable')).toBeTruthy()
  })

  it('renders empty researcher and publication pages', async () => {
    vi.mocked(api.researchers).mockResolvedValue({ page: 1, page_size: 20, total: 0, items: [] })
    vi.mocked(api.publications).mockResolvedValue({ page: 1, page_size: 20, total: 0, items: [] })
    window.history.pushState({}, '', '/researchers')
    const view = render(<App />)
    expect(await screen.findByText('No researchers found.')).toBeTruthy()
    view.unmount()
    window.history.pushState({}, '', '/publications')
    render(<App />)
    expect(await screen.findByText('No publications found. Try changing the filters.')).toBeTruthy()
  })
})
