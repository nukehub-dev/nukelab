import { createFileRoute, Link } from '@tanstack/react-router';
import { Server, Activity, Cpu, MemoryStick, Play, Square, RotateCcw, Trash2, ExternalLink, Eye, Users } from 'lucide-react';
import { Tooltip } from '../components/ui/tooltip';
import { useState, useEffect, useRef } from 'react';
import { type ColumnDef, type SortingState, type ColumnFiltersState, type VisibilityState } from '@tanstack/react-table';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useServers, useServerActions } from '../hooks/use-servers';
import { useEnvironments } from '../hooks/use-environments';
import { usePlans } from '../hooks/use-plans';
import { useDataTable } from '../hooks/use-data-table';
import { useAuthStore } from '../stores/auth-store';
import { formatDate } from '../lib/utils';
import type { Server as ServerType } from '../types/api';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { Select, SelectItem } from '../components/ui/select';
import { useConfirmDialog } from '../components/ui/confirm-dialog';

export const Route = createFileRoute('/servers/')({
  component: ServersPage,
});

function ServersPage() {
  const { confirm, dialog } = useConfirmDialog();
  const { data: servers = [], isLoading, isError, error } = useServers();
  const { createServer, startServer, stopServer, restartServer, deleteServer, isOperationPending } = useServerActions();
  const { data: envData } = useEnvironments({ is_active: true, limit: 100 });
  const { data: plansData } = usePlans({ is_active: true, limit: 100 });
  const canViewAllServers = useAuthStore((state) => state.canViewAllServers());
   
  const {
    state: tableState,
    setPage,
    setLimit,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 10 });

  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [selectedUserFilter] = useState<string>('');

  // Sync React Table column filters with client-side filter state
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

  const [dialogOpen, setDialogOpen] = useState(false);
  const [deployForm, setDeployForm] = useState({
    name: '',
    plan_id: '',
    environment_id: '',
  });

  const environments = envData?.data || [];
  const plans = plansData?.data || [];
  
  // Client-side filtering and sorting for now since API doesn't support it fully
  const filteredServers = servers.filter((server) => {
    let matches = true;
    
    if (tableState.search) {
      const search = tableState.search.toLowerCase();
      const userName = server.username?.toLowerCase() || '';
      matches = matches && (
        server.name.toLowerCase().includes(search) ||
        server.status.toLowerCase().includes(search) ||
        userName.includes(search)
      );
    }
    
    // Filter by selected user
    if (selectedUserFilter && server.user_id !== selectedUserFilter) {
      matches = false;
    }
    
    // Filter by status
    const statusFilter = tableState.filters.status;
    if (statusFilter && server.status !== statusFilter) {
      matches = false;
    }
    
    return matches;
  });

  const sortedServers = [...filteredServers].sort((a, b) => {
    if (sorting.length === 0) return 0;
    const sort = sorting[0];
    const aVal = a[sort.id as keyof ServerType];
    const bVal = b[sort.id as keyof ServerType];
    if (aVal == null || bVal == null) return 0;
    if (aVal < bVal) return sort.desc ? 1 : -1;
    if (aVal > bVal) return sort.desc ? -1 : 1;
    return 0;
  });

  // Client-side pagination
  const pageCount = Math.ceil(sortedServers.length / tableState.limit) || 1;
  const paginatedServers = sortedServers.slice(
    (tableState.page - 1) * tableState.limit,
    tableState.page * tableState.limit
  );

  const handleDeploy = (e: React.FormEvent) => {
    e.preventDefault();
    if (!deployForm.environment_id) return;
    createServer.mutate(
      {
        name: deployForm.name,
        plan_id: deployForm.plan_id,
        environment_id: deployForm.environment_id,
      },
      {
        onSuccess: () => {
          setDialogOpen(false);
          setDeployForm({ name: '', plan_id: '', environment_id: '' });
        },
      }
    );
  };

  const columns: ColumnDef<ServerType>[] = [
    {
      id: 'select',
      header: ({ table }) => (
        <input
          type="checkbox"
          checked={table.getIsAllPageRowsSelected()}
          onChange={table.getToggleAllPageRowsSelectedHandler()}
          className="rounded border-border"
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          className="rounded border-border"
        />
      ),
      enableSorting: false,
      size: 40,
    },
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <div className="font-medium"
        >{row.getValue('name')}</div>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => {
        const status = row.getValue('status') as string;
        return (
          <StatusBadge
            status={status as 'running' | 'stopped' | 'pending' | 'error'}
            pulse={status === 'running'}
          />
        );
      },
    },
    ...(canViewAllServers ? [{
      accessorKey: 'username' as const,
      header: 'Owner',
      cell: ({ row }: { row: { original: ServerType } }) => {
        const username = row.original.username;
        return (
          <div className="flex items-center gap-2"
          >
            <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center text-xs font-medium"
            >
              {username?.slice(0, 2).toUpperCase() || '??'}
            </div>
            <span className="text-sm"
            >{username || 'Unknown'}</span>
          </div>
        );
      },
    } as ColumnDef<ServerType>] : []),
    {
      accessorKey: 'external_url',
      header: 'URL',
      cell: ({ row }) => {
        const server = row.original;
        const url = row.getValue('external_url') as string;
        if (!url) return <span className="text-muted-foreground">—</span>;

        const gatewayUrl = server.username
          ? `/user/${server.username}/${server.name}`
          : url;

        const handleOpen = async (e: React.MouseEvent) => {
          e.preventDefault();
          if (server.status !== 'running') {
            await startServer.mutateAsync(server.id);
          }
          window.open(gatewayUrl, '_blank', 'noopener,noreferrer');
        };

        const anyPending = isOperationPending(server.id);

        return (
          <button
            onClick={handleOpen}
            disabled={anyPending}
            className="inline-flex items-center gap-1 text-primary hover:underline disabled:opacity-50"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            {isOperationPending(server.id, 'start') ? 'Starting...' : server.status !== 'running' ? 'Start & Open' : 'Open'}
          </button>
        );
      },
    },
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: ({ row }) => formatDate(row.getValue('created_at') as string),
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => {
        const server = row.original;
        return (
          <div className="flex items-center gap-1"
          >
            <Tooltip content="View Details">
              <Link
                to="/servers/$serverId"
                params={{ serverId: server.id }}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
              >
                <Eye className="w-4 h-4" />
              </Link>
            </Tooltip>
            {server.status === 'stopped' && (
              <Tooltip content={isOperationPending(server.id, 'start') ? 'Starting...' : 'Start'}>
                <button
                  onClick={() => startServer.mutate(server.id)}
                  disabled={isOperationPending(server.id, 'start')}
                  className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
                >
                  {isOperationPending(server.id, 'start') ? (
                    <RotateCcw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4" />
                  )}
                </button>
              </Tooltip>
            )}
            {server.status === 'running' && (
              <>
                <Tooltip content={isOperationPending(server.id, 'stop') ? 'Stopping...' : 'Stop'}>
                  <button
                    onClick={() => stopServer.mutate(server.id)}
                    disabled={isOperationPending(server.id, 'stop')}
                    className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
                  >
                    {isOperationPending(server.id, 'stop') ? (
                      <RotateCcw className="w-4 h-4 animate-spin" />
                    ) : (
                      <Square className="w-4 h-4" />
                    )}
                  </button>
                </Tooltip>
                <Tooltip content={isOperationPending(server.id, 'restart') ? 'Restarting...' : 'Restart'}>
                  <button
                    onClick={() => restartServer.mutate(server.id)}
                    disabled={isOperationPending(server.id, 'restart')}
                    className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
                  >
                    {isOperationPending(server.id, 'restart') ? (
                      <RotateCcw className="w-4 h-4 animate-spin" />
                    ) : (
                      <RotateCcw className="w-4 h-4" />
                    )}
                  </button>
                </Tooltip>
              </>
            )}
            <Tooltip content={isOperationPending(server.id, 'delete') ? 'Deleting...' : 'Delete'}>
              <button
                onClick={async () => {
                  const confirmed = await confirm({
                    title: 'Delete Server',
                    description: 'Are you sure you want to delete this server?',
                    confirmLabel: 'Delete',
                    cancelLabel: 'Cancel',
                    variant: 'danger',
                  });
                  if (confirmed) deleteServer.mutate(server.id);
                }}
                disabled={isOperationPending(server.id, 'delete')}
                className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
              >
                {isOperationPending(server.id, 'delete') ? (
                  <RotateCcw className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
              </button>
            </Tooltip>
          </div>
        );
      },
      enableSorting: false,
    },
  ];

  const activeServers = servers.filter((s) => s.status === 'running').length;
  const parseMemory = (mem: string | undefined) => {
    if (!mem) return 0;
    const match = mem.match(/^(\d+)/);
    return match ? parseInt(match[1]) : 0;
  };
  const totalMemory = servers.reduce((acc, s) => acc + parseMemory(s.allocated_memory), 0);

  const stats = [
    { title: 'Active Servers', value: activeServers, icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Total Servers', value: servers.length, icon: Activity, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Memory Allocated', value: `${totalMemory} GB`, icon: MemoryStick, iconColor: 'text-rose-400', bgColor: 'bg-rose-500/10' },
    { title: 'CPU Cores', value: servers.reduce((acc, s) => acc + (s.allocated_cpu || 0), 0), icon: Cpu, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

  const bulkActions = [
    {
      label: 'Start',
      icon: <Play className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => startServer.mutate(id));
      },
    },
    {
      label: 'Stop',
      icon: <Square className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => stopServer.mutate(id));
      },
    },
    {
      label: 'Restart',
      icon: <RotateCcw className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => restartServer.mutate(id));
      },
    },
    {
      label: 'Delete',
      icon: <Trash2 className="w-4 h-4" />,
      onClick: async (ids: string[]) => {
        const confirmed = await confirm({
          title: 'Delete Servers',
          description: `Are you sure you want to delete ${ids.length} servers?`,
          confirmLabel: 'Delete',
          cancelLabel: 'Cancel',
          variant: 'danger',
        });
        if (confirmed) ids.forEach((id) => deleteServer.mutate(id));
      },
      variant: 'destructive' as const,
    },
  ];

  const filters = [
    {
      key: 'status',
      label: 'Status',
      options: [
        { label: 'Running', value: 'running' },
        { label: 'Stopped', value: 'stopped' },
        { label: 'Pending', value: 'pending' },
        { label: 'Error', value: 'error' },
      ],
    },
  ];

  const mobileCardRenderer = (server: ServerType) => (
    <div className="p-4 space-y-3"
    >
      <div className="flex items-center justify-between"
      >
        <div className="font-medium"
        >{server.name}</div>
        <StatusBadge status={server.status as 'running' | 'stopped' | 'pending' | 'error'} pulse={server.status === 'running'} />
      </div>
          {canViewAllServers && server.username && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Users className="w-3.5 h-3.5" />
          {server.username}
        </div>
      )}
      <div className="text-sm text-muted-foreground"
      >
        Created: {formatDate(server.created_at || '')}
      </div>
      <div className="flex items-center justify-between pt-1">
        {server.external_url && (
          <button
            onClick={async (e) => {
              e.preventDefault();
              if (server.status !== 'running') {
                await startServer.mutateAsync(server.id);
              }
              const gatewayUrl = server.username
                ? `/user/${server.username}/${server.name}`
                : server.external_url;
              window.open(gatewayUrl, '_blank', 'noopener,noreferrer');
            }}
            disabled={isOperationPending(server.id)}
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline disabled:opacity-50"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            {isOperationPending(server.id, 'start') ? 'Starting...' : server.status !== 'running' ? 'Start & Open' : 'Open Server'}
          </button>
        )}
        <div className="flex items-center gap-1 ml-auto">
          <Tooltip content="View Details">
            <Link
              to="/servers/$serverId"
              params={{ serverId: server.id }}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
            >
              <Eye className="w-4 h-4" />
            </Link>
          </Tooltip>
          {server.status === 'stopped' && (
            <Tooltip content={isOperationPending(server.id, 'start') ? 'Starting...' : 'Start'}>
              <button
                onClick={() => startServer.mutate(server.id)}
                disabled={isOperationPending(server.id, 'start')}
                className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
              >
                {isOperationPending(server.id, 'start') ? (
                  <RotateCcw className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
              </button>
            </Tooltip>
          )}
          {server.status === 'running' && (
            <>
              <Tooltip content={isOperationPending(server.id, 'stop') ? 'Stopping...' : 'Stop'}>
                <button
                  onClick={() => stopServer.mutate(server.id)}
                  disabled={isOperationPending(server.id, 'stop')}
                  className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
                >
                  {isOperationPending(server.id, 'stop') ? (
                    <RotateCcw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                </button>
              </Tooltip>
              <Tooltip content={isOperationPending(server.id, 'restart') ? 'Restarting...' : 'Restart'}>
                <button
                  onClick={() => restartServer.mutate(server.id)}
                  disabled={isOperationPending(server.id, 'restart')}
                  className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
                >
                  {isOperationPending(server.id, 'restart') ? (
                    <RotateCcw className="w-4 h-4 animate-spin" />
                  ) : (
                    <RotateCcw className="w-4 h-4" />
                  )}
                </button>
              </Tooltip>
            </>
          )}
          <Tooltip content={isOperationPending(server.id, 'delete') ? 'Deleting...' : 'Delete'}>
            <button
              onClick={async () => {
                const confirmed = await confirm({
                  title: 'Delete Server',
                  description: 'Are you sure you want to delete this server?',
                  confirmLabel: 'Delete',
                  cancelLabel: 'Cancel',
                  variant: 'danger',
                });
                if (confirmed) deleteServer.mutate(server.id);
              }}
              disabled={isOperationPending(server.id, 'delete')}
              className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-all duration-100 inline-flex disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
            >
              {isOperationPending(server.id, 'delete') ? (
                <RotateCcw className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <ResourcePageLayout
        title="Servers"
        subtitle="Manage your simulation servers"
        icon={Server}
        stats={stats}
        actions={[
          { 
            action: 'deploy', 
            onClick: () => setDialogOpen(true) 
          },
        ]}
      >

        {/* Servers Table - Always paginated flat view for performance */}
        <DataTable
          columns={columns}
          data={paginatedServers}
          totalCount={sortedServers.length}
          pageCount={pageCount}
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
          onSortingChange={setSorting}
          onRowSelectionChange={setRowSelection}
          onColumnFiltersChange={setColumnFilters}
          onColumnVisibilityChange={setColumnVisibility}
          onGlobalFilterChange={setSearch}
          getRowId={(row) => row.id}
          bulkActions={bulkActions}
          filters={filters}
          searchable
          searchPlaceholder="Search..."
          mobileCardRenderer={mobileCardRenderer}
        />
      </ResourcePageLayout>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}
      >
        <DialogContent
        >
          <DialogHeader>
            <DialogTitle>Deploy New Server</DialogTitle>
            <DialogDescription>
              Create and spawn a new simulation server.
            </DialogDescription>
          </DialogHeader>
          <form id="deploy-form" onSubmit={handleDeploy} className="space-y-4 mt-4" noValidate
          >
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Server Name *</label>
              <Input
                type="text"
                required
                value={deployForm.name}
                onChange={(e) => setDeployForm({ ...deployForm, name: e.target.value })}
                placeholder="my-simulation-server"
              />
            </div>
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Plan *</label>
              <Select
                value={deployForm.plan_id}
                onChange={(value) => setDeployForm({ ...deployForm, plan_id: value })}
                placeholder="Select a plan..."
              >
                {plans.map((plan) => (
                  <SelectItem key={plan.id} value={plan.id}>
                    {plan.name} ({plan.cpu_limit} CPU / {plan.memory_limit})
                  </SelectItem>
                ))}
              </Select>
            </div>
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Environment *</label>
              <Select
                value={deployForm.environment_id}
                onChange={(value) => setDeployForm({ ...deployForm, environment_id: value })}
                placeholder="Select an environment..."
              >
                {environments.map((env) => (
                  <SelectItem key={env.id} value={env.id}>
                    {env.name} ({env.slug})
                  </SelectItem>
                ))}
              </Select>
            </div>
          </form>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" form="deploy-form" loading={createServer.isPending || !deployForm.environment_id}>
              {createServer.isPending ? 'Deploying...' : 'Deploy'}
            </Button>
          </DialogFooter>
          <DialogClose onClick={() => setDialogOpen(false)} />
        </DialogContent>
      </Dialog>
      {dialog}
    </>
  );
}
