import { create } from 'zustand'
import { useCallback } from 'react'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  type: ToastType
  title: string
  message?: string
  duration?: number
  action?: {
    label: string
    onClick: () => void
  }
}

interface ToastStore {
  toasts: Toast[]
  addToast: (toast: Omit<Toast, 'id'>) => string
  removeToast: (id: string) => void
  updateToast: (id: string, updates: Partial<Toast>) => void
}

let toastIdCounter = 0

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (toast) => {
    const id = `toast-${++toastIdCounter}`
    set((state) => ({
      toasts: [...state.toasts, { ...toast, id }],
    }))
    return id
  },
  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }))
  },
  updateToast: (id, updates) => {
    set((state) => ({
      toasts: state.toasts.map((t) => (t.id === id ? { ...t, ...updates } : t)),
    }))
  },
}))

// Convenience hooks
export function useToast() {
  const addToast = useToastStore((s) => s.addToast)
  const removeToast = useToastStore((s) => s.removeToast)

  const toast = useCallback((options: Omit<Toast, 'id'>) => addToast(options), [addToast])

  const success = useCallback(
    (title: string, message?: string) =>
      addToast({ type: 'success', title, message, duration: 5000 }),
    [addToast]
  )

  const error = useCallback(
    (title: string, message?: string) =>
      addToast({ type: 'error', title, message, duration: 8000 }),
    [addToast]
  )

  const warning = useCallback(
    (title: string, message?: string) =>
      addToast({ type: 'warning', title, message, duration: 6000 }),
    [addToast]
  )

  const info = useCallback(
    (title: string, message?: string) => addToast({ type: 'info', title, message, duration: 4000 }),
    [addToast]
  )

  return { toast, success, error, warning, info, removeToast }
}
