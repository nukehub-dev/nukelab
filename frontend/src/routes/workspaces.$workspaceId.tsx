import { createFileRoute } from '@tanstack/react-router';
import { useState, useEffect, useRef } from 'react';
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
  Mail,
  Check,
  X,
  Clock,
  LogOut,
  Crown,
  Activity,
  AlertCircle,
} from 'lucide-react';
import {
  useWorkspace,
  useUpdateWorkspace,
  useRemoveWorkspaceMember,
  useUpdateMemberRole,
  useAddWorkspaceVolume,
  useRemoveWorkspaceVolume,
  useUpdateVolumeRole,
  useInviteWorkspaceMember,
  useAcceptInvitation,
  useRejectInvitation,
  useCancelInvitation,
  useLeaveWorkspace,
  useTransferOwnership,
  useWorkspaceActivity,
  useWorkspaceMembers,
  useWorkspaceVolumes,
  useWorkspaceInvitations,
} from '../hooks/use-workspaces';
import { useVolumes } from '../hooks/use-volumes';
import { useDiscoverUsers, usePublicProfile } from '../hooks/use-users';
import { useAuthStore } from '../stores/auth-store';
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
import { DataTable } from '../components/data/data-table';
import { useDataTable } from '../hooks/use-data-table';
import { Link } from '@tanstack/react-router';
import type { ColumnDef, SortingState, ColumnFiltersState, VisibilityState } from '@tanstack/react-table';
import type { WorkspaceMember, WorkspaceVolume } from '../hooks/use-workspaces';
import type { WorkspaceActivity } from '../types/api';

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

const volumeRoleLabels = {
  read_write: 'Read-Write',
  read_only: 'Read-Only',
};

const roleColors = {
  admin: 'text-purple-400 bg-purple-400/10',
  read_write: 'text-blue-400 bg-blue-400/10',
  read_only: 'text-gray-400 bg-gray-400/10',
};

