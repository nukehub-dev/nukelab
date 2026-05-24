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

// Permission constants (match backend)
export const PERMISSIONS = {
  USERS_READ: 'users:read',
  USERS_CREATE: 'users:create',
  USERS_UPDATE: 'users:update',
  USERS_DELETE: 'users:delete',
  USERS_IMPERSONATE: 'users:impersonate',
  SERVERS_READ_OWN: 'servers:read_own',
  SERVERS_READ_ALL: 'servers:read_all',
  SERVERS_START: 'servers:start',
  SERVERS_STOP: 'servers:stop',
  SERVERS_DELETE: 'servers:delete',
  SERVERS_MANAGE: 'servers:manage',
  RESOURCES_READ_OWN: 'resources:read_own',
  RESOURCES_READ_ALL: 'resources:read_all',
  ENVIRONMENT_CREATE: 'environment:create',
  ENVIRONMENT_READ: 'environment:read',
  ENVIRONMENT_UPDATE: 'environment:update',
  ENVIRONMENT_DELETE: 'environment:delete',
  PLAN_CREATE: 'plan:create',
  PLAN_READ: 'plan:read',
  PLAN_UPDATE: 'plan:update',
  PLAN_DELETE: 'plan:delete',
  QUOTA_READ: 'quota:read',
  QUOTA_UPDATE: 'quota:update',
  CREDITS_READ: 'credits:read',
  CREDITS_GRANT: 'credits:grant',
  CREDITS_DEDUCT: 'credits:deduct',
  ANALYTICS_READ: 'analytics:read',
  WORKSPACES_READ: 'workspaces:read',
  WORKSPACES_MANAGE: 'workspaces:manage',
  VOLUMES_READ: 'volumes:read',
  VOLUMES_MANAGE: 'volumes:manage',

  AUDIT_READ: 'audit:read',
  ADMIN_ACCESS: 'admin:access',
  ALL: '*',
} as const;

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

  // Raw permission checks (robust - checks actual permissions first, falls back to roles)
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (permissions: string[]) => boolean;
  hasAllPermissions: (permissions: string[]) => boolean;

  // Semantic permission checks
  canManageUsers: () => boolean;
  canCreateUsers: () => boolean;
  canDeleteUsers: () => boolean;
  canViewAllServers: () => boolean;
  canManageServers: () => boolean;
  canStartStopServers: () => boolean;
  canDeleteServers: () => boolean;
  canManageEnvironments: () => boolean;
  canManagePlans: () => boolean;
  canAccessAdmin: () => boolean;
  canManageCredits: () => boolean;
  canViewCredits: () => boolean;
  canViewAudit: () => boolean;
}

function getRoleLevel(role?: string): number {
  if (!role) return -1;
  return ROLE_LEVELS[role as UserRole] ?? -1;
}

/**
 * Check if user has a specific permission.
 * First checks actual permissions array from backend (supports dynamic permission changes).
 * Falls back to role-based checks for backwards compatibility.
 */
