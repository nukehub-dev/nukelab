import { createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  FolderOpen,
  Users,
  HardDrive,
  ArrowLeft,
  Plus,
  Trash2,
  Shield,
  User,
  Eye,
  Pencil,
  X,
} from 'lucide-react';
import {
  useWorkspace,
  useUpdateWorkspace,
  useAddWorkspaceMember,
  useRemoveWorkspaceMember,
  useUpdateMemberRole,
} from '../hooks/use-workspaces';
import { useUsers } from '../hooks/use-users';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Select, SelectItem } from '../components/ui/select';
import { Combobox } from '../components/ui/combobox';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { Tooltip } from '../components/ui/tooltip';
import { Link } from '@tanstack/react-router';

export const Route = createFileRoute('/workspaces/$workspaceId')({
  component: WorkspaceDetailPage,
});

const roleIcons = {
  admin: Shield,
  read_write: User,
  read_only: Eye,
};

const roleLabels = {
  admin: 'Admin',
  read_write: 'Editor',
  read_only: 'Viewer',
};

const roleColors = {
  admin: 'text-purple-400 bg-purple-400/10',
  read_write: 'text-blue-400 bg-blue-400/10',
  read_only: 'text-gray-400 bg-gray-400/10',
};

function WorkspaceDetailPage() {
  const { workspaceId } = Route.useParams();
  const { data: workspace, isLoading } = useWorkspace(workspaceId);
  const { data: usersData } = useUsers();
  const updateWorkspace = useUpdateWorkspace();
  const addMember = useAddWorkspaceMember();
  const removeMember = useRemoveWorkspaceMember();
  const updateRole = useUpdateMemberRole();
  const { confirm, dialog } = useConfirmDialog();

  const [showAddMember, setShowAddMember] = useState(false);
  const [showEditWorkspace, setShowEditWorkspace] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedRole, setSelectedRole] = useState('read_write');
  const [editForm, setEditForm] = useState({ name: '', description: '' });

  const handleAddMember = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUserId) return;
    
    addMember.mutate(
      { workspaceId, userId: selectedUserId, role: selectedRole },
      {
        onSuccess: () => {
          setShowAddMember(false);
          setSelectedUserId('');
          setSelectedRole('read_write');
        },
      }
    );
  };

  if (isLoading) {
    return (
      <div className="min-h-screen p-6 lg:p-10">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3"></div>
          <div className="h-4 bg-muted rounded w-1/2"></div>
          <div className="h-32 bg-muted rounded"></div>
        </div>
      </div>
    );
  }

  if (!workspace) {
    return (
      <div className="min-h-screen p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <FolderOpen className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
          <h2 className="text-lg font-semibold mb-2">Workspace not found</h2>
          <Link to="/workspaces" className="text-primary hover:underline">
            Back to Workspaces
          </Link>
        </div>
      </div>
    );
  }

  const availableUsers = usersData?.data?.filter(
    (u: any) => !workspace.members?.some((m: any) => m.user_id === u.id)
  ) || [];

  const userOptions = availableUsers.map((user: any) => ({
    value: user.id,
    label: `${user.username} (${user.email})`,
  }));

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="space-y-4"
      >
        <Link
          to="/workspaces"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Workspaces
        </Link>

        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 rounded-lg bg-primary/10 flex-shrink-0">
              <FolderOpen className="w-5 h-5 text-primary" />
            </div>
            <div className="min-w-0">
              <h1 className="text-2xl font-bold truncate">{workspace.name}</h1>
              {workspace.description && (
                <p className="text-sm text-muted-foreground truncate">{workspace.description}</p>
              )}
            </div>
          </div>
          <Tooltip content="Edit workspace">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEditForm({ name: workspace.name, description: workspace.description || '' });
                setShowEditWorkspace(true);
              }}
              className="gap-1 flex-shrink-0"
            >
              <Pencil className="w-3.5 h-3.5" />
              Edit
            </Button>
          </Tooltip>
        </div>
      </motion.div>

      {/* Info Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <motion.div
          className="bubble p-4"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, ...springs.gentle }}
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-chart-1/10">
              <HardDrive className="w-4 h-4 text-chart-1" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Volume</p>
              <p className="text-sm font-medium">{workspace.volume_name}</p>
            </div>
          </div>
        </motion.div>

        <motion.div
          className="bubble p-4"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, ...springs.gentle }}
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-chart-2/10">
              <Users className="w-4 h-4 text-chart-2" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Members</p>
              <p className="text-sm font-medium">{workspace.members?.length || 0}</p>
            </div>
          </div>
        </motion.div>

        <motion.div
          className="bubble p-4"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, ...springs.gentle }}
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-chart-3/10">
              <Shield className="w-4 h-4 text-chart-3" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Status</p>
              <p className="text-sm font-medium">{workspace.is_active ? 'Active' : 'Inactive'}</p>
            </div>
          </div>
        </motion.div>
      </div>

      {/* Members Section */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4, ...springs.gentle }}
      >
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold">Members</h3>
          </div>
          <Button
            size="sm"
            onClick={() => setShowAddMember(!showAddMember)}
            className="gap-1"
          >
            <Plus className="w-3.5 h-3.5" />
            Add Member
          </Button>
        </div>

        {showAddMember && (
          <form onSubmit={handleAddMember} className="mb-4 p-4 rounded-xl bg-surface/50 border border-border/50 space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">User</label>
                <Combobox
                  value={selectedUserId}
                  onChange={setSelectedUserId}
                  options={userOptions}
                  placeholder="Select user..."
                  searchPlaceholder="Search users..."
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Role</label>
                <Select
                  value={selectedRole}
                  onChange={setSelectedRole}
                  placeholder="Select role..."
                >
                  <SelectItem value="read_write">Editor</SelectItem>
                  <SelectItem value="read_only">Viewer</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </Select>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button type="submit" size="sm" loading={addMember.isPending}>Add</Button>
              <Button type="button" variant="outline" size="sm" onClick={() => setShowAddMember(false)}>
                Cancel
              </Button>
            </div>
          </form>
        )}

        <div className="space-y-2">
          {workspace.members?.map((member: any) => {
            const RoleIcon = roleIcons[member.role as keyof typeof roleIcons] || User;
            return (
              <div
                key={member.user_id}
                className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className={cn("p-1.5 rounded flex-shrink-0", roleColors[member.role as keyof typeof roleColors])}>
                    <RoleIcon className="w-3.5 h-3.5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{member.username || 'Unknown'}</p>
                    <p className="text-xs text-muted-foreground truncate">{member.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className={cn("text-xs px-2 py-0.5 rounded-full", roleColors[member.role as keyof typeof roleColors])}>
                    {roleLabels[member.role as keyof typeof roleLabels] || member.role}
                  </span>
                  <Select
                    value={member.role}
                    onChange={(value) => updateRole.mutate({
                      workspaceId,
                      userId: member.user_id,
                      role: value
                    })}
                    className="w-28"
                  >
                    <SelectItem value="read_write">Editor</SelectItem>
                    <SelectItem value="read_only">Viewer</SelectItem>
                    <SelectItem value="admin">Admin</SelectItem>
                  </Select>
                  <Tooltip content="Remove member">
                    <button
                      onClick={async () => {
                        const confirmed = await confirm({
                          title: 'Remove Member',
                          description: `Are you sure you want to remove ${member.username || 'this member'} from the workspace?`,
                          confirmLabel: 'Remove',
                          cancelLabel: 'Cancel',
                          variant: 'warning',
                        });
                        if (confirmed) {
                          removeMember.mutate({ workspaceId, userId: member.user_id });
                        }
                      }}
                      className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors inline-flex"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </Tooltip>
                </div>
              </div>
            );
          })}
          {!workspace.members?.length && (
            <div className="text-center py-8 text-muted-foreground">
              <Users className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No members yet</p>
              <p className="text-xs mt-1">Add members to collaborate</p>
            </div>
          )}
        </div>
      </motion.div>

      {/* Edit Workspace Dialog */}
      {showEditWorkspace && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          onClick={() => setShowEditWorkspace(false)}
        >
          <motion.div
            className="w-full max-w-md rounded-2xl bg-card/95 backdrop-blur-xl border border-border/50 shadow-2xl overflow-hidden"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-1 bg-primary" />
            <div className="p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">Edit Workspace</h3>
                <button
                  onClick={() => setShowEditWorkspace(false)}
                  className="p-1 rounded hover:bg-muted transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="space-y-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">Name</label>
                  <Input
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    placeholder="Workspace name"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">Description</label>
                  <Input
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    placeholder="Optional description"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setShowEditWorkspace(false)}>Cancel</Button>
                <Button
                  onClick={() => {
                    updateWorkspace.mutate(
                      { workspaceId, data: editForm },
                      {
                        onSuccess: () => {
                          setShowEditWorkspace(false);
                        },
                      }
                    );
                  }}
                  loading={updateWorkspace.isPending}
                >
                  Save
                </Button>
              </div>
            </div>
          </motion.div>
        </div>
      )}

      {/* Confirmation Dialog */}
      {dialog}
    </div>
  );
}
