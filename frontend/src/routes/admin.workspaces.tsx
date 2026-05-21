import { createFileRoute } from '@tanstack/react-router';
import { FolderOpen, Pencil, Trash2, Users, HardDrive } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useAdminWorkspaces, useAdminWorkspaceActions, type AdminWorkspace } from '../hooks/use-admin-workspaces';
import { useDataTable } from '../hooks/use-data-table';
import { useThemeStore } from '../stores/theme-store';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { usePageGuard } from '../hooks/use-page-guard';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { formatDate } from '../lib/utils';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Button } from '../components/ui/button';
import { Tooltip } from '../components/ui/tooltip';
import { Checkbox } from '../components/ui/checkbox';
import { motion } from 'framer-motion';

export const Route = createFileRoute('/admin/workspaces')({
  component: WorkspacesAdminPage,
});

function WorkspacesAdminPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ADMIN_ACCESS });
  if (!allowed) return null;

  const hasPermission = useAuthStore((state) => state.hasPermission);
  const canManageWorkspaces = hasPermission(PERMISSIONS.WORKSPACES_MANAGE);

  const { confirm, dialog } = useConfirmDialog();

  const {
    state: tableState,
    setPage,
    setLimit,
    setSort,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 20, defaultSortBy: 'created_at' });

  const [sorting, setSorting] = useState<SortingState>([
    { id: tableState.sortBy, desc: tableState.sortOrder === 'desc' }
  ]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

  // Sync React Table column filters with API filter state
  const prevColumnFiltersRef = useRef<ColumnFiltersState>([]);
  useEffect(() => {
    const currentIds = new Set(columnFilters.map(f => f.id));

    columnFilters.forEach((filter) => {
      if (filter.value !== undefined && filter.value !== null) {
        setFilter(filter.id, String(filter.value));
      }
    });

    prevColumnFiltersRef.current.forEach((filter) => {
      if (!currentIds.has(filter.id)) {
        setFilter(filter.id, null);
      }
    });

    prevColumnFiltersRef.current = columnFilters;
  }, [columnFilters, setFilter]);

  const { data, isLoading, isError, error } = useAdminWorkspaces({
    search: tableState.search,
    status: tableState.filters.status as string | undefined,
    page: tableState.page,
    limit: tableState.limit,
    sort_by: tableState.sortBy,
    sort_order: tableState.sortOrder,
  });

  const workspaces = data?.workspaces || [];
  const pagination = data?.pagination;

  // Edit dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingWorkspace, setEditingWorkspace] = useState<AdminWorkspace | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    is_active: true,
  });

  const { updateWorkspace, deleteWorkspace } = useAdminWorkspaceActions();

  const openEditDialog = (workspace: AdminWorkspace) => {
    setEditingWorkspace(workspace);
    setFormData({
      name: workspace.name,
      description: workspace.description || '',
      is_active: workspace.is_active,
    });
    setDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingWorkspace) return;

    updateWorkspace.mutate({
      workspaceId: editingWorkspace.id,
      name: formData.name,
      description: formData.description || undefined,
      is_active: formData.is_active,
    }, {
      onSuccess: () => setDialogOpen(false),
    });
  };

  const handleDelete = async (workspace: AdminWorkspace) => {
    const confirmed = await confirm({
      title: 'Delete Workspace',
      description: `Are you sure you want to delete "${workspace.name}"? This action cannot be undone and will remove all members, volumes, and invitations.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (confirmed) {
      deleteWorkspace.mutate(workspace.id);
    }
  };

  // Stats
  const totalWorkspaces = pagination?.total || 0;
  const activeWorkspaces = workspaces.filter(w => w.is_active).length;
  const totalMembers = workspaces.reduce((sum, w) => sum + (w.member_count || 0), 0);
  const totalVolumes = workspaces.reduce((sum, w) => sum + (w.volume_count || 0), 0);

  const stats = [
    { title: 'Workspaces', value: totalWorkspaces, icon: FolderOpen, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: activeWorkspaces, icon: FolderOpen, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Members', value: totalMembers, icon: Users, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Volumes', value: totalVolumes, icon: HardDrive, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

  const columns: ColumnDef<AdminWorkspace>[] = [
    {
      accessorKey: 'name',
      header: 'Workspace',
      cell: ({ row }) => {
        const w = row.original;
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded flex-shrink-0 bg-primary/10">
              <FolderOpen className="w-4 h-4 text-primary" />
            </div>
            <div>
              <div className="font-medium">{w.name}</div>
              <code className="text-[10px] text-muted-foreground">{w.id}</code>
              {w.description && (
                <div className="text-xs text-muted-foreground line-clamp-1 max-w-[200px]">{w.description}</div>
              )}
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'owner_username',
      header: 'Owner',
      cell: ({ row }) => {
        const w = row.original;
        return (
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
              <span className="text-[10px] font-medium text-primary">
                {(w.owner_name || w.owner_username || '?').slice(0, 2).toUpperCase()}
              </span>
            </div>
            <div>
              <div className="text-sm">{w.owner_name || w.owner_username}</div>
              {w.owner_username && w.owner_name && w.owner_name !== w.owner_username && (
                <div className="text-xs text-muted-foreground">@{w.owner_username}</div>
              )}
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'member_count',
      header: 'Members',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5 text-sm">
          <Users className="w-3.5 h-3.5 text-muted-foreground" />
          <span>{row.getValue('member_count') || 0}</span>
        </div>
      ),
    },
    {
      accessorKey: 'volume_count',
      header: 'Volumes',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5 text-sm">
          <HardDrive className="w-3.5 h-3.5 text-muted-foreground" />
          <span>{row.getValue('volume_count') || 0}</span>
        </div>
      ),
    },
    {
      accessorKey: 'is_active',
      header: 'Status',
      cell: ({ row }) => {
        const isActive = row.getValue('is_active');
        return (
          <StatusBadge
            status={isActive ? 'running' : 'stopped'}
            label={isActive ? 'Active' : 'Inactive'}
          />
        );
      },

    },
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: ({ row }) => formatDate(row.getValue('created_at') as string),
    },
    ...(canManageWorkspaces ? [{
      id: 'actions' as const,
      header: 'Actions',
      cell: ({ row }: { row: { original: AdminWorkspace } }) => (
        <div className="flex items-center gap-1">
          <Tooltip content="Edit">
            <motion.button
              onClick={() => openEditDialog(row.original)}
              className="inline-flex p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
            >
              <Pencil className="w-4 h-4" />
            </motion.button>
          </Tooltip>
          <Tooltip content="Delete">
            <motion.button
              onClick={() => handleDelete(row.original)}
              disabled={deleteWorkspace.isPending}
              className="inline-flex p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </motion.button>
          </Tooltip>
        </div>
      ),
      enableSorting: false,
      size: 80,
    } satisfies ColumnDef<AdminWorkspace>] : []),
  ];

  const filters = [
    {
      key: 'status',
      label: 'Status',
      options: [
        { label: 'All', value: 'all' },
        { label: 'Active', value: 'active' },
        { label: 'Inactive', value: 'inactive' },
      ],
    },
  ];

  const mobileCardRenderer = (w: AdminWorkspace) => (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{w.name}</div>
        <StatusBadge
          status={w.is_active ? 'running' : 'stopped'}
          label={w.is_active ? 'Active' : 'Inactive'}
        />
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <code className="text-[10px]">{w.id}</code>
        <span>@{w.owner_username}</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">
          {w.member_count || 0} members
        </span>
        <span className="text-muted-foreground">
          {w.volume_count || 0} volumes
        </span>
      </div>
      {canManageWorkspaces && (
        <div className="flex items-center justify-between pt-1">
          <span className="text-sm text-muted-foreground">
            {w.created_at ? formatDate(w.created_at) : '-'}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => openEditDialog(w)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
            >
              <Pencil className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleDelete(w)}
              className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors inline-flex"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <>
      <ResourcePageLayout
        title="Workspaces"
        subtitle="Manage all platform workspaces"
        icon={FolderOpen}
        backTo="/admin"
        stats={stats}
      >
        <DataTable
          columns={columns}
          data={workspaces}
          totalCount={pagination?.total || 0}
          pageCount={pagination?.total_pages || 1}
          page={tableState.page}
          limit={tableState.limit}
          sorting={sorting}
          rowSelection={rowSelection}
          columnFilters={columnFilters}
          columnVisibility={columnVisibility}
          globalFilter={tableState.search}
          isLoading={isLoading}
          isError={isError}
          errorMessage={error?.message}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onSortingChange={(newSorting) => {
            setSorting(newSorting);
            if (newSorting.length > 0) {
              setSort(newSorting[0].id, newSorting[0].desc ? 'desc' : 'asc');
            }
          }}
          onRowSelectionChange={setRowSelection}
          onColumnFiltersChange={setColumnFilters}
          onColumnVisibilityChange={setColumnVisibility}
          onGlobalFilterChange={setSearch}
          getRowId={(row) => row.id}
          filters={filters}
          searchable
          searchPlaceholder="Search workspaces..."
          density={useThemeStore().density}
          mobileCardRenderer={mobileCardRenderer}
        />
      </ResourcePageLayout>

      {canManageWorkspaces && (
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Edit Workspace: {editingWorkspace?.name}</DialogTitle>
              <DialogDescription>
                Update workspace details.
              </DialogDescription>
            </DialogHeader>
            <form id="workspace-form" onSubmit={handleSubmit} className="space-y-4 mt-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Name</label>
                <Input
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Workspace name"
                  required
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Workspace description"
                  rows={3}
                />
              </div>
              <label className="flex items-center gap-3 cursor-pointer group">
                <Checkbox
                  checked={formData.is_active}
                  onChange={(checked) => setFormData({ ...formData, is_active: checked })}
                />
                <span className="text-sm">Active</span>
              </label>
            </form>
            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" form="workspace-form" loading={updateWorkspace.isPending}>
                Update
              </Button>
            </DialogFooter>
            <DialogClose onClick={() => setDialogOpen(false)} />
          </DialogContent>
        </Dialog>
      )}

      {dialog}
    </>
  );
}