function checkPermission(user: User | null, permission: string): boolean {
  if (!user || !user.is_active) return false;

  // If backend sent permissions, use them (robust, supports dynamic changes)
  if (user.permissions && user.permissions.length > 0) {
    // Super admin wildcard
    if (user.permissions.includes(PERMISSIONS.ALL)) return true;
    return user.permissions.includes(permission);
  }

  // Fallback: role-based check (for backwards compatibility or if permissions not loaded yet)
  const roleLevel = getRoleLevel(user.role);

  switch (permission) {
    case PERMISSIONS.USERS_READ:
    case PERMISSIONS.USERS_CREATE:
    case PERMISSIONS.USERS_UPDATE:
      return roleLevel >= ROLE_LEVELS.moderator;
    case PERMISSIONS.USERS_DELETE:
    case PERMISSIONS.USERS_IMPERSONATE:
      return roleLevel >= ROLE_LEVELS.admin;
    case PERMISSIONS.SERVERS_READ_ALL:
    case PERMISSIONS.SERVERS_MANAGE:
    case PERMISSIONS.SERVERS_DELETE:
      return roleLevel >= ROLE_LEVELS.moderator;
    case PERMISSIONS.SERVERS_START:
    case PERMISSIONS.SERVERS_STOP:
      return roleLevel >= ROLE_LEVELS.user;
    case PERMISSIONS.SERVERS_READ_OWN:
      return roleLevel >= ROLE_LEVELS.guest;
    case PERMISSIONS.RESOURCES_READ_ALL:
      return roleLevel >= ROLE_LEVELS.support;
    case PERMISSIONS.RESOURCES_READ_OWN:
      return roleLevel >= ROLE_LEVELS.guest;
    case PERMISSIONS.ENVIRONMENT_CREATE:
    case PERMISSIONS.ENVIRONMENT_UPDATE:
    case PERMISSIONS.ENVIRONMENT_DELETE:
      return roleLevel >= ROLE_LEVELS.admin;
    case PERMISSIONS.ENVIRONMENT_READ:
      return roleLevel >= ROLE_LEVELS.moderator;
    case PERMISSIONS.PLAN_CREATE:
    case PERMISSIONS.PLAN_UPDATE:
    case PERMISSIONS.PLAN_DELETE:
      return roleLevel >= ROLE_LEVELS.admin;
    case PERMISSIONS.PLAN_READ:
      return roleLevel >= ROLE_LEVELS.moderator;
    case PERMISSIONS.QUOTA_READ:
    case PERMISSIONS.QUOTA_UPDATE:
      return roleLevel >= ROLE_LEVELS.admin;
    case PERMISSIONS.CREDITS_READ:
      return roleLevel >= ROLE_LEVELS.user;
    case PERMISSIONS.CREDITS_GRANT:
    case PERMISSIONS.CREDITS_DEDUCT:
      return roleLevel >= ROLE_LEVELS.admin;
    case PERMISSIONS.AUDIT_READ:
    case PERMISSIONS.ADMIN_ACCESS:
      return roleLevel >= ROLE_LEVELS.admin;
    case PERMISSIONS.ANALYTICS_READ:
      return roleLevel >= ROLE_LEVELS.support;
    case PERMISSIONS.WORKSPACES_READ:
    case PERMISSIONS.VOLUMES_READ:
    case PERMISSIONS.WORKSPACES_MANAGE:
    case PERMISSIONS.VOLUMES_MANAGE:
      return roleLevel >= ROLE_LEVELS.admin;
    default:
      return false;
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      setUser: (user) => set({ user }),

      getRole: () => (get().user?.role as UserRole) || 'guest',
      getRoleLevel: () => getRoleLevel(get().user?.role),

      // Role checks - now permission-based for consistency and robustness
      isSuperAdmin: () => get().hasPermission(PERMISSIONS.ALL),
      isAdmin: () => get().hasPermission(PERMISSIONS.ADMIN_ACCESS),
      isModerator: () => get().hasPermission(PERMISSIONS.SERVERS_READ_ALL) && !get().hasPermission(PERMISSIONS.ADMIN_ACCESS),
      isSupport: () => get().hasPermission(PERMISSIONS.RESOURCES_READ_ALL) && !get().hasPermission(PERMISSIONS.SERVERS_READ_ALL),
      isUser: () => get().hasPermission(PERMISSIONS.SERVERS_START) && !get().hasPermission(PERMISSIONS.RESOURCES_READ_ALL),
      isGuest: () => !get().user || (get().hasPermission(PERMISSIONS.SERVERS_READ_OWN) && !get().hasPermission(PERMISSIONS.SERVERS_START)),

      // Raw permission checks
      hasPermission: (permission: string) => checkPermission(get().user, permission),
      hasAnyPermission: (permissions: string[]) => permissions.some((p) => checkPermission(get().user, p)),
      hasAllPermissions: (permissions: string[]) => permissions.every((p) => checkPermission(get().user, p)),

      // Semantic permission checks - now use actual permissions with role fallback
      canManageUsers: () => get().hasAnyPermission([PERMISSIONS.USERS_CREATE, PERMISSIONS.USERS_UPDATE, PERMISSIONS.USERS_DELETE]),
      canCreateUsers: () => get().hasPermission(PERMISSIONS.USERS_CREATE),
      canDeleteUsers: () => get().hasPermission(PERMISSIONS.USERS_DELETE),

      canManageServers: () => get().hasPermission(PERMISSIONS.SERVERS_MANAGE),
      canViewAllServers: () => get().hasPermission(PERMISSIONS.SERVERS_READ_ALL),

      canStartStopServers: () => get().hasAnyPermission([PERMISSIONS.SERVERS_START, PERMISSIONS.SERVERS_STOP]),
      canDeleteServers: () => get().hasPermission(PERMISSIONS.SERVERS_DELETE),

      canManageEnvironments: () => get().hasAnyPermission([PERMISSIONS.ENVIRONMENT_CREATE, PERMISSIONS.ENVIRONMENT_UPDATE, PERMISSIONS.ENVIRONMENT_DELETE]),
      canManagePlans: () => get().hasAnyPermission([PERMISSIONS.PLAN_CREATE, PERMISSIONS.PLAN_UPDATE, PERMISSIONS.PLAN_DELETE]),
      canAccessAdmin: () =>
        get().hasAnyPermission([
          PERMISSIONS.ADMIN_ACCESS,
          PERMISSIONS.USERS_READ,
          PERMISSIONS.USERS_CREATE,
          PERMISSIONS.USERS_UPDATE,
          PERMISSIONS.USERS_DELETE,
          PERMISSIONS.SERVERS_READ_ALL,
          PERMISSIONS.SERVERS_MANAGE,
          PERMISSIONS.RESOURCES_READ_ALL,
          PERMISSIONS.ENVIRONMENT_CREATE,
          PERMISSIONS.ENVIRONMENT_UPDATE,
          PERMISSIONS.ENVIRONMENT_DELETE,
          PERMISSIONS.PLAN_CREATE,
          PERMISSIONS.PLAN_UPDATE,
          PERMISSIONS.PLAN_DELETE,
          PERMISSIONS.QUOTA_READ,
          PERMISSIONS.QUOTA_UPDATE,
          PERMISSIONS.CREDITS_GRANT,
          PERMISSIONS.CREDITS_DEDUCT,
          PERMISSIONS.ANALYTICS_READ,
          PERMISSIONS.AUDIT_READ,
        ]),
      canManageCredits: () => get().hasAnyPermission([PERMISSIONS.CREDITS_GRANT, PERMISSIONS.CREDITS_DEDUCT]),

      canViewCredits: () => get().hasPermission(PERMISSIONS.CREDITS_READ),
      canViewAudit: () => get().hasPermission(PERMISSIONS.AUDIT_READ),
    }),
    {
      name: 'nukelab-auth',
      version: 1,
      migrate: (_persistedState: unknown) => {
        // Reset cached user on version bump so fresh data is fetched
        return { user: null };
      },
      partialize: (state) => ({ user: state.user }),
    }
  )
);
