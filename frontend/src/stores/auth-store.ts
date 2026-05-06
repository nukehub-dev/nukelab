import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '../types/api';

// Match backend roles exactly
export type UserRole = 'super_admin' | 'admin' | 'moderator' | 'support' | 'user' | 'guest';

// Role hierarchy levels (higher = more privileges)
const ROLE_LEVELS: Record<UserRole, number> = {
  'super_admin': 5,
  'admin': 4,
  'moderator': 3,
  'support': 2,
  'user': 1,
  'guest': 0,
};

interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  getRole: () => UserRole;
  getRoleLevel: () => number;
  
  // Role checks
  isSuperAdmin: () => boolean;
  isAdmin: () => boolean;
  isModerator: () => boolean;
  isSupport: () => boolean;
  isUser: () => boolean;
  isGuest: () => boolean;
  
  // Permission checks
  canManageUsers: () => boolean;      // Create/update/delete users
  canCreateUsers: () => boolean;       // Create users
  canDeleteUsers: () => boolean;       // Delete users
  canViewAllServers: () => boolean;    // View all servers (not just own)
  canManageServers: () => boolean;     // Manage any server (admin/moderator)
  canStartStopServers: () => boolean;  // Start/stop servers
  canDeleteServers: () => boolean;     // Delete servers
  canManageEnvironments: () => boolean; // CRUD environments
  canManagePlans: () => boolean;        // CRUD plans
  canAccessAdmin: () => boolean;       // Admin dashboard access
  canManageCredits: () => boolean;      // Grant/deduct credits
  canViewCredits: () => boolean;        // View credits
  canViewAudit: () => boolean;          // View audit logs
}

function getRoleLevel(role?: string): number {
  if (!role) return -1;
  return ROLE_LEVELS[role as UserRole] ?? -1;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      setUser: (user) => set({ user }),
      
      getRole: () => (get().user?.role as UserRole) || 'guest',
      getRoleLevel: () => getRoleLevel(get().user?.role),
      
      // Role checks - each includes roles above it
      isSuperAdmin: () => get().user?.role === 'super_admin',
      isAdmin: () => ['admin', 'super_admin'].includes(get().user?.role || ''),
      isModerator: () => ['moderator', 'admin', 'super_admin'].includes(get().user?.role || ''),
      isSupport: () => ['support', 'moderator', 'admin', 'super_admin'].includes(get().user?.role || ''),
      isUser: () => ['user', 'support', 'moderator', 'admin', 'super_admin'].includes(get().user?.role || ''),
      isGuest: () => !get().user || ['guest'].includes(get().user?.role || ''),
      
      // Permission checks based on role hierarchy
      // Admin+ can do everything
      canManageUsers: () => get().isAdmin(),
      canCreateUsers: () => get().isAdmin(),
      canDeleteUsers: () => get().isAdmin(),
      
      // Moderator+ can manage all servers
      canManageServers: () => get().isModerator(),
      canViewAllServers: () => get().isSupport(),
      
      // Support+ can start/stop servers
      canStartStopServers: () => get().isSupport() || get().isUser(),
      
      // Moderator+ can delete servers
      canDeleteServers: () => get().isModerator() || get().isUser(),
      
      // Admin only
      canManageEnvironments: () => get().isAdmin(),
      canManagePlans: () => get().isAdmin(),
      canAccessAdmin: () => get().isAdmin(),
      canManageCredits: () => get().isAdmin(),
      
      // Almost everyone can view
      canViewCredits: () => !get().isGuest(),
      canViewAudit: () => get().isAdmin(),
    }),
    {
      name: 'nukelab-auth',
      partialize: (state) => ({ user: state.user }),
    }
  )
);
