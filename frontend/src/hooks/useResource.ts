import { useEffect, useState, type DependencyList } from 'react'

interface Resource<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>, dependencies: DependencyList): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ data: null, loading: true, error: null })
  useEffect(() => {
    const controller = new AbortController()
    setState({ data: null, loading: true, error: null })
    load(controller.signal).then(
      data => { if (!controller.signal.aborted) setState({ data, loading: false, error: null }) },
      error => { if (!controller.signal.aborted) setState({ data: null, loading: false, error: error instanceof Error ? error.message : 'An unexpected error occurred.' }) },
    )
    return () => controller.abort()
    // The caller supplies the request's changing arguments as dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies)
  return state
}
