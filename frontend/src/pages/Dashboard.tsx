import { Link, useNavigate } from 'react-router'
import { SearchBar } from '../components/SearchBar'
import { StatCard } from '../components/StatCard'
import { ErrorState, LoadingState } from '../components/States'
import { useResource } from '../hooks/useResource'
import { api } from '../services/api'

export function Dashboard() {
  const navigate = useNavigate()
  const { data: stats, loading, error } = useResource(signal => api.stats(signal), [])
  return <>
    <section className="hero">
      <div className="hero-copy"><p className="eyebrow">Scientific publication explorer</p><h1>FSBM Semantic Research</h1>
        <p className="hero-lead">Explore publications from Faculté des Sciences Ben M'Sick through structured research data, zembed-1 abstract embeddings, and cosine semantic search.</p>
        <div className="hero-links"><Link to="/researchers" className="subtle-link">Browse researchers <span aria-hidden="true">↗</span></Link><Link to="/publications" className="subtle-link">Explore publications <span aria-hidden="true">↗</span></Link></div>
      </div>
      <div className="hero-aside"><span className="hero-aside-label">Research corpus</span><strong>Discover work by meaning.</strong><p>Move beyond exact keywords and explore connections across scientific abstracts.</p></div>
    </section>

    <section className="section-block" aria-labelledby="corpus-heading"><div className="section-heading"><div><p className="eyebrow">The dataset</p><h2 id="corpus-heading">A consolidated view of FSBM research</h2></div><p>Counts are loaded from the project API.</p></div>
      {loading ? <LoadingState message="Loading project statistics..." /> : error ? <ErrorState message={error} /> : stats && <div className="stats-grid">
        <StatCard label="Researchers" value={stats.researchers} note="Unique profiles" />
        <StatCard label="Unique publications" value={stats.unique_publications} note="After deduplication" />
        <StatCard label="Indexed publications" value={stats.indexed_publications} note="Semantic search corpus" />
        <StatCard label="Excluded publications" value={stats.excluded_publications} note="Insufficient abstract text" />
      </div>}
    </section>

    <section className="section-block search-feature" aria-labelledby="discover-heading">
      <div className="section-heading"><div><p className="eyebrow">Start exploring</p><h2 id="discover-heading">Semantic search</h2></div><p>Search by a topic or research question. Suggested queries are examples, not dataset categories.</p></div>
      <SearchBar onSearch={query => navigate(`/search?q=${encodeURIComponent(query)}&top_k=5`)} />
      <p className="search-note">Results are ranked by semantic similarity using zembed-1 embeddings and cosine vector search. The first request may take longer while the model loads.</p>
    </section>
  </>
}
