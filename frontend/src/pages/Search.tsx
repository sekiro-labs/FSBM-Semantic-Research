import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { SearchBar } from '../components/SearchBar'
import { SearchResultCard } from '../components/SearchResultCard'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { api } from '../services/api'
import type { SearchResponse } from '../types/api'

const choices = [5, 10, 20]

export function Search() {
  const [params, setParams] = useSearchParams()
  const query = params.get('q')?.trim() || ''
  const requestedK = Number(params.get('top_k') || 5)
  const topK = choices.includes(requestedK) ? requestedK : 5
  const [response, setResponse] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!query) { setResponse(null); setLoading(false); setError(null); return }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setResponse(null)
    api.search(query, topK, controller.signal).then(
      result => { if (!controller.signal.aborted) { setResponse(result); setLoading(false) } },
      reason => { if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'Search is unavailable.'); setLoading(false) } },
    )
    return () => controller.abort()
  }, [query, topK])

  return <div className="page-narrow"><div className="page-heading"><p className="eyebrow">Explore by meaning</p><h1>Semantic Search</h1><p>Describe a research topic in natural language. Results reflect the available abstracts and their cosine similarity.</p></div>
    <SearchBar key={query} initialQuery={query} onSearch={next => setParams({ q: next, top_k: String(topK) })} busy={loading} />
    <div className="search-toolbar"><label htmlFor="top-k">Results to show</label><select id="top-k" value={topK} onChange={event => setParams(query ? { q: query, top_k: event.target.value } : { top_k: event.target.value })}>
      {choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}
    </select></div>
    {loading ? <LoadingState message="Loading semantic model and searching publications... The first request may take a while." />
      : error ? <ErrorState message={error} />
      : response ? <section aria-live="polite"><div className="results-heading"><h2>Results for “{response.query}”</h2><span>{response.results.length} shown</span></div>
          {response.results.length ? <div className="result-list">{response.results.map((result, index) => <SearchResultCard key={result.publication_id} result={result} rank={index + 1} />)}</div> : <EmptyState message="No publications matched this query. Try another topic." />}</section>
      : <div className="intro-panel"><strong>Find related publications</strong><p>Enter a topic above or choose an example query to begin. A search is only sent when you submit a query.</p></div>}
    <p className="search-note">Similarity reflects ranking within the current corpus; it does not guarantee that every result is relevant.</p>
  </div>
}
