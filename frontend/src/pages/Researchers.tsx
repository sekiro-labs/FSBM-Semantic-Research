import { useState } from 'react'
import { Pagination } from '../components/Pagination'
import { ResearcherCard } from '../components/ResearcherCard'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useResource } from '../hooks/useResource'
import { api } from '../services/api'

const PAGE_SIZE = 20

export function Researchers() {
  const [page, setPage] = useState(1)
  const [filter, setFilter] = useState('')
  const { data, loading, error } = useResource(signal => api.researchers(page, PAGE_SIZE, signal), [page])
  const visible = data?.items.filter(researcher => `${researcher.full_name || ''} ${researcher.affiliation || ''}`.toLocaleLowerCase().includes(filter.toLocaleLowerCase())) || []
  return <div className="page-narrow"><div className="page-heading"><p className="eyebrow">People behind the publications</p><h1>Researchers</h1><p>Browse the collected FSBM researcher profiles and their available bibliometric information.</p></div>
    <div className="list-toolbar"><div><strong>{data?.total ?? '—'} researchers</strong><span>Profiles in the consolidated dataset</span></div>
      <label className="inline-filter" htmlFor="researcher-filter">Filter this page<input id="researcher-filter" value={filter} onChange={event => setFilter(event.target.value)} placeholder="Name or affiliation" /></label></div>
    {loading ? <LoadingState message="Loading researchers..." /> : error ? <ErrorState message={error} /> : visible.length ? <div className="card-list">{visible.map(researcher => <ResearcherCard key={researcher.scholar_id} researcher={researcher} />)}</div> : <EmptyState message={filter ? 'No researchers match this filter on the current page.' : 'No researchers found.'} />}
    {data && !loading && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />}
  </div>
}
