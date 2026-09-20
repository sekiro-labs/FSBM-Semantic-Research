export function LoadingState({ message = 'Loading data...' }: { message?: string }) {
  return <div className="state-panel" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" />{message}</div>
}

export function ErrorState({ message }: { message: string }) {
  return <div className="state-panel error-panel" role="alert"><strong>Something went wrong.</strong><span>{message}</span></div>
}

export function EmptyState({ message }: { message: string }) {
  return <div className="state-panel empty-panel"><strong>No results</strong><span>{message}</span></div>
}
