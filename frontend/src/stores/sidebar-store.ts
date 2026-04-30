import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface SidebarState {
  isOpen: boolean;
  isPinned: boolean;
  isMobileOpen: boolean;
  toggle: () => void;
  togglePin: () => void;
  setOpen: (open: boolean) => void;
  setMobileOpen: (open: boolean) => void;
  closeMobile: () => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      isOpen: true,
      isPinned: true,
      isMobileOpen: false,
      toggle: () => set((state) => ({ isOpen: !state.isOpen })),
      togglePin: () => set((state) => ({ isPinned: !state.isPinned })),
      setOpen: (open) => set({ isOpen: open }),
      setMobileOpen: (open) => set({ isMobileOpen: open }),
      closeMobile: () => set({ isMobileOpen: false }),
    }),
    {
      name: 'nukelab-sidebar',
      partialize: (state) => ({ isPinned: state.isPinned }),
    }
  )
);
