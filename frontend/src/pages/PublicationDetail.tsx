import { Link, useParams } from 'react-router'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useResource } from '../hooks/useResource'
import { api } from '../services/api'

function safeHttpUrl(value: string | null): string | null {
  return value && /^https?:\/\//i.test(value) ? value : null
}

export function PublicationDetail() {
  const { id = '' } = useParams()
  const { data: publication, loading, error } = useResource(signal => api.publication(id, signal), [id])
  return <div className="page-narrow"><Link to="/publications" className="back-link">← All publications</Link>
    {loading ? <LoadingState message="Loading publication..." /> : error ? <ErrorState message={error} /> : publication ? <article>
      <header className="detail-header"><p className="eyebrow">Publication detail</p><h1>{publication.title || 'Untitled publication'}</h1>
        <div className="metadata-line">{(publication.publication_year ?? publication.publication_date) && <span>{publication.publication_year ?? publication.publication_date}</span>}{publication.journal && <span>{publication.journal}</span>}</div>
        {!!publication.authors?.length && <p className="detail-lead">{publication.authors.join(', ')}</p>}</header>
      <div className="detail-grid"><section className="card detail-panel"><h2>Researcher</h2>{publication.researcher_name ? <p>{publication.researcher_id ? <Link to={`/researchers/${encodeURIComponent(publication.researcher_id)}`}>{publication.researcher_name}</Link> : publication.researcher_name}</p> : <p>Not available</p>}</section>
        <section className="card detail-panel"><h2>Publication facts</h2><dl className="fact-grid">
          <div><dt>Citations</dt><dd>{publication.citations ?? 'Not available'}</dd></div>
          <div><dt>Volume</dt><dd>{publication.volume || 'Not available'}</dd></div>
          <div><dt>Pages</dt><dd>{publication.pages || 'Not available'}</dd></div>
          <div><dt>Publisher</dt><dd>{publication.publisher || 'Not available'}</dd></div>
        </dl></section></div>
      <section className="card abstract-section"><h2>Abstract</h2>{publication.abstract?.trim() ? <p>{publication.abstract}</p> : <EmptyState message="No abstract was collected for this publication." />}</section>
      {(safeHttpUrl(publication.publication_url) || safeHttpUrl(publication.pdf_url)) && <section className="card links-section"><h2>Available sources</h2>
        {safeHttpUrl(publication.publication_url) && <a href={publication.publication_url!} target="_blank" rel="noopener noreferrer">Publication page ↗</a>}
        {safeHttpUrl(publication.pdf_url) && <a href={publication.pdf_url!} target="_blank" rel="noopener noreferrer">Open PDF ↗</a>}</section>}
      {!!publication.references?.length && <section className="card references-section"><h2>References</h2><ul>{publication.references.map((reference, index) => <li key={index}>{reference}</li>)}</ul></section>}
    </article> : <EmptyState message="Publication not found." />}
  </div>
}
