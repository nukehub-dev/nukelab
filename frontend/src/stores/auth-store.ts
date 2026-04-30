import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '../types/api';

// Match backend roles exactly
export type UserRole = 'super_admin' | 'admin' | 'moderator' | 'support' | 'user' | 'guest';

interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  getRole: () => UserRole;
  
  // Permission checks matching backend
  isSuperAdmin: () => boolean;
  isAdmin: () => boolean;
  isModerator: () => boolean;
  isSupport: () => boolean;
  isUser: () => boolean;
  isGuest: () => boolean;
  
  // Feature-level checks
  canManageUsers: () => boolean;      // Create/update/delete users
  canCreateUsers: () => boolean;       // Create users (admin + moderator)
  canDeleteUsers: () => boolean;       // Delete users (admin only)
  canManageServers: () => boolean;     // Manage any server (admin)
  canManageEnvironments: () => boolean; // CRUD environments (admin only)
  canViewAllServers: () => boolean;    // View all servers (admin + moderator + support)
  canStartStopServers: () => boolean;  // Start/stop own servers (user+) or all (support+)
  canAccessAdmin: () => boolean;       // Admin dashboard access
  canManageCredits: () => boolean;      // Grant/deduct credits (admin only)
  canManagePlans: () => boolean;        // CRUD plans (admin only)
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      setUser: (user) => set({ user }),
      
      getRole: () => (get().user?.role as UserRole) || 'guest',
      
      isSuperAdmin: () => get().user?.role === 'super_admin',
      isAdmin: () => get().user?.role === 'admin' || get().user?.role === 'super_admin',
      isModerator: () => get().user?.role === 'moderator' || get().isAdmin(),
      isSupport: () => get().user?.role === 'support' || get().isModerator(),
      isUser: () => get().user?.role === 'user' || get().isSupport(),
      isGuest: () => get().user?.role === 'guest' || !get().user,
      
      // Admin + Super Admin
      canManageUsers: () => get().isAdmin() || get().user?.role === 'moderator',
      
      // Admin + Moderator
      canCreateUsers: () => get().isAdmin() || get().user?.role === 'moderator',
      
      // Admin only
      canDeleteUsers: () => get().isAdmin(),
      
      // Admin only
      canManageServers: () => get().isAdmin(),
      
      // Admin only  
      canManageEnvironments: () => get().isAdmin(),
      
      // Admin + Moderator + Support
      canViewAllServers: () => get().isAdmin() || get().user?.role === 'moderator' || get().user?.role === 'support',
      
      // User+ (own), Support+ (all)
      canStartStopServers: () => !get().isGuest(),
      
      // Admin only
      canAccessAdmin: () => get().isAdmin(),
      
      // Admin only
      canManageCredits: () => get().isAdmin(),
      
      // Admin only
      canManagePlans: () => get().isAdmin(),
    }),
    {
      name: 'nukelab-auth',
      partialize: (state) => ({ user: state.user }),
    }
  )
);
