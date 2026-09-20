export function Pagination({ page, pageSize, total, onPageChange }: {
  page: number; pageSize: number; total: number; onPageChange: (page: number) => void
}) {
  const pages = Math.ceil(total / pageSize)
  if (pages < 2) return null
  return <nav className="pagination" aria-label="Pagination">
    <button type="button" className="button secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>Previous</button>
    <span>Page <strong>{page}</strong> of {pages}</span>
    <button type="button" className="button secondary" disabled={page >= pages} onClick={() => onPageChange(page + 1)}>Next</button>
  </nav>
}
