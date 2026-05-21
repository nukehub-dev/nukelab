import { createFileRoute } from '@tanstack/react-router';
import { HardDrive, Pencil, Trash2, Server } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useAdminVolumes, useAdminVolumeActions, type AdminVolume } from '../hooks/use-admin-volumes';
import { useDataTable } from '../hooks/use-data-table';
import { useThemeStore } from '../stores/theme-store';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { usePageGuard } from '../hooks/use-page-guard';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { formatDate, formatBytes } from '../lib/utils';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectItem } from '../components/ui/select';
import { Button } from '../components/ui/button';
import { Tooltip } from '../components/ui/tooltip';
import { motion } from 'framer-motion';

export const Route = createFileRoute('/admin/volumes')({
  component: VolumesAdminPage,
});

function volumeStatusToBadge(status: string): { status: 'running' | 'stopped' | 'pending' | 'warning'; label: string } {
  switch (status) {
    case 'active':
      return { status: 'running', label: 'Active' };
    case 'archived':
      return { status: 'stopped', label: 'Archived' };
    case 'deleting':
      return { status: 'pending', label: 'Deleting' };
    case 'over_limit':
      return { status: 'warning', label: 'Over Limit' };
    default:
      return { status: 'stopped', label: status };
  }
}

function visibilityBadgeClass(visibility: string): string {
  switch (visibility) {
    case 'public':
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
    case 'workspace':
      return 'bg-blue-500/10 text-blue-400 border-blue-500/20';
    default:
      return 'bg-gray-500/10 text-gray-400 border-gray-500/20';
  }
}

function VolumesAdminPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ADMIN_ACCESS });
  if (!allowed) return null;

  const hasPermission = useAuthStore((state) => state.hasPermission);
  const canManageVolumes = hasPermission(PERMISSIONS.VOLUMES_MANAGE);

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

  const { data, isLoading, isError, error } = useAdminVolumes({
    search: tableState.search,
    status: tableState.filters.status as string | undefined,
    visibility: tableState.filters.visibility as string | undefined,
    page: tableState.page,
    limit: tableState.limit,
    sort_by: tableState.sortBy,
    sort_order: tableState.sortOrder,
  });

  const volumes = data?.volumes || [];
  const pagination = data?.pagination;

  // Edit dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingVolume, setEditingVolume] = useState<AdminVolume | null>(null);
  const [formData, setFormData] = useState({
    display_name: '',
    description: '',
    visibility: 'private',
    status: 'active',
    max_size_bytes: undefined as number | undefined,
  });

  const { updateVolume, deleteVolume } = useAdminVolumeActions();

  const openEditDialog = (volume: AdminVolume) => {
    setEditingVolume(volume);
    setFormData({
      display_name: volume.display_name,
      description: volume.description || '',
      visibility: volume.visibility,
      status: volume.status,
      max_size_bytes: volume.max_size_bytes || undefined,
    });
    setDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingVolume) return;

    updateVolume.mutate({
      volumeId: editingVolume.id,
      display_name: formData.display_name,
      description: formData.description || undefined,
      visibility: formData.visibility,
      status: formData.status,
      max_size_bytes: formData.max_size_bytes,
    }, {
      onSuccess: () => setDialogOpen(false),
    });
  };

  const handleDelete = async (volume: AdminVolume) => {
    const confirmed = await confirm({
      title: 'Delete Volume',
      description: `Are you sure you want to delete "${volume.display_name || volume.name}"? This action cannot be undone.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (confirmed) {
      deleteVolume.mutate(volume.id);
    }
  };

  // Stats
  const totalVolumes = pagination?.total || 0;
  const totalSize = volumes.reduce((sum, v) => sum + (v.size_bytes || 0), 0);
  const activeVolumes = volumes.filter(v => v.status === 'active').length;
  const publicVolumes = volumes.filter(v => v.visibility === 'public').length;

  const stats = [
    { title: 'Volumes', value: totalVolumes, icon: HardDrive, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Total Size', value: formatBytes(totalSize), icon: HardDrive, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Active', value: activeVolumes, icon: HardDrive, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Public', value: publicVolumes, icon: HardDrive, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

  const columns: ColumnDef<AdminVolume>[] = [
    {
      accessorKey: 'display_name',
      header: 'Volume',
      cell: ({ row }) => {
        const v = row.original;
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded flex-shrink-0 bg-primary/10">
              <HardDrive className="w-4 h-4 text-primary" />
            </div>
            <div>
              <div className="font-medium">{v.display_name || v.name}</div>
              <code className="text-[10px] text-muted-foreground">{v.id}</code>
              <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{v.name}</code>
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'owner',
      header: 'Owner',
      cell: ({ row }) => {
        const owner = row.original.owner;
        if (!owner) return '-';
        return (
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
              <span className="text-[10px] font-medium text-primary">
                {(owner.display_name || owner.username).slice(0, 2).toUpperCase()}
              </span>
            </div>
            <span className="text-sm">{owner.display_name || owner.username}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'size_bytes',
      header: 'Size',
      cell: ({ row }) => {
        const v = row.original;
        const size = v.size_bytes || 0;
        const max = v.max_size_bytes;
        const pct = max && max > 0 ? Math.round((size / max) * 100) : 0;
        return (
          <div className="space-y-1">
            <div className="text-sm">
              {formatBytes(size)}
              {max ? ` / ${formatBytes(max)}` : ''}
            </div>
            {max && max > 0 && (
              <div className="w-20 h-1 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full ${pct >= 90 ? 'bg-amber-400' : 'bg-primary'}`}
                  style={{ width: `${Math.min(pct, 100)}%` }}
                />
              </div>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => {
        const { status, label } = volumeStatusToBadge(row.original.status);
        return <StatusBadge status={status} label={label} />;
      },

    },
    {
      accessorKey: 'visibility',
      header: 'Visibility',
      cell: ({ row }) => {
        const visibility = row.getValue('visibility') as string;
        return (
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${visibilityBadgeClass(visibility)}`}>
            {visibility}
          </span>
        );
      },

    },
    {
      accessorKey: 'server_count',
      header: 'Servers',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5 text-sm">
          <Server className="w-3.5 h-3.5 text-muted-foreground" />
          <span>{row.getValue('server_count') || 0}</span>
        </div>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: ({ row }) => formatDate(row.getValue('created_at') as string),
    },
    ...(canManageVolumes ? [{
      id: 'actions' as const,
      header: 'Actions',
      cell: ({ row }: { row: { original: AdminVolume } }) => (
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
              disabled={deleteVolume.isPending}
              className="inline-flex p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </motion.button>
          </Tooltip>
        </div>
      ),
      enableSorting: false,
      size: 80,
    } satisfies ColumnDef<AdminVolume>] : []),
  ];

  const filters = [
    {
      key: 'status',
      label: 'Status',
      options: [
        { label: 'All', value: 'all' },
        { label: 'Active', value: 'active' },
        { label: 'Archived', value: 'archived' },
        { label: 'Deleting', value: 'deleting' },
        { label: 'Over Limit', value: 'over_limit' },
      ],
    },
    {
      key: 'visibility',
      label: 'Visibility',
      options: [
        { label: 'All', value: 'all' },
        { label: 'Private', value: 'private' },
        { label: 'Workspace', value: 'workspace' },
        { label: 'Public', value: 'public' },
      ],
    },
  ];

  const mobileCardRenderer = (v: AdminVolume) => {
    const { status, label } = volumeStatusToBadge(v.status);
    return (
      <div className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="font-medium">{v.display_name || v.name}</div>
          <StatusBadge status={status} label={label} />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <code className="text-[10px]">{v.id}</code>
          <code className="bg-muted px-1.5 py-0.5 rounded">{v.name}</code>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{formatBytes(v.size_bytes)}</span>
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${visibilityBadgeClass(v.visibility)}`}>
            {v.visibility}
          </span>
          <span className="text-muted-foreground">{v.server_count || 0} servers</span>
        </div>
        {canManageVolumes && (
          <div className="flex items-center justify-between pt-1">
            <span className="text-sm text-muted-foreground">
              {v.created_at ? formatDate(v.created_at) : '-'}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => openEditDialog(v)}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
              >
                <Pencil className="w-4 h-4" />
              </button>
              <button
                onClick={() => handleDelete(v)}
                className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors inline-flex"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <ResourcePageLayout
        title="Volumes"
        subtitle="Manage all platform storage volumes"
        icon={HardDrive}
        backTo="/admin"
        stats={stats}
      >
        <DataTable
          columns={columns}
          data={volumes}
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
          searchPlaceholder="Search volumes..."
          density={useThemeStore().density}
          mobileCardRenderer={mobileCardRenderer}
        />
      </ResourcePageLayout>

      {canManageVolumes && (
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Edit Volume: {editingVolume?.display_name || editingVolume?.name}</DialogTitle>
              <DialogDescription>
                Update volume metadata.
              </DialogDescription>
            </DialogHeader>
            <form id="volume-form" onSubmit={handleSubmit} className="space-y-4 mt-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Display Name</label>
                <Input
                  value={formData.display_name}
                  onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                  placeholder="Volume display name"
                  required
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Volume description"
                  rows={3}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Visibility</label>
                  <Select
                    value={formData.visibility}
                    onChange={(v) => setFormData({ ...formData, visibility: v })}
                  >
                    <SelectItem value="private">Private</SelectItem>
                    <SelectItem value="workspace">Workspace</SelectItem>
                    <SelectItem value="public">Public</SelectItem>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Status</label>
                  <Select
                    value={formData.status}
                    onChange={(v) => setFormData({ ...formData, status: v })}
                  >
                    <SelectItem value="active">Active</SelectItem>
                    <SelectItem value="archived">Archived</SelectItem>
                    <SelectItem value="deleting">Deleting</SelectItem>
                    <SelectItem value="over_limit">Over Limit</SelectItem>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Max Size (bytes)</label>
                <Input
                  type="number"
                  min={0}
                  value={formData.max_size_bytes ?? ''}
                  onChange={(e) => setFormData({ ...formData, max_size_bytes: e.target.value ? parseInt(e.target.value) : undefined })}
                  placeholder="Leave empty for unlimited"
                />
              </div>
            </form>
            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" form="volume-form" loading={updateVolume.isPending}>
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
