import { useState } from 'react'
import { Link } from 'react-router'
import type { SearchResult } from '../types/api'

export function SearchResultCard({ result, rank }: { result: SearchResult; rank: number }) {
  const [expanded, setExpanded] = useState(false)
  const abstract = result.abstract?.trim()
  const needsToggle = !!abstract && abstract.length > 260
  const shown = abstract && !expanded && needsToggle ? `${abstract.slice(0, 260).trimEnd()}…` : abstract
  return <article className="result-card card">
    <div className="result-topline"><span className="result-rank">Result {rank}</span><span className="score">Similarity {result.similarity_score.toFixed(3)}</span></div>
    <h3><Link to={`/publications/${encodeURIComponent(result.publication_id)}`}>{result.title || 'Untitled publication'}</Link></h3>
    <div className="metadata-line">
      {(result.publication_year ?? result.publication_date) && <span>{result.publication_year ?? result.publication_date}</span>}
      {result.researcher_name && <span>{result.researcher_id ? <Link to={`/researchers/${encodeURIComponent(result.researcher_id)}`}>{result.researcher_name}</Link> : result.researcher_name}</span>}
    </div>
    {!!result.authors?.length && <p className="byline">{result.authors.join(', ')}</p>}
    {abstract && <div className="abstract-preview"><p>{shown}</p>{needsToggle && <button className="text-button" type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? 'Show less' : 'Read full abstract'}</button>}</div>}
  </article>
}
