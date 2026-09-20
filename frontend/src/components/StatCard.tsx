export function StatCard({ label, value, note }: { label: string; value: number; note?: string }) {
  return <div className="stat-card"><span className="stat-label">{label}</span><strong className="stat-value">{value.toLocaleString()}</strong>{note && <span className="stat-note">{note}</span>}</div>
}
