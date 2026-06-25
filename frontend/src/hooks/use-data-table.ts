import { useState, useCallback } from 'react'

export interface TableState {
  page: number
  limit: number
  sortBy: string
  sortOrder: 'asc' | 'desc'
  search: string
  filters: Record<string, string | string[]>
}

export interface UseDataTableOptions {
  defaultLimit?: number
  defaultSortBy?: string
  defaultSortOrder?: 'asc' | 'desc'
}

export function useDataTable(options: UseDataTableOptions = {}) {
  const { defaultLimit = 20, defaultSortBy = 'created_at', defaultSortOrder = 'desc' } = options

  const [state, setState] = useState<TableState>({
    page: 1,
    limit: defaultLimit,
    sortBy: defaultSortBy,
    sortOrder: defaultSortOrder,
    search: '',
    filters: {},
  })

  const setPage = useCallback((page: number) => {
    setState((prev) => ({ ...prev, page }))
  }, [])

  const setLimit = useCallback((limit: number) => {
    setState((prev) => ({ ...prev, limit, page: 1 }))
  }, [])

  const setSort = useCallback((sortBy: string, sortOrder: 'asc' | 'desc') => {
    setState((prev) => ({ ...prev, sortBy, sortOrder, page: 1 }))
  }, [])

  const setSearch = useCallback((search: string) => {
    setState((prev) => ({ ...prev, search, page: 1 }))
  }, [])

  const setFilter = useCallback((key: string, value: string | string[] | null) => {
    setState((prev) => ({
      ...prev,
      filters:
        value === null
          ? Object.fromEntries(Object.entries(prev.filters).filter(([k]) => k !== key))
          : { ...prev.filters, [key]: value },
      page: 1,
    }))
  }, [])

  const resetFilters = useCallback(() => {
    setState((prev) => ({
      ...prev,
      page: 1,
      search: '',
      filters: {},
    }))
  }, [])

  return {
    state,
    setPage,
    setLimit,
    setSort,
    setSearch,
    setFilter,
    resetFilters,
  }
}
