import { Link } from 'react-router'
import type { Researcher } from '../types/api'

export function interestsText(value: Researcher['research_interests']): string | null {
  if (Array.isArray(value)) return value.length ? value.join(' · ') : null
  return value || null
}

export function ResearcherCard({ researcher }: { researcher: Researcher }) {
  return <article className="card researcher-card">
    <div><p className="eyebrow">Researcher profile</p><h3><Link to={`/researchers/${encodeURIComponent(researcher.scholar_id)}`}>{researcher.full_name || 'Unnamed researcher'}</Link></h3>
      {researcher.affiliation && <p className="muted">{researcher.affiliation}</p>}
      {interestsText(researcher.research_interests) && <p className="interests">{interestsText(researcher.research_interests)}</p>}
    </div>
    <div className="metric-row">
      {researcher.total_citations != null && <span><strong>{researcher.total_citations.toLocaleString()}</strong> citations</span>}
      {researcher.h_index != null && <span><strong>{researcher.h_index}</strong> h-index</span>}
      {researcher.i10_index != null && <span><strong>{researcher.i10_index}</strong> i10-index</span>}
    </div>
  </article>
}
