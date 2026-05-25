import { createFileRoute, Link } from '@tanstack/react-router';
import { Server, Activity, Cpu, MemoryStick, Play, Square, RotateCcw, Trash2, ExternalLink, Eye, Users } from 'lucide-react';
import { Tooltip } from '../components/ui/tooltip';
import { Checkbox } from '../components/ui/checkbox';
import { useState, useEffect, useRef, useMemo } from 'react';
import { type ColumnDef, type SortingState, type ColumnFiltersState, type VisibilityState } from '@tanstack/react-table';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useServers, useBulkServerActions } from '../hooks/use-servers';
import { useServerActionsWithReason } from '../hooks/use-server-actions-with-reason';
import { useReasonDialog } from '../hooks/use-reason-dialog';
import { useEnvironments } from '../hooks/use-environments';
import { usePlans } from '../hooks/use-plans';
import { useVolumes } from '../hooks/use-volumes';
import { useDataTable } from '../hooks/use-data-table';
import { useThemeStore } from '../stores/theme-store';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { PermissionGuard } from '../components/permission-guard';
import { formatDate } from '../lib/utils';
import type { Server as ServerType } from '../types/api';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { DeployServerDialog } from '../components/server/deploy-server-dialog';

export const Route = createFileRoute('/admin/servers')({
  component: AdminServersPage,
});

function AdminServersPage() {
  const canManageServers = useAuthStore((state) => state.canManageServers());

  return (
    <PermissionGuard permission={PERMISSIONS.SERVERS_READ_ALL} redirectTo="/servers">
      <AdminServersContent enableManagement={canManageServers} />
    </PermissionGuard>
  );
}

