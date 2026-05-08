import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Shield,
  Check,
  X,
  Save,
  RotateCcw,
} from 'lucide-react';
import { api } from '../lib/api';
import { useAuthStore } from '../stores/auth-store';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { Button } from '../components/ui/button';

interface PermissionMatrix {
  roles: string[];
  permissions: string[];
  matrix: Record<string, string[]>;
}

export const Route = createFileRoute('/admin/permissions')({
  component: PermissionsPage,
});

function PermissionsPage() {
  const navigate = useNavigate();
  const isAdmin = useAuthStore((state) => state.isAdmin());
  const [matrix, setMatrix] = useState<PermissionMatrix | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editedRoles, setEditedRoles] = useState<Record<string, string[]>>({});

  // Redirect non-admin users
  useEffect(() => {
    if (!isAdmin) {
      navigate({ to: '/' });
    }
  }, [isAdmin, navigate]);

  useEffect(() => {
    fetchMatrix();
  }, []);

  const fetchMatrix = async () => {
    try {
      setLoading(true);
      const response = await api.get<PermissionMatrix>('/admin/permissions');
      setMatrix(response);
      setEditedRoles({ ...response.matrix });
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
        return {
          ...prev,
          [role]: current.filter((p) => p !== permission),
        };
      } else {
        return {
          ...prev,
          [role]: [...current, permission],
        };
      }
    });
  };

  const saveRole = async (role: string) => {
    try {
      setSaving(true);
      await api.put(`/admin/permissions/${role}`, {
        permissions: editedRoles[role] || [],
      });
      
      // Update original matrix
      setMatrix((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          matrix: {
            ...prev.matrix,
            [role]: editedRoles[role] || [],
          },
        };
      });
      
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save permissions');
    } finally {
      setSaving(false);
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
          <Button onClick={fetchMatrix} variant="outline" className="mt-4">
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const roleLabels: Record<string, string> = {
    super_admin: 'Super Admin',
    admin: 'Admin',
    moderator: 'Moderator',
    support: 'Support',
    user: 'User',
    guest: 'Guest',
  };

  const roleColors: Record<string, string> = {
    super_admin: 'text-purple-400 bg-purple-400/10',
    admin: 'text-red-400 bg-red-400/10',
    moderator: 'text-amber-400 bg-amber-400/10',
    support: 'text-blue-400 bg-blue-400/10',
    user: 'text-emerald-400 bg-emerald-400/10',
    guest: 'text-gray-400 bg-gray-400/10',
  };

  const permissionLabels: Record<string, string> = {
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
          <div className="p-2 rounded-lg bg-primary/10">
            <Shield className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Permission Matrix</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Manage role-based access control
            </p>
          </div>
        </div>
      </motion.div>

      {/* Permission Matrix */}
      <div className="space-y-6">
        {matrix?.roles.filter((role) => role !== 'super_admin').map((role, roleIndex) => (
          <motion.div
            key={role}
            className="bubble p-5"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: roleIndex * 0.05, ...springs.gentle }}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <span className={cn("px-3 py-1 rounded-full text-sm font-medium", roleColors[role])}>
                  {roleLabels[role] || role}
                </span>
                <span className="text-xs text-muted-foreground">
                  {editedRoles[role]?.length || 0} permissions
                </span>
              </div>
              <div className="flex items-center gap-2">
                {hasChanges(role) && (
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
                      loading={saving}
                      className="h-8"
                    >
                      <Save className="w-3.5 h-3.5 mr-1" />
                      Save
                    </Button>
                  </>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
              {matrix.permissions.map((permission) => {
                const isGranted = editedRoles[role]?.includes(permission) || false;
                return (
                  <button
                    key={permission}
                    onClick={() => togglePermission(role, permission)}
                    className={cn(
                      "flex items-center gap-2 p-2.5 rounded-lg border text-left text-sm transition-all duration-100",
                      isGranted
                        ? "bg-primary/10 border-primary/30 text-primary"
                        : "bg-muted/30 border-border/50 text-muted-foreground hover:bg-muted/50"
                    )}
                  >
                    <div className={cn(
                      "w-4 h-4 rounded flex items-center justify-center transition-colors",
                      isGranted ? "bg-primary text-primary-foreground" : "border border-muted-foreground/30"
                    )}>
                      {isGranted && <Check className="w-3 h-3" />}
                    </div>
                    <span className="truncate">
                      {permissionLabels[permission] || permission}
                    </span>
                  </button>
                );
              })}
            </div>
          </motion.div>
        ))}
      </div>

      {/* Super Admin Note */}
      <motion.div
        className="bubble p-5 bg-primary/5 border-primary/20"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, ...springs.gentle }}
      >
        <div className="flex items-center gap-3">
          <Shield className="w-5 h-5 text-purple-400" />
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
