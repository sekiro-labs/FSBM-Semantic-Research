export interface StatsResponse {
  researchers: number
  raw_publications: number
  unique_publications: number
  embedding_eligible: number
  excluded_publications: number
  indexed_publications: number
}

export interface PaginatedResponse<T> {
  page: number
  page_size: number
  total: number
  items: T[]
}

export interface Researcher {
  scholar_id: string
  full_name: string | null
  affiliation: string | null
  research_interests: string[] | string | null
  total_citations: number | null
  h_index: number | null
  i10_index: number | null
  raw_sources?: string[]
  source_statuses?: Record<string, string>
}

export interface Publication {
  article_id: string
  article_ids: string[]
  researcher_id: string | null
  researcher_ids: string[]
  researcher_name: string | null
  title: string | null
  authors: string[]
  publication_year: number | null
  publication_date: string | null
  journal: string | null
  volume: string | null
  pages: string | null
  publisher: string | null
  citations: number | null
  abstract: string | null
  abstract_clean: string | null
  publication_url: string | null
  pdf_url: string | null
  references: string[] | null
  embedding_eligible: boolean
}

export interface ResearcherDetail extends Researcher {
  publications: Publication[]
}

export interface SearchResult {
  publication_id: string
  title: string | null
  authors: string[] | null
  publication_year: number | null
  publication_date: string | null
  abstract: string | null
  researcher_id: string | null
  researcher_name: string | null
  researcher_ids: string[]
  similarity_score: number
}

export interface SearchResponse {
  query: string
  top_k: number
  results: SearchResult[]
}
