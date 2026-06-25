import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type SidebarMode = 'collapsed' | 'auto' | 'expanded'

interface SidebarState {
  isOpen: boolean
  mode: SidebarMode
  isMobileOpen: boolean
  toggle: () => void
  setMode: (mode: SidebarMode) => void
  setOpen: (open: boolean) => void
  setMobileOpen: (open: boolean) => void
  closeMobile: () => void
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      isOpen: true,
      mode: 'expanded',
      isMobileOpen: false,
      toggle: () => set((state) => ({ isOpen: !state.isOpen })),
      setMode: (mode) =>
        set(() => {
          if (mode === 'expanded') return { mode, isOpen: true }
          if (mode === 'collapsed') return { mode, isOpen: false }
          return { mode }
        }),
      setOpen: (open) => set({ isOpen: open }),
      setMobileOpen: (open) => set({ isMobileOpen: open }),
      closeMobile: () => set({ isMobileOpen: false }),
    }),
    {
      name: 'nukelab-sidebar',
      partialize: (state) => ({ mode: state.mode }),
    }
  )
)
