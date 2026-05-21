import { createFileRoute } from '@tanstack/react-router';
import { Gauge, Pencil, Server, Cpu, HardDrive, MemoryStick, CircuitBoard } from 'lucide-react';
import { useState, useEffect } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { useQuotas, useQuotaActions, type UserQuota } from '../hooks/use-quotas';
import { useDataTable } from '../hooks/use-data-table';
import { useThemeStore } from '../stores/theme-store';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { usePageGuard } from '../hooks/use-page-guard';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { Tooltip } from '../components/ui/tooltip';

export const Route = createFileRoute('/admin/quotas')({
  component: QuotasPage,
});

function QuotasPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.QUOTA_READ });
  if (!allowed) return null;

  const hasPermission = useAuthStore((state) => state.hasPermission);
  const canUpdateQuotas = hasPermission(PERMISSIONS.QUOTA_UPDATE);

  const {
    state: tableState,
    setPage,
    setLimit,
    setSort,
    setSearch,
  } = useDataTable({ defaultLimit: 20, defaultSortBy: 'username' });

  const [sorting, setSorting] = useState<SortingState>([
    { id: tableState.sortBy, desc: tableState.sortOrder === 'desc' }
  ]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

  // Sync React Table column filters with API filter state
  useEffect(() => {
    columnFilters.forEach((filter) => {
      if (filter.value !== undefined && filter.value !== null) {
        // no-op for now — quotas don't have column filters
      }
    });
  }, [columnFilters]);

  const { data, isLoading, isError, error } = useQuotas({
    search: tableState.search,
    page: tableState.page,
    limit: tableState.limit,
  });

  const quotas = data?.items || [];
  const pagination = data;

  // Edit dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingQuota, setEditingQuota] = useState<UserQuota | null>(null);
  const [formData, setFormData] = useState({
    max_servers_total: 5,
    max_cpu_total: 8,
    max_memory_total: '16g',
    max_disk_total: '100g',
    max_gpu_total: 0,
  });

  const { updateQuota } = useQuotaActions();

  const openEditDialog = (quota: UserQuota) => {
    setEditingQuota(quota);
    setFormData({
      max_servers_total: quota.limits.max_servers_total,
      max_cpu_total: quota.limits.max_cpu_total,
      max_memory_total: quota.limits.max_memory_total,
      max_disk_total: quota.limits.max_disk_total,
      max_gpu_total: quota.limits.max_gpu_total,
    });
    setDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingQuota) return;

    updateQuota.mutate({
      userId: editingQuota.user_id,
      limits: {
        max_servers_total: formData.max_servers_total,
        max_cpu_total: formData.max_cpu_total,
        max_memory_total: formData.max_memory_total,
        max_disk_total: formData.max_disk_total,
        max_gpu_total: formData.max_gpu_total,
      },
    }, {
      onSuccess: () => setDialogOpen(false),
    });
  };

  // Stats
  const totalUsers = pagination?.total || 0;
  const avgServers = totalUsers > 0
    ? Math.round(quotas.reduce((sum: number, q: UserQuota) => sum + q.limits.max_servers_total, 0) / totalUsers)
    : 0;
  const avgCpu = totalUsers > 0
    ? Math.round((quotas.reduce((sum: number, q: UserQuota) => sum + q.limits.max_cpu_total, 0) / totalUsers) * 10) / 10
    : 0;

  const stats = [
    { title: 'Users', value: totalUsers, icon: Gauge, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Avg Servers', value: avgServers, icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Avg CPU', value: `${avgCpu} cores`, icon: Cpu, iconColor: 'text-orange-400', bgColor: 'bg-orange-500/10' },
  ];

  const columns: ColumnDef<UserQuota>[] = [
    {
      accessorKey: 'username',
      header: 'User',
      cell: ({ row }) => {
        const q = row.original;
        return (
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
              <span className="text-xs font-medium text-primary">
                {q.username.slice(0, 2).toUpperCase()}
              </span>
            </div>
            <div>
              <div className="font-medium">{q.username}</div>
              {q.display_name && <div className="text-xs text-muted-foreground">{q.display_name}</div>}
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'role',
      header: 'Role',
      cell: ({ row }) => (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">
          {row.getValue('role')}
        </span>
      ),
    },
    {
      accessorKey: 'limits.max_servers_total',
      header: 'Servers',
      cell: ({ row }) => {
        const q = row.original;
        const usage = q.usage.servers;
        const limit = q.limits.max_servers_total;
        const pct = limit > 0 ? Math.round((usage / limit) * 100) : 0;
        return (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm">
              <Server className="w-3.5 h-3.5 text-muted-foreground" />
              <span className={pct >= 90 ? 'text-amber-400 font-medium' : ''}>
                {usage} / {limit}
              </span>
            </div>
            <div className="w-20 h-1 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full ${pct >= 90 ? 'bg-amber-400' : 'bg-primary'}`}
                style={{ width: `${Math.min(pct, 100)}%` }}
              />
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'limits.max_cpu_total',
      header: 'CPU',
      cell: ({ row }) => {
        const q = row.original;
        return (
          <div className="flex items-center gap-2 text-sm">
            <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
            <span>{q.usage.cpu} / {q.limits.max_cpu_total} cores</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'limits.max_memory_total',
      header: 'Memory',
      cell: ({ row }) => {
        const q = row.original;
        return (
          <div className="flex items-center gap-2 text-sm">
            <MemoryStick className="w-3.5 h-3.5 text-muted-foreground" />
            <span>{q.limits.max_memory_total}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'limits.max_disk_total',
      header: 'Disk',
      cell: ({ row }) => {
        const q = row.original;
        return (
          <div className="flex items-center gap-2 text-sm">
            <HardDrive className="w-3.5 h-3.5 text-muted-foreground" />
            <span>{q.limits.max_disk_total}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'limits.max_gpu_total',
      header: 'GPU',
      cell: ({ row }) => {
        const q = row.original;
        return (
          <div className="flex items-center gap-2 text-sm">
            <CircuitBoard className="w-3.5 h-3.5 text-muted-foreground" />
            <span>{q.limits.max_gpu_total}</span>
          </div>
        );
      },
    },
    ...(canUpdateQuotas ? [{
      id: 'actions' as const,
      header: 'Actions',
      cell: ({ row }: { row: { original: UserQuota } }) => (
        <Tooltip content="Edit Quota">
          <button
            onClick={() => openEditDialog(row.original)}
            className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
          >
            <Pencil className="w-4 h-4" />
          </button>
        </Tooltip>
      ),
      enableSorting: false,
      size: 50,
    } satisfies ColumnDef<UserQuota>] : []),
  ];

  // Mobile card
  const mobileCard = (q: UserQuota) => (
    <div className="p-3 space-y-3">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
          <span className="text-xs font-medium text-primary">{q.username.slice(0, 2).toUpperCase()}</span>
        </div>
        <div>
          <p className="text-sm font-medium">{q.username}</p>
          <p className="text-xs text-muted-foreground">{q.role}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <Server className="w-3 h-3" />
          {q.usage.servers} / {q.limits.max_servers_total} servers
        </div>
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <Cpu className="w-3 h-3" />
          {q.usage.cpu} / {q.limits.max_cpu_total} cores
        </div>
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <MemoryStick className="w-3 h-3" />
          {q.limits.max_memory_total}
        </div>
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <HardDrive className="w-3 h-3" />
          {q.limits.max_disk_total}
        </div>
        {canUpdateQuotas && (
          <div className="ml-auto">
            <Tooltip content="Edit Quota">
              <button
                onClick={() => openEditDialog(q)}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
              >
                <Pencil className="w-4 h-4" />
              </button>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <>
      <ResourcePageLayout
        title="Quotas"
        subtitle="Manage per-user resource limits"
        icon={Gauge}
        backTo="/admin"
        stats={stats}
      >
        <DataTable
          columns={columns}
          data={quotas}
          totalCount={pagination?.total || 0}
          pageCount={pagination?.pages || 1}
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
          getRowId={(row) => row.user_id}
          searchable
          searchPlaceholder="Search users..."
          density={useThemeStore().density}
          mobileCardRenderer={mobileCard}
        />
      </ResourcePageLayout>

      {canUpdateQuotas && (
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Edit Quota: {editingQuota?.username}</DialogTitle>
              <DialogDescription>
                Adjust resource limits for this user.
              </DialogDescription>
            </DialogHeader>
            <form id="quotas-form" onSubmit={handleSubmit} className="space-y-4 mt-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Max Servers</label>
                  <Input
                    type="number"
                    min={0}
                    value={formData.max_servers_total}
                    onChange={(e) => setFormData({ ...formData, max_servers_total: parseInt(e.target.value) || 0 })}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Max CPU (cores)</label>
                  <Input
                    type="number"
                    min={0}
                    step={0.5}
                    value={formData.max_cpu_total}
                    onChange={(e) => setFormData({ ...formData, max_cpu_total: parseFloat(e.target.value) || 0 })}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Max Memory</label>
                  <Input
                    type="text"
                    value={formData.max_memory_total}
                    onChange={(e) => setFormData({ ...formData, max_memory_total: e.target.value })}
                    placeholder="e.g. 16g"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Max Disk</label>
                  <Input
                    type="text"
                    value={formData.max_disk_total}
                    onChange={(e) => setFormData({ ...formData, max_disk_total: e.target.value })}
                    placeholder="e.g. 100g"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Max GPU</label>
                <Input
                  type="number"
                  min={0}
                  value={formData.max_gpu_total}
                  onChange={(e) => setFormData({ ...formData, max_gpu_total: parseInt(e.target.value) || 0 })}
                />
              </div>
            </form>
            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" form="quotas-form" loading={updateQuota.isPending}>
                Update
              </Button>
            </DialogFooter>
            <DialogClose onClick={() => setDialogOpen(false)} />
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
