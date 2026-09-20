import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { Pagination } from '../components/Pagination'
import { PublicationCard } from '../components/PublicationCard'
import { interestsText } from '../components/ResearcherCard'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useResource } from '../hooks/useResource'
import { api } from '../services/api'

export function ResearcherDetail() {
  const { id = '' } = useParams()
  const [page, setPage] = useState(1)
  const profile = useResource(signal => api.researcher(id, signal), [id])
  const publications = useResource(signal => api.publications(page, 10, { researcher_id: id }, signal), [id, page])
  const researcher = profile.data
  return <div className="page-narrow"><Link to="/researchers" className="back-link">← All researchers</Link>
    {profile.loading ? <LoadingState message="Loading researcher profile..." /> : profile.error ? <ErrorState message={profile.error} /> : researcher && <>
      <div className="detail-header"><p className="eyebrow">Researcher profile</p><h1>{researcher.full_name || 'Unnamed researcher'}</h1>{researcher.affiliation && <p className="detail-lead">{researcher.affiliation}</p>}</div>
      <div className="detail-grid"><section className="card detail-panel"><h2>Research interests</h2><p>{interestsText(researcher.research_interests) || 'Not available'}</p></section>
        <section className="card detail-panel"><h2>Scholar metrics</h2><dl className="fact-grid"><div><dt>Total citations</dt><dd>{researcher.total_citations?.toLocaleString() ?? 'Not available'}</dd></div><div><dt>h-index</dt><dd>{researcher.h_index ?? 'Not available'}</dd></div><div><dt>i10-index</dt><dd>{researcher.i10_index ?? 'Not available'}</dd></div></dl></section></div>
      <section className="section-block"><div className="section-heading"><div><p className="eyebrow">From this profile</p><h2>Associated publications</h2></div><span>{publications.data?.total ?? researcher.publications.length} records</span></div>
        {publications.loading ? <LoadingState message="Loading associated publications..." /> : publications.error ? <ErrorState message={publications.error} /> : publications.data?.items.length ? <div className="card-list">{publications.data.items.map(publication => <PublicationCard key={publication.article_id} publication={publication} />)}</div> : <EmptyState message="No associated publications found." />}
        {publications.data && <Pagination page={page} pageSize={10} total={publications.data.total} onPageChange={setPage} />}</section>
    </>}
  </div>
}
