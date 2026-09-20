import { Link } from 'react-router'
import type { Publication } from '../types/api'

export function PublicationCard({ publication }: { publication: Publication }) {
  const abstract = publication.abstract?.trim()
  return <article className="card publication-card">
    <p className="eyebrow">{publication.publication_year ?? 'Year unavailable'}{publication.journal ? ` · ${publication.journal}` : ''}</p>
    <h3><Link to={`/publications/${encodeURIComponent(publication.article_id)}`}>{publication.title || 'Untitled publication'}</Link></h3>
    <div className="metadata-line">{publication.researcher_name && <span>{publication.researcher_name}</span>}{publication.citations != null && <span>{publication.citations} citations</span>}</div>
    {!!publication.authors?.length && <p className="byline">{publication.authors.join(', ')}</p>}
    {abstract && <p className="abstract-preview clamp">{abstract}</p>}
  </article>
}
