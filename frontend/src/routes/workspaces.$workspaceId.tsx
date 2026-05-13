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
} from 'lucide-react';
import {
  useWorkspace,
  useUpdateWorkspace,
  useAddWorkspaceMember,
  useRemoveWorkspaceMember,
  useUpdateMemberRole,
  useAddWorkspaceVolume,
  useRemoveWorkspaceVolume,
} from '../hooks/use-workspaces';
import { useVolumes } from '../hooks/use-volumes';
import { useUsers } from '../hooks/use-users';
import { springs } from '../lib/animations';
import { cn, formatBytes } from '../lib/utils';
import { Button } from '../components/ui/button';
import { StatCard } from '../components/data/stat-card';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectItem } from '../components/ui/select';
import { Combobox } from '../components/ui/combobox';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { Tooltip } from '../components/ui/tooltip';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
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
  const { data: volumesData } = useVolumes();
  const updateWorkspace = useUpdateWorkspace();
  const addMember = useAddWorkspaceMember();
  const removeMember = useRemoveWorkspaceMember();
  const updateRole = useUpdateMemberRole();
  const addVolume = useAddWorkspaceVolume();
  const removeVolume = useRemoveWorkspaceVolume();
  const { confirm, dialog } = useConfirmDialog();

  const [showAddMember, setShowAddMember] = useState(false);
  const [showAddVolume, setShowAddVolume] = useState(false);
  const [showEditWorkspace, setShowEditWorkspace] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedRole, setSelectedRole] = useState('read_write');
  const [selectedVolumeId, setSelectedVolumeId] = useState('');
  const [selectedVolumeRole, setSelectedVolumeRole] = useState('read_write');
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

  const handleAddVolume = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedVolumeId) return;
    
    addVolume.mutate(
      { workspaceId, volumeId: selectedVolumeId, role: selectedVolumeRole },
      {
        onSuccess: () => {
          setShowAddVolume(false);
          setSelectedVolumeId('');
          setSelectedVolumeRole('read_write');
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

  const availableVolumes = volumesData?.filter(
    (v: any) => !workspace.volumes?.some((wv: any) => wv.volume_id === v.id)
  ) || [];

  const volumeOptions = availableVolumes.map((vol: any) => ({
    value: vol.id,
    label: `${vol.display_name} (${vol.server_count} servers)`,
  }));

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
      >
        <div className="flex items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3 min-w-0">
            <Tooltip content="Back to workspaces">
              <Link
                to="/workspaces"
                className="p-2 rounded-lg hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors flex-shrink-0 inline-flex"
              >
                <ArrowLeft className="w-4 h-4" />
              </Link>
            </Tooltip>
            <div className="p-2 rounded-xl bg-primary/10 shrink-0">
              <FolderOpen className="w-4 h-4 text-primary" />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-bold truncate">{workspace.name}</h1>
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
              className="gap-1.5 flex-shrink-0"
            >
              <Pencil className="w-3.5 h-3.5" />
              Edit
            </Button>
          </Tooltip>
        </div>

        {/* Description */}
        {workspace.description && (
          <div className="rounded-xl bg-muted/30 border border-border/30 p-4 mb-4">
            <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
              {workspace.description}
            </p>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard
            title="Volumes"
            value={workspace.volumes?.length || 0}
            icon={HardDrive}
            iconColor="text-blue-400"
            bgColor="bg-blue-500/10"
            variant="compact"
          />
          <StatCard
            title="Members"
            value={workspace.members?.length || 0}
            icon={Users}
            iconColor="text-violet-400"
            bgColor="bg-violet-500/10"
            variant="compact"
          />
          <StatCard
            title="Status"
            value={workspace.is_active ? 'Active' : 'Inactive'}
            icon={Shield}
            iconColor={workspace.is_active ? 'text-emerald-400' : 'text-muted-foreground'}
            bgColor={workspace.is_active ? 'bg-emerald-500/10' : 'bg-muted/50'}
            variant="compact"
          />
        </div>
      </motion.div>

      {/* Volumes Section */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35, ...springs.gentle }}
      >
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold">Volumes</h3>
          </div>
          <Button
            size="sm"
            onClick={() => setShowAddVolume(!showAddVolume)}
            className="gap-1"
          >
            <Plus className="w-3.5 h-3.5" />
            Add Volume
          </Button>
        </div>

        {showAddVolume && (
          <form onSubmit={handleAddVolume} className="mb-4 p-4 rounded-xl bg-surface/50 border border-border/50 space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">Volume</label>
                <Combobox
                  value={selectedVolumeId}
                  onChange={setSelectedVolumeId}
                  options={volumeOptions}
                  placeholder="Select volume..."
                  searchPlaceholder="Search volumes..."
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">Access Role</label>
                <Select
                  value={selectedVolumeRole}
                  onChange={setSelectedVolumeRole}
                  placeholder="Select role..."
                >
                  <SelectItem value="read_write">Read-Write</SelectItem>
                  <SelectItem value="read_only">Read-Only</SelectItem>
                </Select>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button type="submit" size="sm" loading={addVolume.isPending}>Add</Button>
              <Button type="button" variant="outline" size="sm" onClick={() => setShowAddVolume(false)}>
                Cancel
              </Button>
            </div>
          </form>
        )}

        <div className="space-y-2">
          {workspace.volumes?.map((wv: any) => (
            <div
              key={wv.volume_id}
              className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="p-1.5 rounded flex-shrink-0 bg-primary/10">
                  <HardDrive className="w-3.5 h-3.5 text-primary" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{wv.volume?.display_name || 'Unnamed Volume'}</p>
                  <p className="text-xs text-muted-foreground">
                    {wv.volume?.size_bytes != null ? formatBytes(wv.volume.size_bytes) : 'Size unknown'}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className={cn("text-xs px-2 py-0.5 rounded-full", roleColors[wv.role as keyof typeof roleColors])}>
                  {roleLabels[wv.role as keyof typeof roleLabels] || wv.role}
                </span>
                <Tooltip content="Remove volume">
                  <button
                    onClick={async () => {
                      const confirmed = await confirm({
                        title: 'Remove Volume',
                        description: `Are you sure you want to remove this volume from the workspace?`,
                        confirmLabel: 'Remove',
                        cancelLabel: 'Cancel',
                        variant: 'warning',
                      });
                      if (confirmed) {
                        removeVolume.mutate({ workspaceId, volumeId: wv.volume_id });
                      }
                    }}
                    className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors inline-flex"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </Tooltip>
              </div>
            </div>
          ))}
          {!workspace.volumes?.length && (
            <div className="text-center py-8 text-muted-foreground">
              <HardDrive className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No volumes yet</p>
              <p className="text-xs mt-1">Add volumes to share with workspace members</p>
            </div>
          )}
        </div>
      </motion.div>

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
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">User</label>
                <Combobox
                  value={selectedUserId}
                  onChange={setSelectedUserId}
                  options={userOptions}
                  placeholder="Select user..."
                  searchPlaceholder="Search users..."
                />
              </div>
              <div className="space-y-2">
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
      <Dialog open={showEditWorkspace} onOpenChange={setShowEditWorkspace}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Workspace</DialogTitle>
            <DialogDescription>Update workspace details.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Name</label>
              <Input
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                placeholder="Workspace name"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Textarea
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                placeholder="Optional description"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
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
          </DialogFooter>
          <DialogClose onClick={() => setShowEditWorkspace(false)} />
        </DialogContent>
      </Dialog>

      {/* Confirmation Dialog */}
      {dialog}
    </div>
  );
}
