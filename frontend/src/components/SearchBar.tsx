import { useState, type FormEvent } from 'react'

export const exampleQueries = [
  'Natural language processing', 'Medical image analysis', 'Renewable energy', 'Environmental pollution',
]

export function SearchBar({ initialQuery = '', onSearch, busy = false, showExamples = true }: {
  initialQuery?: string; onSearch: (query: string) => void; busy?: boolean; showExamples?: boolean
}) {
  const [query, setQuery] = useState(initialQuery)
  const [validation, setValidation] = useState('')
  function submit(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) { setValidation('Enter a research topic to search.'); return }
    setValidation('')
    onSearch(trimmed)
  }
  return <div className="search-box">
    <form onSubmit={submit} role="search">
      <label htmlFor="topic-search">Search publications by research topic</label>
      <div className="search-row"><input id="topic-search" value={query} onChange={event => { setQuery(event.target.value); setValidation('') }}
        placeholder="machine learning for medical diagnosis" aria-invalid={!!validation} aria-describedby={validation ? 'search-validation' : undefined} />
        <button type="submit" className="button primary" disabled={busy}>Search publications</button></div>
      {validation && <p className="field-error" id="search-validation" role="alert">{validation}</p>}
    </form>
    {showExamples && <div className="suggestions"><span>Try a topic</span><div className="chip-list">
      {exampleQueries.map(example => <button type="button" className="chip" key={example} onClick={() => { setQuery(example); setValidation(''); onSearch(example) }}>{example}</button>)}
    </div></div>}
  </div>
}
