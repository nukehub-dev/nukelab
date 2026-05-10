import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Shield,
  Check,
  X,
  Save,
  RotateCcw,
  Users,
  Server,
  Boxes,
  Trees,
  FileText,
  CreditCard,
  Settings,
  Lock,
  ChevronUp,
  CheckCheck,
} from 'lucide-react';
import { api } from '../lib/api';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { Button } from '../components/ui/button';

interface PermissionMatrix {
  roles: string[];
  permissions: string[];
  matrix: Record<string, string[]>;
}

interface PermissionCategory {
  id: string;
  label: string;
  icon: typeof Users;
  color: string;
  bgColor: string;
  permissions: string[];
}

export const Route = createFileRoute('/admin/permissions')({
  component: PermissionsPage,
});

const ROLE_LABELS: Record<string, string> = {
  super_admin: 'Super Admin',
  admin: 'Admin',
  moderator: 'Moderator',
  support: 'Support',
  user: 'User',
  guest: 'Guest',
};

const ROLE_COLORS: Record<string, { text: string; bg: string; border: string; bar: string }> = {
  super_admin: { text: 'text-purple-400', bg: 'bg-purple-400/10', border: 'border-purple-400/20', bar: 'bg-purple-400' },
  admin: { text: 'text-red-400', bg: 'bg-red-400/10', border: 'border-red-400/20', bar: 'bg-red-400' },
  moderator: { text: 'text-amber-400', bg: 'bg-amber-400/10', border: 'border-amber-400/20', bar: 'bg-amber-400' },
  support: { text: 'text-blue-400', bg: 'bg-blue-400/10', border: 'border-blue-400/20', bar: 'bg-blue-400' },
  user: { text: 'text-emerald-400', bg: 'bg-emerald-400/10', border: 'border-emerald-400/20', bar: 'bg-emerald-400' },
  guest: { text: 'text-gray-400', bg: 'bg-gray-400/10', border: 'border-gray-400/20', bar: 'bg-gray-400' },
};

const PERMISSION_LABELS: Record<string, string> = {
  'users:read': 'Read Users',
  'users:create': 'Create Users',
  'users:update': 'Update Users',
  'users:delete': 'Delete Users',
  'users:impersonate': 'Impersonate',
  'servers:read_own': 'Read Own Servers',
  'servers:read_all': 'Read All Servers',
  'servers:start': 'Start Servers',
  'servers:stop': 'Stop Servers',
  'servers:delete': 'Delete Servers',
  'servers:manage': 'Manage Servers',
  'resources:read_own': 'Read Own Resources',
  'resources:read_all': 'Read All Resources',
  'environment:create': 'Create Environments',
  'environment:read': 'Read Environments',
  'environment:update': 'Update Environments',
  'environment:delete': 'Delete Environments',
  'plan:create': 'Create Plans',
  'plan:read': 'Read Plans',
  'plan:update': 'Update Plans',
  'plan:delete': 'Delete Plans',
  'quota:read': 'Read Quotas',
  'quota:update': 'Update Quotas',
  'credits:read': 'Read Credits',
  'credits:grant': 'Grant Credits',
  'credits:deduct': 'Deduct Credits',
  'audit:read': 'Read Audit',
  'admin:access': 'Admin Access',
  '*': 'All Permissions',
};

function getCategories(allPermissions: string[]): PermissionCategory[] {
  const cats: PermissionCategory[] = [
    {
      id: 'users', label: 'Users', icon: Users,
      color: 'text-blue-400', bgColor: 'bg-blue-400/10',
      permissions: allPermissions.filter(p => p.startsWith('users:')),
    },
    {
      id: 'servers', label: 'Servers', icon: Server,
      color: 'text-emerald-400', bgColor: 'bg-emerald-400/10',
      permissions: allPermissions.filter(p => p.startsWith('servers:')),
    },
    {
      id: 'resources', label: 'Resources', icon: Boxes,
      color: 'text-violet-400', bgColor: 'bg-violet-400/10',
      permissions: allPermissions.filter(p => p.startsWith('resources:')),
    },
    {
      id: 'environments', label: 'Environments', icon: Trees,
      color: 'text-amber-400', bgColor: 'bg-amber-400/10',
      permissions: allPermissions.filter(p => p.startsWith('environment:')),
    },
    {
      id: 'plans', label: 'Plans', icon: FileText,
      color: 'text-cyan-400', bgColor: 'bg-cyan-400/10',
      permissions: allPermissions.filter(p => p.startsWith('plan:') || p.startsWith('quota:')),
    },
    {
      id: 'credits', label: 'Credits', icon: CreditCard,
      color: 'text-rose-400', bgColor: 'bg-rose-400/10',
      permissions: allPermissions.filter(p => p.startsWith('credits:')),
    },
    {
      id: 'admin', label: 'Admin', icon: Settings,
      color: 'text-orange-400', bgColor: 'bg-orange-400/10',
      permissions: allPermissions.filter(p => p.startsWith('audit:') || p.startsWith('admin:') || p === '*'),
    },
  ];
  return cats.filter(c => c.permissions.length > 0);
}

