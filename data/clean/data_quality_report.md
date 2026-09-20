# Consolidated data quality report

| Measure | Count |
|---|---:|
| total_unique_researchers | 77 |
| researchers_represented_in_publications | 76 |
| raw_publication_records | 1044 |
| unique_publications | 959 |
| duplicate_publications_merged | 85 |
| publications_with_abstracts | 976 |
| publications_without_abstracts | 68 |
| embedding_eligible | 895 |
| embedding_ineligible | 64 |
| missing_publication_year | 17 |
| missing_publication_date | 17 |
| missing_journal_or_conference | 76 |
| missing_authors | 0 |
| missing_citation_count | 0 |
| publication_urls_available | 547 |
| pdf_urls_available | 0 |
| references_available | 0 |

## Raw sources

| Source | Schema | Researchers | Publications |
|---|---|---:|---:|
| raw_scholar_data.json | legacy | 37 | 430 |
| new_scholar_data.json | checkpoint | 9 | 176 |
| new_scholar_data_batch2.json | checkpoint | 10 | 131 |
| new_scholar_data_batch3.json | checkpoint | 21 | 307 |

## Checkpoint statuses

- legacy: 37
- complete: 8
- in_progress: 1
- partial_limited: 31

## Exclusion reasons

- duplicate_publication: 85
- missing_abstract: 64

## Publication source memberships

- new_scholar_data.json: 168
- new_scholar_data_batch2.json: 127
- new_scholar_data_batch3.json: 296
- raw_scholar_data.json: 408

## Suspicious records

- profiles_without_publications: 1
- raw_publications_without_title: 0
- replacement_character_in_abstract: 0
- implausible_publication_year: 0
- {'source': 'new_scholar_data.json', 'scholar_id': 'YMFR4oAAAAJ', 'issue': 'checkpoint_failure', 'status': 'blocked'}

## Limitations

- The legacy source does not supply publication URLs, PDF URLs, references, or provenance for individual fields.
- A source affiliation string does not independently establish current FSBM membership.
- Partial checkpoints contain only the publication records saved at collection time.
- Scholar publication IDs are scoped to a researcher; cross-researcher matching requires DOI or exact title, year, and author overlap.
- Original abstracts may already be truncated or contain replacement characters; they are preserved.
