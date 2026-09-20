import { useState, type FormEvent } from 'react'
import { Pagination } from '../components/Pagination'
import { PublicationCard } from '../components/PublicationCard'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useResource } from '../hooks/useResource'
import { api } from '../services/api'

const PAGE_SIZE = 20

export function Publications() {
  const [page, setPage] = useState(1)
  const [yearInput, setYearInput] = useState('')
  const [researcherInput, setResearcherInput] = useState('')
  const [filters, setFilters] = useState<{ year?: number; researcher_id?: string }>({})
  const [validation, setValidation] = useState('')
  const { data, loading, error } = useResource(signal => api.publications(page, PAGE_SIZE, filters, signal), [page, filters.year, filters.researcher_id])

  function applyFilters(event: FormEvent) {
    event.preventDefault()
    const year = yearInput.trim()
    if (year && (!/^\d{4}$/.test(year) || Number(year) < 1900 || Number(year) > 2100)) { setValidation('Enter a four-digit year between 1900 and 2100.'); return }
    setValidation('')
    setPage(1)
    setFilters({ year: year ? Number(year) : undefined, researcher_id: researcherInput.trim() || undefined })
  }

  return <div className="page-narrow"><div className="page-heading"><p className="eyebrow">The publication corpus</p><h1>Publications</h1><p>Browse deduplicated publication metadata, abstracts, and available source information.</p></div>
    <form className="filter-panel" onSubmit={applyFilters}><div className="filter-fields"><label htmlFor="year-filter">Publication year<input id="year-filter" inputMode="numeric" placeholder="e.g. 2022" value={yearInput} onChange={event => setYearInput(event.target.value)} /></label>
      <label htmlFor="researcher-id-filter">Researcher Scholar ID<input id="researcher-id-filter" placeholder="Optional" value={researcherInput} onChange={event => setResearcherInput(event.target.value)} /></label>
      <button className="button primary" type="submit">Apply filters</button></div>{validation && <p className="field-error" role="alert">{validation}</p>}</form>
    <div className="list-count"><strong>{data?.total ?? '—'} publications</strong><span>{filters.year || filters.researcher_id ? 'Matching filters' : 'In the consolidated dataset'}</span></div>
    {loading ? <LoadingState message="Loading publications..." /> : error ? <ErrorState message={error} /> : data?.items.length ? <div className="card-list">{data.items.map(publication => <PublicationCard key={publication.article_id} publication={publication} />)}</div> : <EmptyState message="No publications found. Try changing the filters." />}
    {data && !loading && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />}
  </div>
}