function PermissionsPage() {
  const navigate = useNavigate();
  const canAccessAdmin = useAuthStore((state) => state.hasPermission(PERMISSIONS.ADMIN_ACCESS));
  const [matrix, setMatrix] = useState<PermissionMatrix | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editedRoles, setEditedRoles] = useState<Record<string, string[]>>({});
  const [expandedRoles, setExpandedRoles] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!canAccessAdmin) navigate({ to: '/' });
  }, [canAccessAdmin, navigate]);

  useEffect(() => {
    fetchMatrix();
  }, []);

  const fetchMatrix = async () => {
    try {
      setLoading(true);
      const response = await api.get<PermissionMatrix>('/admin/permissions');
      setMatrix(response);
      setEditedRoles({ ...response.matrix });
      // Expand all by default
      const expanded: Record<string, boolean> = {};
      response.roles.forEach(r => { if (r !== 'super_admin') expanded[r] = true; });
      setExpandedRoles(expanded);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load permissions');
    } finally {
      setLoading(false);
    }
  };

  const togglePermission = (role: string, permission: string) => {
    setEditedRoles((prev) => {
      const current = prev[role] || [];
      const hasPermission = current.includes(permission);
      if (hasPermission) {
        return { ...prev, [role]: current.filter((p) => p !== permission) };
      } else {
        return { ...prev, [role]: [...current, permission] };
      }
    });
  };

  const toggleAllInCategory = (role: string, category: PermissionCategory, grant: boolean) => {
    setEditedRoles((prev) => {
      const current = new Set(prev[role] || []);
      category.permissions.forEach(p => {
        if (grant) current.add(p);
        else current.delete(p);
      });
      return { ...prev, [role]: Array.from(current) };
    });
  };

  const saveRole = async (role: string) => {
    try {
      setSavingRole(role);
      await api.put(`/admin/permissions/${role}`, {
        permissions: editedRoles[role] || [],
      });
      setMatrix((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          matrix: { ...prev.matrix, [role]: editedRoles[role] || [] },
        };
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save permissions');
    } finally {
      setSavingRole(null);
    }
  };

  const resetRole = (role: string) => {
    if (!matrix) return;
    setEditedRoles((prev) => ({
      ...prev,
      [role]: [...(matrix.matrix[role] || [])],
    }));
  };

  const hasChanges = (role: string) => {
    if (!matrix) return false;
    const original = matrix.matrix[role] || [];
    const edited = editedRoles[role] || [];
    if (original.length !== edited.length) return true;
    return original.some((p) => !edited.includes(p)) || edited.some((p) => !original.includes(p));
  };

  const categories = useMemo(() => matrix ? getCategories(matrix.permissions) : [], [matrix]);

  if (loading) {
    return (
      <div className="min-h-screen p-6 lg:p-10 flex items-center justify-center">
        <div className="text-center">
          <Shield className="w-8 h-8 mx-auto text-muted-foreground animate-pulse mb-4" />
          <p className="text-muted-foreground">Loading permissions...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <X className="w-8 h-8 mx-auto text-destructive mb-4" />
          <p className="text-destructive font-medium">{error}</p>
          <Button onClick={fetchMatrix} variant="outline" className="mt-4">Retry</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col md:flex-row md:items-center md:justify-between gap-4"
      >
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-primary/10">
            <Shield className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Permission Matrix</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Manage role-based access control
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchMatrix}>
            <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
            Refresh
          </Button>
        </div>
      </motion.div>

      {/* Role Cards */}
      <div className="space-y-6">
        {matrix?.roles.filter((role) => role !== 'super_admin').map((role, roleIndex) => {
          const roleColor = ROLE_COLORS[role];
          const grantedCount = editedRoles[role]?.length || 0;
          const totalCount = matrix.permissions.length;
          const progress = totalCount > 0 ? (grantedCount / totalCount) * 100 : 0;
          const isExpanded = expandedRoles[role] ?? true;
          const changed = hasChanges(role);

          return (
            <motion.div
              key={role}
              className={cn(
                "bubble overflow-hidden transition-colors",
                changed && "border-primary/30"
              )}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: roleIndex * 0.05, ...springs.gentle }}
            >
              {/* Role Header */}
              <div className="p-5 border-b border-border/50">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className={cn("p-2 rounded-lg", roleColor.bg)}>
                      <Lock className={cn("w-4 h-4", roleColor.text)} />
                    </div>
                    <div>
                      <div className="flex items-center gap-3">
                        <h2 className="text-lg font-semibold">{ROLE_LABELS[role] || role}</h2>
                        <span className={cn("text-xs font-medium px-2 py-0.5 rounded-full", roleColor.bg, roleColor.text)}>
                          {grantedCount} / {totalCount}
                        </span>
                        {changed && (
                          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-400/10 text-amber-400">
                            Modified
                          </span>
                        )}
                      </div>
                      {/* Progress Bar */}
                      <div className="flex items-center gap-2 mt-2">
                        <div className="w-48 h-1.5 rounded-full bg-muted overflow-hidden">
                          <motion.div
                            className={cn("h-full rounded-full", roleColor.bar)}
                            initial={{ width: 0 }}
                            animate={{ width: `${progress}%` }}
                            transition={{ duration: 0.5, delay: 0.2 }}
                          />
                        </div>
                        <span className="text-xs text-muted-foreground">{Math.round(progress)}%</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {changed && (
                      <>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => resetRole(role)}
                          className="h-8"
                        >
                          <RotateCcw className="w-3.5 h-3.5 mr-1" />
                          Reset
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => saveRole(role)}
                          loading={savingRole === role}
                          className="h-8"
                        >
                          <Save className="w-3.5 h-3.5 mr-1" />
                          Save
                        </Button>
                      </>
                    )}
                    <motion.button
                      onClick={() => setExpandedRoles(prev => ({ ...prev, [role]: !isExpanded }))}
                      className="p-2 rounded-lg hover:bg-muted transition-colors"
                      animate={{ rotate: isExpanded ? 0 : 180 }}
                      transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                    >
                      <ChevronUp className="w-4 h-4" />
                    </motion.button>
                  </div>
                </div>
              </div>

              {/* Permission Categories */}
              <AnimatePresence initial={false}>
                {isExpanded && (
                  <motion.div
                    key={`${role}-content`}
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="p-5 space-y-6">
                      {categories.map((category, catIndex) => {
                        const categoryGranted = category.permissions.filter(p =>
                          editedRoles[role]?.includes(p)
                        ).length;

                        return (
                          <motion.div
                            key={category.id}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: catIndex * 0.05 + 0.1, duration: 0.3 }}
                          >
                            {/* Category Header */}
                            <div className="flex items-center justify-between mb-3">
                              <div className="flex items-center gap-2">
                                <category.icon className={cn("w-4 h-4", category.color)} />
                                <h3 className="text-sm font-semibold">{category.label}</h3>
                                <span className="text-xs text-muted-foreground">
                                  {categoryGranted}/{category.permissions.length}
                                </span>
                              </div>
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => toggleAllInCategory(role, category, true)}
                                  className="text-[10px] px-2 py-1 rounded-md hover:bg-muted transition-colors text-muted-foreground"
                                >
                                  All
                                </button>
                                <button
                                  onClick={() => toggleAllInCategory(role, category, false)}
                                  className="text-[10px] px-2 py-1 rounded-md hover:bg-muted transition-colors text-muted-foreground"
                                >
                                  None
                                </button>
                              </div>
                            </div>

                            {/* Permission Grid */}
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                              {category.permissions.map((permission, permIndex) => {
                                const isGranted = editedRoles[role]?.includes(permission) || false;
                                return (
                                  <motion.button
                                    key={permission}
                                    onClick={() => togglePermission(role, permission)}
                                    initial={{ opacity: 0, scale: 0.95 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    transition={{ delay: permIndex * 0.02 + 0.15, duration: 0.2 }}
                                    whileHover={{ scale: 1.02 }}
                                    whileTap={{ scale: 0.97 }}
                                    className={cn(
                                      "group flex items-center gap-2.5 px-3 py-2.5 rounded-lg border text-left text-sm transition-colors duration-150",
                                      isGranted
                                        ? cn("border-primary/30 bg-primary/5 text-primary hover:bg-primary/10")
                                        : "border-border/30 bg-muted/20 text-muted-foreground/60 hover:bg-muted/40 hover:text-muted-foreground"
                                    )}
                                  >
                                    <motion.div
                                      className={cn(
                                        "w-4 h-4 rounded flex items-center justify-center shrink-0",
                                        isGranted
                                          ? "bg-primary text-primary-foreground"
                                          : "border border-muted-foreground/20 group-hover:border-muted-foreground/40"
                                      )}
                                      animate={isGranted ? { scale: [1, 1.2, 1] } : { scale: 1 }}
                                      transition={{ duration: 0.2 }}
                                    >
                                      {isGranted && <Check className="w-2.5 h-2.5" />}
                                    </motion.div>
                                    <span className="truncate text-xs font-medium">
                                      {PERMISSION_LABELS[permission] || permission}
                                    </span>
                                  </motion.button>
                                );
                              })}
                            </div>
                          </motion.div>
                        );
                      })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>

      {/* Super Admin Note */}
      <motion.div
        className="bubble p-5 bg-purple-400/5 border-purple-400/20"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, ...springs.gentle }}
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-purple-400/10">
            <CheckCheck className="w-4 h-4 text-purple-400" />
          </div>
          <div>
            <p className="text-sm font-medium">Super Admin</p>
            <p className="text-xs text-muted-foreground">
              Super admins have all permissions automatically. This role cannot be modified.
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