function WorkspaceDetailPage() {
  const { workspaceId } = Route.useParams();
  const { data: workspace, isLoading } = useWorkspace(workspaceId);
  const { data: discoverableUsers } = useDiscoverUsers();
  const { data: volumesData } = useVolumes();
  const updateWorkspace = useUpdateWorkspace();
  const removeMember = useRemoveWorkspaceMember();
  const updateRole = useUpdateMemberRole();
  const addVolume = useAddWorkspaceVolume();
  const removeVolume = useRemoveWorkspaceVolume();
  const updateVolumeRole = useUpdateVolumeRole();
  const inviteMember = useInviteWorkspaceMember();
  const acceptInvitation = useAcceptInvitation();
  const rejectInvitation = useRejectInvitation();
  const cancelInvitation = useCancelInvitation();
  const leaveWorkspace = useLeaveWorkspace();
  const transferOwnership = useTransferOwnership();
  const { confirm, dialog } = useConfirmDialog();
  const currentUser = useAuthStore((state) => state.user);
  const navigate = Route.useNavigate();

  const [showInviteMember, setShowInviteMember] = useState(false);
  const [showAddVolume, setShowAddVolume] = useState(false);
  const [showEditWorkspace, setShowEditWorkspace] = useState(false);
  const [showTransferOwnership, setShowTransferOwnership] = useState(false);
  const [selectedMember, setSelectedMember] = useState<WorkspaceMember | null>(null);
  const [selectedVolume, setSelectedVolume] = useState<WorkspaceVolume | null>(null);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedRole, setSelectedRole] = useState('read_write');
  const [selectedVolumeId, setSelectedVolumeId] = useState('');
  const [selectedVolumeRole, setSelectedVolumeRole] = useState('read_write');
  const [editForm, setEditForm] = useState({ name: '', description: '' });
  const [transferTargetId, setTransferTargetId] = useState('');

  // ─── Members DataTable State ───
  const membersTable = useDataTable({ defaultLimit: 20, defaultSortBy: 'joined_at' });
  const [membersSorting, setMembersSorting] = useState<SortingState>([{ id: 'joined_at', desc: true }]);
  const [membersRowSelection, setMembersRowSelection] = useState<Record<string, boolean>>({});
  const [membersColumnFilters, setMembersColumnFilters] = useState<ColumnFiltersState>([]);
  const [membersColumnVisibility, setMembersColumnVisibility] = useState<VisibilityState>({});

  const prevMembersColumnFilters = useRef<ColumnFiltersState>([]);
  useEffect(() => {
    const currentIds = new Set(membersColumnFilters.map((f) => f.id));
    membersColumnFilters.forEach((filter) => {
      if (filter.value !== undefined && filter.value !== null) {
        membersTable.setFilter(filter.id, String(filter.value));
      }
    });
    prevMembersColumnFilters.current.forEach((filter) => {
      if (!currentIds.has(filter.id)) {
        membersTable.setFilter(filter.id, null);
      }
    });
    prevMembersColumnFilters.current = membersColumnFilters;
  }, [membersColumnFilters, membersTable]);

  const { data: membersData, isLoading: membersLoading } = useWorkspaceMembers(workspaceId, {
    page: membersTable.state.page,
    limit: membersTable.state.limit,
    sort_by: membersSorting[0]?.id,
    sort_order: membersSorting[0]?.desc ? 'desc' : 'asc',
    search: membersTable.state.search,
    role: membersTable.state.filters.role as string,
  });

  // Fetch all members for forms (high limit)
  const { data: allMembersData } = useWorkspaceMembers(workspaceId, { limit: 1000 });
  const { data: invitationsData } = useWorkspaceInvitations(workspaceId);

  // ─── Volumes DataTable State ───
  const volumesTable = useDataTable({ defaultLimit: 20, defaultSortBy: 'added_at' });
  const [volumesSorting, setVolumesSorting] = useState<SortingState>([{ id: 'added_at', desc: true }]);
  const [volumesRowSelection, setVolumesRowSelection] = useState<Record<string, boolean>>({});
  const [volumesColumnFilters, setVolumesColumnFilters] = useState<ColumnFiltersState>([]);
  const [volumesColumnVisibility, setVolumesColumnVisibility] = useState<VisibilityState>({});

  const { data: volumesDataTable, isLoading: volumesLoading } = useWorkspaceVolumes(workspaceId, {
    page: volumesTable.state.page,
    limit: volumesTable.state.limit,
    sort_by: volumesSorting[0]?.id,
    sort_order: volumesSorting[0]?.desc ? 'desc' : 'asc',
    search: volumesTable.state.search,
  });

  // Fetch all workspace volumes for forms
  const { data: allWorkspaceVolumes } = useWorkspaceVolumes(workspaceId, { limit: 1000 });

  const handleInviteMember = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUserId) return;

    inviteMember.mutate(
      { workspaceId, userId: selectedUserId, role: selectedRole },
      {
        onSuccess: () => {
          setShowInviteMember(false);
          setSelectedUserId('');
          setSelectedRole('read_write');
        },
      }
    );
  };

  const handleAddVolume = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedVolumeId) return;

    const selectedVolume = availableVolumes.find((v: any) => v.id === selectedVolumeId);
    const isHomeVolume = selectedVolume && selectedVolume.is_home_volume;
    const isMountedOnServer = selectedVolume && selectedVolume.server_count > 0;

    if (isHomeVolume) {
      const confirmed = await confirm({
        title: 'Share Home Directory Volume?',
        description: `This volume is or was mounted as your home directory. Everyone in this workspace will be able to read and modify its contents.`,
        confirmLabel: 'Share Anyway',
        cancelLabel: 'Cancel',
        variant: 'warning',
        typeToConfirm: 'YES',
        customContent: (
          <div className="space-y-3">
            <div className="rounded-md bg-amber-500/5 border border-amber-500/20 p-3">
              <p className="text-xs font-medium text-amber-400 uppercase tracking-wider mb-2">Exposed data</p>
              <ul className="text-sm text-amber-200/80 list-disc list-inside space-y-0.5">
                <li>Personal files, dotfiles, shell configuration</li>
                <li>SSH keys and credentials</li>
                <li>Shell history, logs, cached data</li>
              </ul>
            </div>
            <div className="rounded-md bg-blue-500/5 border border-blue-500/20 p-3">
              <p className="text-xs font-medium text-blue-400 uppercase tracking-wider mb-2">Recommended alternatives</p>
              <ul className="text-sm text-blue-200/80 list-disc list-inside space-y-0.5">
                <li>Create a new volume mounted at /data or /project for shared work</li>
                <li>Deploy a new server with a separate data volume</li>
              </ul>
              <Link
                to="/servers"
                className="inline-flex items-center gap-1 text-sm font-medium text-blue-400 hover:text-blue-300 mt-2"
                onClick={() => setShowAddVolume(false)}
              >
                Go to Servers to deploy with a dedicated data volume →
              </Link>
            </div>
          </div>
        ),
      });
      if (!confirmed) return;
    } else if (isMountedOnServer) {
      const confirmed = await confirm({
        title: 'Share Active Volume?',
        description: `This volume (${selectedVolume.display_name}) is currently mounted on ${selectedVolume.server_count} server(s). Sharing it may allow workspace members to access or modify files that those servers are actively using. Are you sure you want to proceed?`,
        confirmLabel: 'Share Anyway',
        cancelLabel: 'Cancel',
        variant: 'warning',
      });
      if (!confirmed) return;
    }

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

  const handleLeaveWorkspace = async () => {
    const confirmed = await confirm({
      title: 'Leave Workspace',
      description: `Are you sure you want to leave "${workspace?.name}"? You will lose access to all shared volumes.`,
      confirmLabel: 'Leave',
      cancelLabel: 'Cancel',
      variant: 'warning',
    });
    if (confirmed) {
      leaveWorkspace.mutate(workspaceId, {
        onSuccess: () => {
          navigate({ to: '/workspaces' });
        },
      });
    }
  };

  const handleTransferOwnership = (e: React.FormEvent) => {
    e.preventDefault();
    if (!transferTargetId) return;

    transferOwnership.mutate(
      { workspaceId, userId: transferTargetId },
      {
        onSuccess: () => {
          setShowTransferOwnership(false);
          setTransferTargetId('');
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
            Back to workspaces
          </Link>
        </div>
      </div>
    );
  }

  const isOwner = workspace.owner_id === currentUser?.id;
  const myMembership = workspace.my_membership;
  const isAdmin = isOwner || myMembership?.role === 'admin';
  const isMember = isOwner || !!myMembership;
  const hasPendingInvite = workspace.my_invitation?.status === 'pending';

  // If user has a pending invitation, show accept/reject UI
  if (hasPendingInvite) {
    const inviterName = workspace.my_invitation?.inviter_display_name || workspace.my_invitation?.inviter_username || 'Someone';
    const inviterAvatar = workspace.my_invitation?.inviter_avatar_url;
    const roleLabel = roleLabels[workspace.my_invitation?.role as keyof typeof roleLabels] || workspace.my_invitation?.role;
    const invitedAt = workspace.my_invitation?.created_at
      ? new Date(workspace.my_invitation.created_at).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
      : '';

    return (
      <div className="min-h-screen p-6 lg:p-10 flex items-start justify-center pt-20">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-lg w-full"
        >
          <div className="bubble p-8 space-y-6">
            {/* Inviter */}
            <div className="flex items-center gap-4">
              {inviterAvatar ? (
                <img
                  src={inviterAvatar}
                  alt={inviterName}
                  className="w-14 h-14 rounded-full object-cover ring-2 ring-border/50"
                />
              ) : (
                <div className="w-14 h-14 rounded-full bg-gradient-to-br from-primary/30 to-primary/10 ring-2 ring-primary/30 flex items-center justify-center text-xl font-bold text-primary">
                  {inviterName.charAt(0).toUpperCase()}
                </div>
              )}
              <div>
                <p className="text-sm text-muted-foreground">Invitation from</p>
                <p className="text-base font-semibold">{inviterName}</p>
                {workspace.my_invitation?.inviter_username && (
                  <p className="text-xs text-muted-foreground">@{workspace.my_invitation.inviter_username}</p>
                )}
              </div>
            </div>

            <div className="h-px bg-border/50" />

            {/* Workspace Info */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-lg bg-primary/10">
                  <FolderOpen className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Workspace</p>
                  <h2 className="text-xl font-bold">{workspace.name}</h2>
                </div>
              </div>
              {workspace.description && (
                <p className="text-sm text-muted-foreground pl-12">{workspace.description}</p>
              )}
            </div>

            {/* Details */}
            <div className="grid grid-cols-3 gap-3">
              <div className="p-3 rounded-xl bg-surface/50 border border-border/50 text-center">
                <p className="text-xs text-muted-foreground mb-1">Role</p>
                <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", roleColors[workspace.my_invitation?.role as keyof typeof roleColors])}>
                  {roleLabel}
                </span>
              </div>
              <div className="p-3 rounded-xl bg-surface/50 border border-border/50 text-center">
                <p className="text-xs text-muted-foreground mb-1">Members</p>
                <p className="text-sm font-semibold">{workspace.member_count || 0}</p>
              </div>
              <div className="p-3 rounded-xl bg-surface/50 border border-border/50 text-center">
                <p className="text-xs text-muted-foreground mb-1">Sent</p>
                <p className="text-sm font-semibold">{invitedAt}</p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <Button
                variant="outline"
                className="flex-1 gap-2"
                onClick={() =>
                  rejectInvitation.mutate(
                    {
                      workspaceId,
                      invitationId: workspace.my_invitation!.id,
                    },
                    {
                      onSuccess: () => {
                        navigate({ to: '/workspaces' });
                      },
                    }
                  )
                }
                loading={rejectInvitation.isPending}
              >
                <X className="w-4 h-4" />
                Decline
              </Button>
              <Button
                className="flex-1 gap-2"
                onClick={() =>
                  acceptInvitation.mutate({
                    workspaceId,
                    invitationId: workspace.my_invitation!.id,
                  })
                }
                loading={acceptInvitation.isPending}
              >
                <Check className="w-4 h-4" />
                Join Workspace
              </Button>
            </div>
          </div>
        </motion.div>
      </div>
    );
  }

  // Only members (owner + accepted members) see the full workspace
  if (!isMember) {
    return (
      <div className="min-h-screen p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <FolderOpen className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
          <h2 className="text-lg font-semibold mb-2">No access</h2>
          <p className="text-muted-foreground mb-4">
            You don't have access to this workspace.
          </p>
          <Link to="/workspaces" className="text-primary hover:underline">
            Back to workspaces
          </Link>
        </div>
      </div>
    );
  }

  const availableUsers = discoverableUsers?.filter(
    (u) =>
      u.id !== currentUser?.id &&
      !allMembersData?.members?.some((m) => m.user_id === u.id) &&
      !invitationsData?.some((i) => i.user_id === u.id)
  ) || [];

  const userOptions = availableUsers.map((user) => ({
    value: user.id,
    label: `${user.display_name || user.username} (@${user.username})`,
    image: user.avatar_url,
  }));

  const availableVolumes = volumesData?.filter(
    (v: any) =>
      v.owner_id === currentUser?.id &&
      !allWorkspaceVolumes?.volumes?.some((wv) => wv.volume_id === v.id)
  ) || [];

  const volumeOptions = availableVolumes.map((vol: any) => ({
    value: vol.id,
    label: `${vol.display_name} (${vol.server_count} servers)`,
  }));

  // ─── Members Table Columns ───
  const memberColumns: ColumnDef<WorkspaceMember>[] = [
    {
      accessorKey: 'username',
      header: 'Member',
      cell: ({ row }) => {
        const member = row.original;
        const RoleIcon = roleIcons[member.role as keyof typeof roleIcons] || User;
        return (
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSelectedMember(member)}
              className={cn("p-1.5 rounded flex-shrink-0", roleColors[member.role as keyof typeof roleColors])}
            >
              <RoleIcon className="w-3.5 h-3.5" />
            </button>
            <div>
              <button
                onClick={() => setSelectedMember(member)}
                className="text-sm font-medium hover:underline text-left"
              >
                {member.username || 'Unknown'}
              </button>
              <p className="text-xs text-muted-foreground">{member.email}</p>
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'role',
      header: 'Role',
      cell: ({ row }) => {
        const member = row.original;
        const isOwnerMember = workspace.owner_id === member.user_id;
        const isSelf = currentUser?.id === member.user_id;
        const canManage = isAdmin && !isOwnerMember && !isSelf;
        return (
          <div className="flex items-center gap-2">
            <span className={cn("text-xs px-2 py-0.5 rounded-full", roleColors[member.role as keyof typeof roleColors])}>
              {isOwnerMember ? 'Owner' : (roleLabels[member.role as keyof typeof roleLabels] || member.role)}
            </span>
            {canManage && (
              <>
                <RoleEditor
                  currentRole={member.role}
                  onChange={(role) => updateRole.mutate({ workspaceId, userId: member.user_id, role })}
                />
                <Tooltip content="Remove member">
                  <button
                    onClick={async () => {
                      const confirmed = await confirm({
                        title: 'Remove Member',
                        description: `Remove ${member.username || 'this member'} from the workspace?`,
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
              </>
            )}
          </div>
        );
      },
    },
  ];

  const memberMobileCardRenderer = (member: WorkspaceMember) => {
    const RoleIcon = roleIcons[member.role as keyof typeof roleIcons] || User;
    const isOwnerMember = workspace.owner_id === member.user_id;
    const isSelf = currentUser?.id === member.user_id;
    const canManage = isAdmin && !isOwnerMember && !isSelf;
    return (
      <div className="p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setSelectedMember(member)}
              className={cn("p-1 rounded flex-shrink-0", roleColors[member.role as keyof typeof roleColors])}
            >
              <RoleIcon className="w-3 h-3" />
            </button>
            <div className="min-w-0">
              <button
                onClick={() => setSelectedMember(member)}
                className="text-sm font-medium hover:underline text-left truncate block"
              >
                {member.username || 'Unknown'}
              </button>
              <p className="text-xs text-muted-foreground truncate">{member.email}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className={cn("text-xs px-1.5 py-0.5 rounded-full", roleColors[member.role as keyof typeof roleColors])}>
              {isOwnerMember ? 'Owner' : (roleLabels[member.role as keyof typeof roleLabels] || member.role)}
            </span>
            {canManage && (
              <>
                <RoleEditor
                  currentRole={member.role}
                  onChange={(role) => updateRole.mutate({ workspaceId, userId: member.user_id, role })}
                />
                <Tooltip content="Remove member">
                  <button
                    onClick={async () => {
                      const confirmed = await confirm({
                        title: 'Remove Member',
                        description: `Remove ${member.username || 'this member'}?`,
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
              </>
            )}
          </div>
        </div>
      </div>
    );
  };

  // ─── Volumes Table Columns ───
  const volumeColumns: ColumnDef<WorkspaceVolume>[] = [
    {
      accessorKey: 'display_name',
      header: 'Volume',
      cell: ({ row }) => {
        const wv = row.original;
        return (
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-1.5 rounded flex-shrink-0 bg-primary/10">
              <HardDrive className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="min-w-0">
              <button
                onClick={() => setSelectedVolume(wv)}
                className="text-sm font-medium truncate hover:underline text-left"
              >
                {wv.volume?.display_name || 'Unnamed Volume'}
              </button>
              <p className="text-xs text-muted-foreground">
                {wv.volume?.size_bytes != null ? formatBytes(wv.volume.size_bytes) : 'Size unknown'}
              </p>
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'owner',
      header: 'Owner',
      cell: ({ row }) => {
        const wv = row.original;
        const owner = wv.volume?.owner;
        return (
          <span className="text-xs text-muted-foreground">
            {owner?.username || 'Unknown'}
          </span>
        );
      },
    },
    {
      accessorKey: 'role',
      header: 'Access',
      cell: ({ row }) => {
        const wv = row.original;
        return (
          <div className="flex items-center gap-2">
            <span className={cn("text-xs px-2 py-0.5 rounded-full", roleColors[wv.role as keyof typeof roleColors])}>
              {volumeRoleLabels[wv.role as keyof typeof volumeRoleLabels] || wv.role}
            </span>
            {isAdmin && (
              <>
                <VolumeRoleEditor
                  currentRole={wv.role}
                  onChange={(role) => updateVolumeRole.mutate({ workspaceId, volumeId: wv.volume_id, role })}
                />
                <Tooltip content="Remove volume">
                  <button
                    onClick={async () => {
                      const confirmed = await confirm({
                        title: 'Remove Volume',
                        description: `Remove this volume from the workspace?`,
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
              </>
            )}
          </div>
        );
      },
    },
  ];

  const volumeMobileCardRenderer = (wv: WorkspaceVolume) => {
    const owner = wv.volume?.owner;
    return (
    <div className="p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1 rounded flex-shrink-0 bg-primary/10">
            <HardDrive className="w-3 h-3 text-primary" />
          </div>
          <div className="min-w-0">
            <button
              onClick={() => setSelectedVolume(wv)}
              className="text-sm font-medium truncate hover:underline text-left block"
            >
              {wv.volume?.display_name || 'Unnamed Volume'}
            </button>
            <p className="text-xs text-muted-foreground">
              {wv.volume?.size_bytes != null ? formatBytes(wv.volume.size_bytes) : 'Size unknown'}
              {owner && (
                <span>{` · ${owner.username}`}</span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={cn("text-xs px-1.5 py-0.5 rounded-full", roleColors[wv.role as keyof typeof roleColors])}>
            {volumeRoleLabels[wv.role as keyof typeof volumeRoleLabels] || wv.role}
          </span>
          {isAdmin && (
            <>
              <VolumeRoleEditor
                currentRole={wv.role}
                onChange={(role) => updateVolumeRole.mutate({ workspaceId, volumeId: wv.volume_id, role })}
              />
              <Tooltip content="Remove volume">
                <button
                  onClick={async () => {
                    const confirmed = await confirm({
                      title: 'Remove Volume',
                      description: `Remove this volume from the workspace?`,
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
            </>
          )}
        </div>
      </div>
    </div>
  );
};

  const memberFilters = [
    {
      key: 'role',
      label: 'Role',
      options: [
        { label: 'Admin', value: 'admin' },
        { label: 'Editor', value: 'read_write' },
        { label: 'Viewer', value: 'read_only' },
      ],
    },
  ];

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
          <div className="flex items-center gap-2 flex-shrink-0">
            {isOwner && (
              <Tooltip content="Transfer ownership">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setTransferTargetId('');
                    setShowTransferOwnership(true);
                  }}
                  className="gap-1.5"
                >
                  <Crown className="w-3.5 h-3.5" />
                  Transfer
                </Button>
              </Tooltip>
            )}
            {isAdmin && (
              <Tooltip content="Edit workspace">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setEditForm({ name: workspace.name, description: workspace.description || '' });
                    setShowEditWorkspace(true);
                  }}
                  className="gap-1.5"
                >
                  <Pencil className="w-3.5 h-3.5" />
                  Edit
                </Button>
              </Tooltip>
            )}
            {isMember && !isOwner && (
              <Tooltip content="Leave workspace">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleLeaveWorkspace}
                  loading={leaveWorkspace.isPending}
                  className="gap-1.5 text-destructive hover:text-destructive"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  Leave
                </Button>
              </Tooltip>
            )}
          </div>
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
            value={workspace.volume_count || 0}
            icon={HardDrive}
            iconColor="text-blue-400"
            bgColor="bg-blue-500/10"
            variant="compact"
          />
          <StatCard
            title="Members"
            value={workspace.member_count || 0}
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
          {isAdmin && (
            <Button
              size="sm"
              onClick={() => {
                setSelectedVolumeId('');
                setSelectedVolumeRole('read_write');
                setShowAddVolume(true);
              }}
              className="gap-1"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Volume
            </Button>
          )}
        </div>

        <DataTable
          columns={volumeColumns}
          data={volumesDataTable?.volumes || []}
          totalCount={volumesDataTable?.pagination?.total || 0}
          pageCount={volumesDataTable?.pagination?.total_pages || 1}
          page={volumesTable.state.page}
          limit={volumesTable.state.limit}
          sorting={volumesSorting}
          rowSelection={volumesRowSelection}
          columnFilters={volumesColumnFilters}
          columnVisibility={volumesColumnVisibility}
          globalFilter={volumesTable.state.search}
          isLoading={volumesLoading}
          onPageChange={volumesTable.setPage}
          onLimitChange={volumesTable.setLimit}
          onSortingChange={(newSorting) => {
            setVolumesSorting(newSorting);
            if (newSorting.length > 0) {
              volumesTable.setSort(newSorting[0].id, newSorting[0].desc ? 'desc' : 'asc');
            }
          }}
          onRowSelectionChange={setVolumesRowSelection}
          onColumnFiltersChange={setVolumesColumnFilters}
          onColumnVisibilityChange={setVolumesColumnVisibility}
          onGlobalFilterChange={volumesTable.setSearch}
          getRowId={(row) => row.volume_id}
          searchable
          searchPlaceholder="Search volumes..."
          mobileCardRenderer={volumeMobileCardRenderer}
          enableRowSelection={false}
          emptyState={
            <div className="text-center py-8 text-muted-foreground">
              <HardDrive className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No volumes yet</p>
              <p className="text-xs mt-1">Add volumes to share with workspace members</p>
            </div>
          }
        />
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
          {isAdmin && (
            <Button
              size="sm"
              onClick={() => {
                setSelectedUserId('');
                setSelectedRole('read_write');
                setShowInviteMember(true);
              }}
              className="gap-1"
            >
              <Mail className="w-3.5 h-3.5" />
              Invite Member
            </Button>
          )}
        </div>

        <DataTable
          columns={memberColumns}
          data={membersData?.members || []}
          totalCount={membersData?.pagination?.total || 0}
          pageCount={membersData?.pagination?.total_pages || 1}
          page={membersTable.state.page}
          limit={membersTable.state.limit}
          sorting={membersSorting}
          rowSelection={membersRowSelection}
          columnFilters={membersColumnFilters}
          columnVisibility={membersColumnVisibility}
          globalFilter={membersTable.state.search}
          isLoading={membersLoading}
          onPageChange={membersTable.setPage}
          onLimitChange={membersTable.setLimit}
          onSortingChange={(newSorting) => {
            setMembersSorting(newSorting);
            if (newSorting.length > 0) {
              membersTable.setSort(newSorting[0].id, newSorting[0].desc ? 'desc' : 'asc');
            }
          }}
          onRowSelectionChange={setMembersRowSelection}
          onColumnFiltersChange={setMembersColumnFilters}
          onColumnVisibilityChange={setMembersColumnVisibility}
          onGlobalFilterChange={membersTable.setSearch}
          getRowId={(row) => row.user_id}
          filters={memberFilters}
          searchable
          searchPlaceholder="Search members..."
          mobileCardRenderer={memberMobileCardRenderer}
          enableRowSelection={false}
          emptyState={
            <div className="text-center py-8 text-muted-foreground">
              <Users className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No members yet</p>
              <p className="text-xs mt-1">Invite members to collaborate</p>
            </div>
          }
        />
      </motion.div>

      {/* Pending Invitations Section */}
      {isAdmin && invitationsData && invitationsData.length > 0 && (
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.45, ...springs.gentle }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Clock className="w-4 h-4 text-amber-400" />
            <h3 className="text-base font-semibold">Pending Invitations</h3>
          </div>
          <div className="space-y-2">
            {invitationsData.map((invitation: any) => (
              <div
                key={invitation.id}
                className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
              >
                <div className="flex items-center gap-3 min-w-0">
                  {invitation.avatar_url ? (
                    <img
                      src={invitation.avatar_url}
                      alt=""
                      className="w-8 h-8 rounded-full object-cover"
                    />
                  ) : (
                    <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-bold text-primary">
                      {(invitation.display_name || invitation.username || '?').charAt(0).toUpperCase()}
                    </div>
                  )}
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">
                      {invitation.display_name || invitation.username || 'Unknown'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      @{invitation.username} · {roleLabels[invitation.role as keyof typeof roleLabels] || invitation.role}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-xs text-muted-foreground">
                    {invitation.expires_at
                      ? (() => {
                          const expires = new Date(invitation.expires_at);
                          const now = new Date();
                          const diffDays = Math.ceil((expires.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
                          if (diffDays < 0) return <span className="text-destructive flex items-center gap-1"><AlertCircle className="w-3 h-3" /> Expired</span>;
                          if (diffDays === 0) return <span className="text-amber-400">Expires today</span>;
                          return `Expires in ${diffDays} day${diffDays > 1 ? 's' : ''}`;
                        })()
                      : `Sent ${invitation.created_at ? new Date(invitation.created_at).toLocaleDateString() : ''}`
                    }
                  </span>
                  <Tooltip content="Cancel invitation">
                    <button
                      onClick={async () => {
                        const confirmed = await confirm({
                          title: 'Cancel Invitation',
                          description: `Cancel invitation to ${invitation.display_name || invitation.username}?`,
                          confirmLabel: 'Cancel Invite',
                          cancelLabel: 'Keep',
                          variant: 'warning',
                        });
                        if (confirmed) {
                          cancelInvitation.mutate({
                            workspaceId,
                            invitationId: invitation.id,
                          });
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
          </div>
        </motion.div>
      )}

      {/* Activity Section */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5, ...springs.gentle }}
      >
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-4 h-4 text-primary" />
          <h3 className="text-base font-semibold">Activity</h3>
        </div>
        <WorkspaceActivityTable workspaceId={workspaceId} />
      </motion.div>

      {/* Edit Workspace Dialog */}
      {isAdmin && (
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
      )}

      {/* Transfer Ownership Dialog */}
      {isOwner && (
        <Dialog open={showTransferOwnership} onOpenChange={setShowTransferOwnership}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Transfer Ownership</DialogTitle>
              <DialogDescription>
                Choose a member to become the new owner. You will be demoted to admin.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleTransferOwnership} className="space-y-4 mt-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">New Owner</label>
                <Combobox
                  value={transferTargetId}
                  onChange={setTransferTargetId}
                  options={allMembersData?.members
                    ?.filter((m) => m.user_id !== currentUser?.id)
                    .map((m) => ({
                      value: m.user_id,
                      label: `${m.username || 'Unknown'}`,
                    })) || []}
                  placeholder="Select member..."
                  searchPlaceholder="Search members..."
                />
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setShowTransferOwnership(false)}>
                  Cancel
                </Button>
                <Button type="submit" loading={transferOwnership.isPending} disabled={!transferTargetId}>
                  Transfer
                </Button>
              </DialogFooter>
            </form>
            <DialogClose onClick={() => setShowTransferOwnership(false)} />
          </DialogContent>
        </Dialog>
      )}

      {/* Invite Member Dialog */}
      {isAdmin && (
        <Dialog open={showInviteMember} onOpenChange={setShowInviteMember}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Invite Member</DialogTitle>
              <DialogDescription>Invite a user to collaborate in this workspace.</DialogDescription>
            </DialogHeader>
            <form onSubmit={handleInviteMember} className="space-y-4 mt-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">User</label>
                <Combobox
                  value={selectedUserId}
                  onChange={setSelectedUserId}
                  options={userOptions}
                  placeholder="Select user..."
                  searchPlaceholder="Search users..."
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Role</label>
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
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setShowInviteMember(false)}>
                  Cancel
                </Button>
                <Button type="submit" loading={inviteMember.isPending} disabled={!selectedUserId}>
                  Send Invite
                </Button>
              </DialogFooter>
            </form>
            <DialogClose onClick={() => setShowInviteMember(false)} />
          </DialogContent>
        </Dialog>
      )}

      {/* Add Volume Dialog */}
      {isAdmin && (
        <Dialog open={showAddVolume} onOpenChange={setShowAddVolume}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add Volume</DialogTitle>
              <DialogDescription>Add a volume to share with workspace members.</DialogDescription>
            </DialogHeader>
            <form onSubmit={handleAddVolume} className="space-y-4 mt-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Volume</label>
                <Combobox
                  value={selectedVolumeId}
                  onChange={setSelectedVolumeId}
                  options={volumeOptions}
                  placeholder="Select volume..."
                  searchPlaceholder="Search volumes..."
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Access Role</label>
                <Select
                  value={selectedVolumeRole}
                  onChange={setSelectedVolumeRole}
                  placeholder="Select role..."
                >
                  <SelectItem value="read_write">Read-Write</SelectItem>
                  <SelectItem value="read_only">Read-Only</SelectItem>
                </Select>
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setShowAddVolume(false)}>
                  Cancel
                </Button>
                <Button type="submit" loading={addVolume.isPending} disabled={!selectedVolumeId}>
                  Add
                </Button>
              </DialogFooter>
            </form>
            <DialogClose onClick={() => setShowAddVolume(false)} />
          </DialogContent>
        </Dialog>
      )}

      {/* User Profile Dialog */}
      <UserProfileDialog
        member={selectedMember}
        onClose={() => setSelectedMember(null)}
      />

      {/* Volume Detail Dialog */}
      <VolumeDetailDialog
        volume={selectedVolume}
        onClose={() => setSelectedVolume(null)}
      />

      {/* Confirmation Dialog */}
      {dialog}
    </div>
  );
}


// ─── Sub-components ─────────────────────────────────────────────────────────

function RoleEditor({ currentRole, onChange }: { currentRole: string; onChange: (role: string) => void }) {
  const [editing, setEditing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setEditing(false);
      }
    };
    if (editing) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [editing]);

  const options = [
    { value: 'admin', label: 'Admin', color: roleColors.admin },
    { value: 'read_write', label: 'Editor', color: roleColors.read_write },
    { value: 'read_only', label: 'Viewer', color: roleColors.read_only },
  ];

  if (editing) {
    return (
      <div ref={ref} className="flex items-center gap-1">
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => {
              if (opt.value !== currentRole) {
                onChange(opt.value);
              }
              setEditing(false);
            }}
            className={cn(
              'text-xs px-2 py-0.5 rounded-full font-medium transition-colors',
              opt.color,
              currentRole === opt.value && 'ring-1 ring-current'
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <Tooltip content="Change role">
      <button
        onClick={() => setEditing(true)}
        className="p-1 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors inline-flex"
      >
        <Pencil className="w-3 h-3" />
      </button>
    </Tooltip>
  );
}

function VolumeRoleEditor({ currentRole, onChange }: { currentRole: string; onChange: (role: string) => void }) {
  const [editing, setEditing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setEditing(false);
      }
    };
    if (editing) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [editing]);

  const options = [
    { value: 'read_write', label: 'RW', title: 'Read-Write', color: roleColors.read_write },
    { value: 'read_only', label: 'RO', title: 'Read-Only', color: roleColors.read_only },
  ];

  if (editing) {
    return (
      <div ref={ref} className="flex items-center gap-1">
        {options.map((opt) => (
          <Tooltip key={opt.value} content={opt.title}>
            <button
              onClick={() => {
                if (opt.value !== currentRole) {
                  onChange(opt.value);
                }
                setEditing(false);
              }}
              className={cn(
                'text-xs px-2 py-0.5 rounded-full font-medium transition-colors',
                opt.color,
                currentRole === opt.value && 'ring-1 ring-current'
              )}
            >
              {opt.label}
            </button>
          </Tooltip>
        ))}
      </div>
    );
  }

  return (
    <Tooltip content="Change access">
      <button
        onClick={() => setEditing(true)}
        className="p-1 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors inline-flex"
      >
        <Pencil className="w-3 h-3" />
      </button>
    </Tooltip>
  );
}

function formatActivityLabel(item: WorkspaceActivity): string {
  const changed = item.details?.changed_fields as string[] | undefined;

  switch (item.action) {
    case 'workspace_updated':
      if (!changed?.length) return 'updated workspace';
      if (changed.length === 1 && changed[0] === 'name') {
        return `renamed workspace to "${item.details?.name}"`;
      }
      if (changed.length === 1 && changed[0] === 'description') {
        return 'updated workspace description';
      }
      if (changed.length === 1 && changed[0] === 'is_active') {
        return item.details?.is_active ? 'activated workspace' : 'deactivated workspace';
      }
      return `updated workspace ${changed.join(', ')}`;
    case 'member_left':
      return 'left the workspace';
    case 'ownership_transferred':
      return 'transferred ownership';
    case 'invitation_sent':
      return 'sent an invitation';
    case 'invitation_accepted':
      return 'accepted an invitation';
    case 'invitation_rejected':
      return 'rejected an invitation';
    case 'invitation_expired':
      return 'invitation expired';
    case 'member_added':
      return 'was added';
    case 'member_removed':
      return 'was removed';
    case 'role_updated':
      return 'role was updated';
    case 'volume_added':
      return 'added a volume';
    case 'volume_removed':
      return 'removed a volume';
    case 'workspace_created':
      return 'created workspace';
    default:
      return item.action;
  }
}

function WorkspaceActivityTable({ workspaceId }: { workspaceId: string }) {
  const table = useDataTable({ defaultLimit: 20, defaultSortBy: 'created_at' });
  const [sorting, setSorting] = useState<SortingState>([{ id: 'created_at', desc: true }]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

  const { data, isLoading } = useWorkspaceActivity(workspaceId, {
    page: table.state.page,
    limit: table.state.limit,
  });

  const activity = data?.activity || [];

  const columns: ColumnDef<WorkspaceActivity>[] = [
    {
      accessorKey: 'actor',
      header: 'Actor',
      cell: ({ row }) => {
        const item = row.original;
        const actorName = item.actor?.display_name || item.actor?.username || 'Someone';
        return (
          <div className="flex items-center gap-2">
            {item.actor?.avatar_url ? (
              <img src={item.actor.avatar_url} alt="" className="w-6 h-6 rounded-full object-cover" />
            ) : (
              <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-xs font-bold text-primary">
                {actorName.charAt(0).toUpperCase()}
              </div>
            )}
            <span className="text-sm font-medium">{actorName}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'action',
      header: 'Action',
      cell: ({ row }) => {
        const item = row.original;
        return (
          <span className="text-sm text-muted-foreground">
            {formatActivityLabel(item)}
          </span>
        );
      },
    },
    {
      accessorKey: 'created_at',
      header: 'Time',
      cell: ({ row }) => {
        const item = row.original;
        return (
          <span className="text-xs text-muted-foreground">
            {item.created_at
              ? new Date(item.created_at).toLocaleString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : ''}
          </span>
        );
      },
    },
  ];

  const mobileCardRenderer = (item: WorkspaceActivity) => {
    const actorName = item.actor?.display_name || item.actor?.username || 'Someone';
    return (
      <div className="p-3">
        <div className="flex items-start gap-2">
          {item.actor?.avatar_url ? (
            <img src={item.actor.avatar_url} alt="" className="w-6 h-6 rounded-full object-cover flex-shrink-0" />
          ) : (
            <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-xs font-bold text-primary flex-shrink-0">
              {actorName.charAt(0).toUpperCase()}
            </div>
          )}
          <div className="min-w-0">
            <p className="text-sm">
              <span className="font-medium">{actorName}</span>{' '}
              <span className="text-muted-foreground">{formatActivityLabel(item)}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              {item.created_at
                ? new Date(item.created_at).toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                : ''}
            </p>
          </div>
        </div>
      </div>
    );
  };

  return (
    <DataTable
      columns={columns}
      data={activity}
      totalCount={data?.pagination?.total || 0}
      pageCount={data?.pagination?.total_pages || 1}
      page={table.state.page}
      limit={table.state.limit}
      sorting={sorting}
      rowSelection={rowSelection}
      columnFilters={columnFilters}
      columnVisibility={columnVisibility}
      globalFilter={table.state.search}
      isLoading={isLoading}
      onPageChange={table.setPage}
      onLimitChange={table.setLimit}
      onSortingChange={(newSorting) => {
        setSorting(newSorting);
        if (newSorting.length > 0) {
          table.setSort(newSorting[0].id, newSorting[0].desc ? 'desc' : 'asc');
        }
      }}
      onRowSelectionChange={setRowSelection}
      onColumnFiltersChange={setColumnFilters}
      onColumnVisibilityChange={setColumnVisibility}
      onGlobalFilterChange={table.setSearch}
      getRowId={(row) => row.id}
      searchable
      searchPlaceholder="Search activity..."
      mobileCardRenderer={mobileCardRenderer}
      enableRowSelection={false}
      emptyState={
        <div className="text-center py-6 text-muted-foreground">
          <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No activity yet</p>
        </div>
      }
    />
  );
}

function UserProfileDialog({ member, onClose }: { member: WorkspaceMember | null; onClose: () => void }) {
  const { data: profile, isLoading } = usePublicProfile(member?.user_id || undefined);

  const formatDateTime = (date: string) =>
    new Date(date).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });

  return (
    <Dialog open={!!member} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="relative overflow-hidden">
        <div className="absolute bottom-0 left-0 w-48 h-48 bg-chart-2/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2 pointer-events-none" />
        <DialogHeader>
          <DialogTitle className="text-base text-muted-foreground font-medium">Member Profile</DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <div className="py-8 space-y-4">
            <div className="h-14 w-14 bg-muted rounded-full animate-pulse" />
            <div className="h-4 bg-muted rounded w-1/2" />
          </div>
        ) : member ? (
          <div className="py-4 space-y-4 relative">
            <div className="flex items-center gap-4">
              {profile?.avatar_url ? (
                <img
                  src={profile.avatar_url}
                  alt={profile.username}
                  className="w-14 h-14 rounded-full object-cover ring-2 ring-border/50 flex-shrink-0"
                />
              ) : (
                <div className="w-14 h-14 rounded-full bg-gradient-to-br from-primary/30 to-primary/10 ring-2 ring-primary/30 flex items-center justify-center text-xl font-bold text-primary flex-shrink-0">
                  {(profile?.display_name || member.username || '?').charAt(0).toUpperCase()}
                </div>
              )}
              <div className="min-w-0">
                <p className="text-lg font-semibold truncate">{profile?.display_name || member.username || 'Unknown'}</p>
                <p className="text-sm text-muted-foreground">@{member.username || 'unknown'}</p>
                <span className={cn(
                  "text-xs px-2 py-0.5 rounded-full mt-1 inline-block",
                  roleColors[member.role as keyof typeof roleColors]
                )}>
                  {roleLabels[member.role as keyof typeof roleLabels] || member.role}
                </span>
              </div>
            </div>

            {profile?.profile?.bio && (
              <p className="text-sm text-muted-foreground">{profile.profile.bio}</p>
            )}

            <div className="divide-y divide-border/50">
              <div className="flex items-center justify-between py-2.5">
                <span className="text-xs text-muted-foreground">Email</span>
                <span className="text-sm font-medium">{member.email || '—'}</span>
              </div>
              {member.joined_at && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Joined</span>
                  <span className="text-sm font-medium">{formatDateTime(member.joined_at)}</span>
                </div>
              )}
              {profile?.created_at && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Member Since</span>
                  <span className="text-sm font-medium">{formatDateTime(profile.created_at)}</span>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="py-8 text-center text-muted-foreground">
            <p>Member not found.</p>
          </div>
        )}
        <DialogClose onClick={onClose} />
      </DialogContent>
    </Dialog>
  );
}

function VolumeDetailDialog({ volume, onClose }: { volume: WorkspaceVolume | null; onClose: () => void }) {
  const vol = volume?.volume;
  const owner = vol?.owner;

  const formatDateTime = (date: string) =>
    new Date(date).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });

  return (
    <Dialog open={!!volume} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="relative overflow-hidden">
        <div className="absolute bottom-0 left-0 w-48 h-48 bg-chart-2/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2 pointer-events-none" />
        <DialogHeader>
          <DialogTitle className="text-base text-muted-foreground font-medium">Volume Details</DialogTitle>
        </DialogHeader>
        {volume ? (
          <div className="py-4 space-y-4 relative">
            <div className="flex items-center gap-4">
              <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
                <HardDrive className="w-6 h-6 text-primary" />
              </div>
              <div className="min-w-0">
                <p className="text-lg font-semibold truncate">{vol?.display_name || 'Unnamed Volume'}</p>
                <p className="text-sm text-muted-foreground">{vol?.name || 'unknown'}</p>
                <span className={cn(
                  "text-xs px-2 py-0.5 rounded-full mt-1 inline-block",
                  roleColors[volume.role as keyof typeof roleColors]
                )}>
                  {volumeRoleLabels[volume.role as keyof typeof volumeRoleLabels] || volume.role}
                </span>
              </div>
            </div>

            {vol?.description && (
              <p className="text-sm text-muted-foreground">{vol.description}</p>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-xl bg-surface/50 border border-border/50 text-center">
                <p className="text-xs text-muted-foreground mb-1">Size</p>
                <p className="text-sm font-semibold">{vol?.size_bytes != null ? formatBytes(vol.size_bytes) : 'Unknown'}</p>
                {vol?.max_size_bytes != null && (
                  <p className="text-[10px] text-muted-foreground mt-0.5">of {formatBytes(vol.max_size_bytes)}</p>
                )}
              </div>
              <div className="p-3 rounded-xl bg-surface/50 border border-border/50 text-center">
                <p className="text-xs text-muted-foreground mb-1">Servers</p>
                <p className="text-sm font-semibold">{vol?.server_count ?? 0}</p>
              </div>
            </div>

            <div className="divide-y divide-border/50">
              <div className="flex items-center justify-between py-2.5">
                <span className="text-xs text-muted-foreground">Status</span>
                <span className="text-sm font-medium capitalize">{vol?.status || 'Unknown'}</span>
              </div>
              {vol?.visibility && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Visibility</span>
                  <span className="text-sm font-medium capitalize">{vol.visibility}</span>
                </div>
              )}
              <div className="flex items-center justify-between py-2.5">
                <span className="text-xs text-muted-foreground">Owner</span>
                <span className="text-sm font-medium">@{owner?.username || 'Unknown'}</span>
              </div>
              {owner?.display_name && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Owner Name</span>
                  <span className="text-sm font-medium">{owner.display_name}</span>
                </div>
              )}
              {vol?.created_at && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Created</span>
                  <span className="text-sm font-medium">{formatDateTime(vol.created_at)}</span>
                </div>
              )}
              {volume.added_at && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Added to Workspace</span>
                  <span className="text-sm font-medium">{formatDateTime(volume.added_at)}</span>
                </div>
              )}
              {vol?.last_mounted_at && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Last Mounted</span>
                  <span className="text-sm font-medium">{formatDateTime(vol.last_mounted_at)}</span>
                </div>
              )}
              {vol?.labels && Object.keys(vol.labels).length > 0 && (
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs text-muted-foreground">Labels</span>
                  <div className="flex gap-1 flex-wrap justify-end">
                    {Object.entries(vol.labels).map(([k, v]) => (
                      <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                        {k}{v ? `:${v}` : ''}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="py-8 text-center text-muted-foreground">
            <p>Volume not found.</p>
          </div>
        )}
        <DialogClose onClick={onClose} />
      </DialogContent>
    </Dialog>
  );
}
