import type {
  PaginatedResponse, Publication, Researcher, ResearcherDetail, SearchResponse, StatsResponse,
} from '../types/api'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export function apiUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const url = new URL(`${API_BASE_URL}${path}`)
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== '') url.searchParams.set(key, String(value))
  }
  return url.toString()
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(apiUrl(path, params), { signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('Unable to connect to the API. Make sure the FastAPI server is running.')
  }
  if (!response.ok) {
    let detail: unknown
    try { detail = (await response.json() as { detail?: unknown }).detail } catch { /* Keep the status message. */ }
    const message = typeof detail === 'string' ? detail : `API request failed (${response.status}).`
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  stats: (signal?: AbortSignal) => get<StatsResponse>('/stats', undefined, signal),
  researchers: (page: number, pageSize = 20, signal?: AbortSignal) =>
    get<PaginatedResponse<Researcher>>('/researchers', { page, page_size: pageSize }, signal),
  researcher: (id: string, signal?: AbortSignal) =>
    get<ResearcherDetail>(`/researchers/${encodeURIComponent(id)}`, undefined, signal),
  publications: (page: number, pageSize = 20, filters?: { year?: number; researcher_id?: string }, signal?: AbortSignal) =>
    get<PaginatedResponse<Publication>>('/publications', { page, page_size: pageSize, ...filters }, signal),
  publication: (id: string, signal?: AbortSignal) =>
    get<Publication>(`/publications/${encodeURIComponent(id)}`, undefined, signal),
  search: (q: string, topK = 5, signal?: AbortSignal) =>
    get<SearchResponse>('/search', { q, top_k: topK }, signal),
}