function AdminServersContent({ enableManagement }: { enableManagement: boolean }) {
  const { confirm, dialog } = useConfirmDialog();
  const { data: servers = [], isLoading, isError, error } = useServers();
  const { createServer, startServer, stopServer, restartServer, deleteServer, startServerAsync, promptAccessReason, isOperationPending, dialog: reasonDialog } = useServerActionsWithReason();
  const { bulkAction } = useBulkServerActions();
  const { prompt } = useReasonDialog();
  const user = useAuthStore((state) => state.user);
  const canAccessOthersServers = useAuthStore((state) => state.canAccessOthersServers());
  const canAccessServer = (server: ServerType) => !user || server.user_id === user.id || canAccessOthersServers;
  const { data: envData } = useEnvironments({ is_active: true, limit: 100 });
  const { data: plansData } = usePlans({ is_active: true, limit: 100 });
  const { data: volumesData } = useVolumes();

  const {
    state: tableState,
    setPage,
    setLimit,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 20 });

  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

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

  const environments = envData?.data || [];
  const plans = plansData?.data || [];
  const volumes = volumesData || [];

  // Build dynamic owner filter from server data
  const ownerFilterOptions = useMemo(() => {
    const usernames = new Map<string, string>();
    servers.forEach((s) => {
      if (s.user_id && s.username) {
        usernames.set(s.user_id, s.username);
      }
    });
    return Array.from(usernames.entries())
      .map(([id, username]) => ({ label: username, value: id }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [servers]);

  // Client-side filtering and sorting
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

    // Filter by owner
    const ownerFilter = tableState.filters.owner;
    if (ownerFilter && server.user_id !== ownerFilter) {
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



  const columns = useMemo<ColumnDef<ServerType>[]>(() => [
    ...(enableManagement ? [{
      id: 'select' as const,
      header: ({ table }: { table: { getIsAllPageRowsSelected: () => boolean; toggleAllPageRowsSelected: (value?: boolean) => void } }) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected()}
          onChange={(checked) => table.toggleAllPageRowsSelected(checked)}
        />
      ),
      cell: ({ row }: { row: { getIsSelected: () => boolean; toggleSelected: (value?: boolean) => void } }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onChange={(checked) => row.toggleSelected(checked)}
        />
      ),
      enableSorting: false,
      size: 40,
    }] : []),
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <div className="font-medium">{row.getValue('name')}</div>
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
    {
      accessorKey: 'username',
      header: 'Owner',
      cell: ({ row }) => {
        const username = row.original.username;
        return (
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center text-xs font-medium">
              {username?.slice(0, 2).toUpperCase() || '??'}
            </div>
            <span className="text-sm">{username || 'Unknown'}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'allocated_cpu',
      header: 'CPU',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {row.original.allocated_cpu ? `${row.original.allocated_cpu} cores` : '—'}
        </span>
      ),
    },
    {
      accessorKey: 'allocated_memory',
      header: 'Memory',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {row.original.allocated_memory || '—'}
        </span>
      ),
    },
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
          if (!canAccessServer(server)) return;
          if (server.status !== 'running') {
            const started = await startServerAsync(server);
            if (!started) return;
          } else {
            const reason = await promptAccessReason(server, 'open');
            if (reason === null) return;
          }
          window.open(gatewayUrl, '_blank', 'noopener,noreferrer');
        };

        const anyPending = isOperationPending(server.id);

        if (!canAccessServer(server)) {
          return <span className="text-muted-foreground">—</span>;
        }

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
    ...(enableManagement ? [{
      id: 'actions' as const,
      header: 'Actions',
      cell: ({ row }: { row: { original: ServerType } }) => {
        const server = row.original;
        return (
          <div className="flex items-center gap-1">
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
                  onClick={() => startServer(server)}
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
                    onClick={() => stopServer(server)}
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
                    onClick={() => restartServer(server)}
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
                    description: `Are you sure you want to delete ${server.name}${server.username ? ` (owned by ${server.username})` : ''}?`,
                    confirmLabel: 'Delete',
                    cancelLabel: 'Cancel',
                    variant: 'danger',
                  });
                  if (confirmed) deleteServer(server);
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
    }] : []),
  ], [enableManagement, isOperationPending, startServer, stopServer, restartServer, deleteServer, confirm, startServerAsync, user, canAccessOthersServers]);

  const activeServers = servers.filter((s) => s.status === 'running').length;
  const parseMemory = (mem: string | undefined) => {
    if (!mem) return 0;
    const match = mem.match(/^(\d+)/);
    return match ? parseInt(match[1]) : 0;
  };
  const totalMemory = servers.reduce((acc, s) => acc + parseMemory(s.allocated_memory), 0);
  // const totalDisk = servers.reduce((acc, s) => acc + parseMemory(s.allocated_disk), 0);

  const stats = [
    { title: 'Active Servers', value: activeServers, icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Total Servers', value: servers.length, icon: Activity, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Total Memory', value: `${totalMemory} GB`, icon: MemoryStick, iconColor: 'text-rose-400', bgColor: 'bg-rose-500/10' },
    { title: 'Total CPU Cores', value: servers.reduce((acc, s) => acc + (s.allocated_cpu || 0), 0), icon: Cpu, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

  const runBulkAction = async (
    action: 'start' | 'stop' | 'restart' | 'delete',
    ids: string[]
  ) => {
    const selectedServers = ids.map((id) => servers.find((s) => s.id === id)).filter(Boolean) as ServerType[];
    const hasCrossUser = selectedServers.some((s) => s.user_id !== user?.id);
    let reason: string | undefined;
    if (hasCrossUser) {
      const r = await prompt({
        description: `You are about to ${action} ${ids.length} server(s) owned by other users. Please provide a reason.`,
        actionLabel: action,
      });
      if (!r) return;
      reason = r;
    }
    bulkAction.mutate({ action, server_ids: ids, reason }, {
      onSuccess: () => setRowSelection({}),
    });
  };

  const bulkActions = enableManagement ? [
    {
      label: 'Start',
      icon: <Play className="w-4 h-4" />,
      onClick: (ids: string[]) => runBulkAction('start', ids),
    },
    {
      label: 'Stop',
      icon: <Square className="w-4 h-4" />,
      onClick: (ids: string[]) => runBulkAction('stop', ids),
    },
    {
      label: 'Restart',
      icon: <RotateCcw className="w-4 h-4" />,
      onClick: (ids: string[]) => runBulkAction('restart', ids),
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
        if (confirmed) runBulkAction('delete', ids);
      },
      variant: 'destructive' as const,
    },
  ] : [];

  const filters = [
    ...(ownerFilterOptions.length > 0 ? [{
      key: 'owner' as const,
      label: 'Owner',
      options: ownerFilterOptions,
    }] : []),
    {
      key: 'status' as const,
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
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{server.name}</div>
        <StatusBadge status={server.status as 'running' | 'stopped' | 'pending' | 'error'} pulse={server.status === 'running'} />
      </div>
      {server.username && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Users className="w-3.5 h-3.5" />
          {server.username}
        </div>
      )}
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        {server.allocated_cpu !== undefined && (
          <span className="inline-flex items-center gap-1">
            <Cpu className="w-3.5 h-3.5" />
            {server.allocated_cpu} cores
          </span>
        )}
        {server.allocated_memory && (
          <span className="inline-flex items-center gap-1">
            <MemoryStick className="w-3.5 h-3.5" />
            {server.allocated_memory}
          </span>
        )}
      </div>
      <div className="text-sm text-muted-foreground">
        Created: {formatDate(server.created_at || '')}
      </div>
      <div className="flex items-center justify-between pt-1">
        {server.external_url && canAccessServer(server) && (
          <button
            onClick={async (e) => {
              e.preventDefault();
              if (server.status !== 'running') {
                const started = await startServerAsync(server);
                if (!started) return;
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
        {enableManagement && (
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
                  onClick={() => startServer(server)}
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
                    onClick={() => stopServer(server)}
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
                    onClick={() => restartServer(server)}
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
                  if (confirmed) deleteServer(server);
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
        )}
      </div>
    </div>
  );

  return (
    <>
      <ResourcePageLayout
        title="Server Management"
        subtitle="Manage all platform servers"
        icon={Server}
        backTo="/admin"
        stats={stats}
        actions={[
          {
            action: 'deploy',
            onClick: () => setDialogOpen(true)
          },
        ]}
      >
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
          searchPlaceholder="Search by name, status, or owner..."
          density={useThemeStore().density}
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={enableManagement}
        />
      </ResourcePageLayout>

      <DeployServerDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        plans={plans}
        environments={environments}
        volumes={volumes}
        defaultUsername={user?.username}
        defaultPlanId={user?.preferences?.default_plan as string | undefined}
        defaultEnvironmentId={user?.preferences?.default_environment as string | undefined}
        isPending={createServer.isPending}
        error={createServer.error}
        onDeploy={(data) => {
          createServer.mutate(data, {
            onSuccess: () => {
              setDialogOpen(false);
            },
          });
        }}
      />
      {dialog}
      {reasonDialog}
    </>
  );
}
