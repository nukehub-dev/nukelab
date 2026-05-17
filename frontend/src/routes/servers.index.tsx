import { createFileRoute, Link } from '@tanstack/react-router';
import { Server, Activity, Cpu, MemoryStick, Play, Square, RotateCcw, Trash2, ExternalLink, Eye, HardDrive, Plus, X, Pencil, Calendar, AlertTriangle, Clock } from 'lucide-react';
import { Tooltip } from '../components/ui/tooltip';
import { Checkbox } from '../components/ui/checkbox';
import { useState, useEffect, useRef, useMemo } from 'react';
import { type ColumnDef, type SortingState, type ColumnFiltersState, type VisibilityState } from '@tanstack/react-table';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useServers, useServerActions, useServerSchedules, useCreateSchedule, useDeleteSchedule } from '../hooks/use-servers';
import { useEnvironments } from '../hooks/use-environments';
import { usePlans } from '../hooks/use-plans';
import { useVolumes } from '../hooks/use-volumes';
import { useDataTable } from '../hooks/use-data-table';
import { useAuthStore } from '../stores/auth-store';
import { formatDate, cn } from '../lib/utils';
import type { Server as ServerType } from '../types/api';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { Select, SelectItem } from '../components/ui/select';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { CronBuilder, humanizeSchedule, parseCron } from '../components/cron-builder';

export const Route = createFileRoute('/servers/')({
  component: ServersPage,
});

function ServersPage() {
  const { confirm, dialog } = useConfirmDialog();
  const { data: servers = [], isLoading, isError, error } = useServers();
  const { createServer, updateServer, startServer, stopServer, restartServer, deleteServer, isOperationPending } = useServerActions();
  const { data: envData } = useEnvironments({ is_active: true, limit: 100 });
  const { data: plansData } = usePlans({ is_active: true, limit: 100 });
  const { data: volumesData } = useVolumes();
  const user = useAuthStore((state) => state.user);

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

  interface VolumeMountForm {
    volume_id: string;
    mount_path: string;
    mode: 'read_write' | 'read_only';
  }

  const [dialogOpen, setDialogOpen] = useState(false);
  const [deployForm, setDeployForm] = useState({
    name: '',
    plan_id: '',
    environment_id: '',
  });
  const [volumeMounts, setVolumeMounts] = useState<VolumeMountForm[]>([
    { volume_id: '', mount_path: '', mode: 'read_write' },
  ]);

  // Edit dialog state
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editServerId, setEditServerId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({
    name: '',
    plan_id: '',
    environment_id: '',
  });
  const [editVolumeMounts, setEditVolumeMounts] = useState<VolumeMountForm[]>([
    { volume_id: '', mount_path: '', mode: 'read_write' },
  ]);

  const openEditDialog = (server: ServerType) => {
    setEditServerId(server.id);
    setEditForm({
      name: server.name,
      plan_id: server.plan_id || '',
      environment_id: server.environment_id || '',
    });
    if (server.volume_mounts && server.volume_mounts.length > 0) {
      setEditVolumeMounts(
        server.volume_mounts.map((m) => ({
          volume_id: m.volume_id,
          mount_path: m.mount_path,
          mode: m.mode,
        }))
      );
    } else {
      setEditVolumeMounts([
        {
          volume_id: server.volume_id || '',
          mount_path: server.volume_mode ? `/home/${user?.username || 'user'}` : '',
          mode: (server.volume_mode as 'read_write' | 'read_only') || 'read_write',
        },
      ]);
    }
    setEditDialogOpen(true);
  };

  const handleEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editServerId) return;

    const mounts = editVolumeMounts
      .filter((m) => m.volume_id)
      .map((m, idx) => ({
        volume_id: m.volume_id,
        mount_path: idx === 0 && !m.mount_path ? `/home/${user?.username || 'user'}` : (m.mount_path || '/data'),
        mode: m.mode,
      }));

    updateServer.mutate(
      {
        serverId: editServerId,
        data: {
          name: editForm.name,
          plan_id: editForm.plan_id || undefined,
          environment_id: editForm.environment_id || undefined,
          volume_mounts: mounts.length > 0 ? mounts : undefined,
        },
      },
      {
        onSuccess: () => {
          setEditDialogOpen(false);
          setEditServerId(null);
        },
      }
    );
  };

  const addEditVolumeMount = () => {
    setEditVolumeMounts((prev) => [
      ...prev,
      { volume_id: '', mount_path: '/data', mode: 'read_write' },
    ]);
  };

  const removeEditVolumeMount = (index: number) => {
    setEditVolumeMounts((prev) => prev.filter((_, i) => i !== index));
  };

  const updateEditVolumeMount = (index: number, field: keyof VolumeMountForm, value: string) => {
    setEditVolumeMounts((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [field]: value } : m))
    );
  };

  // Schedule dialog state
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [scheduleServerId, setScheduleServerId] = useState<string | null>(null);
  const [showScheduleForm, setShowScheduleForm] = useState(false);
  const [newSchedule, setNewSchedule] = useState<{ action: 'start' | 'stop' | 'restart'; cron_expression: string; timezone: string; is_active: boolean }>({ action: 'start', cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true });

  const openScheduleDialog = (server: ServerType) => {
    setScheduleServerId(server.id);
    setShowScheduleForm(false);
    setNewSchedule({ action: 'start', cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true });
    setScheduleDialogOpen(true);
  };

  const environments = envData?.data || [];
  const plans = plansData?.data || [];
  const volumes = volumesData || [];

  // Filter to only current user's servers
  const myServers = servers.filter((server) => !user || server.user_id === user.id);

  // Client-side filtering and sorting
  const filteredServers = myServers.filter((server) => {
    let matches = true;

    if (tableState.search) {
      const search = tableState.search.toLowerCase();
      matches = matches && (
        server.name.toLowerCase().includes(search) ||
        server.status.toLowerCase().includes(search)
      );
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

    const mounts = volumeMounts
      .filter((m) => m.volume_id)
      .map((m, idx) => ({
        volume_id: m.volume_id,
        mount_path: idx === 0 && !m.mount_path ? `/home/${user?.username || 'user'}` : (m.mount_path || '/data'),
        mode: m.mode,
      }));

    createServer.mutate(
      {
        name: deployForm.name,
        plan_id: deployForm.plan_id,
        environment_id: deployForm.environment_id,
        volume_mounts: mounts.length > 0 ? mounts : undefined,
      },
      {
        onSuccess: () => {
          setDialogOpen(false);
          setDeployForm({ name: '', plan_id: '', environment_id: '' });
          setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write' }]);
        },
      }
    );
  };

  const addVolumeMount = () => {
    setVolumeMounts((prev) => [
      ...prev,
      { volume_id: '', mount_path: '/data', mode: 'read_write' },
    ]);
  };

  const removeVolumeMount = (index: number) => {
    setVolumeMounts((prev) => prev.filter((_, i) => i !== index));
  };

  const updateVolumeMount = (index: number, field: keyof VolumeMountForm, value: string) => {
    setVolumeMounts((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [field]: value } : m))
    );
  };

  const columns = useMemo<ColumnDef<ServerType>[]>(() => [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected()}
          onChange={(checked) => table.toggleAllPageRowsSelected(checked)}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onChange={(checked) => row.toggleSelected(checked)}
        />
      ),
      enableSorting: false,
      size: 40,
    },
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
            <Tooltip content="Edit Server">
              <button
                onClick={() => openEditDialog(server)}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-all duration-100 inline-flex hover:-translate-y-[1px] active:translate-y-[1px]"
              >
                <Pencil className="w-4 h-4" />
              </button>
            </Tooltip>
            <Tooltip content="Schedules">
              <button
                onClick={() => openScheduleDialog(server)}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-all duration-100 inline-flex hover:-translate-y-[1px] active:translate-y-[1px]"
              >
                <Calendar className="w-4 h-4" />
              </button>
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
  ], [isOperationPending, startServer, stopServer, restartServer, deleteServer, confirm]);

  const activeServers = myServers.filter((s) => s.status === 'running').length;
  const parseMemory = (mem: string | undefined) => {
    if (!mem) return 0;
    const match = mem.match(/^(\d+)/);
    return match ? parseInt(match[1]) : 0;
  };
  const totalMemory = myServers.reduce((acc, s) => acc + parseMemory(s.allocated_memory), 0);

  const stats = [
    { title: 'Active Servers', value: activeServers, icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Total Servers', value: myServers.length, icon: Activity, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Memory Allocated', value: `${totalMemory} GB`, icon: MemoryStick, iconColor: 'text-rose-400', bgColor: 'bg-rose-500/10' },
    { title: 'CPU Cores', value: myServers.reduce((acc, s) => acc + (s.allocated_cpu || 0), 0), icon: Cpu, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
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
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{server.name}</div>
        <StatusBadge status={server.status as 'running' | 'stopped' | 'pending' | 'error'} pulse={server.status === 'running'} />
      </div>
      <div className="text-sm text-muted-foreground">
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
          <Tooltip content="Edit Server">
            <button
              onClick={() => openEditDialog(server)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-all duration-100 inline-flex"
            >
              <Pencil className="w-4 h-4" />
            </button>
          </Tooltip>
          <Tooltip content="Schedules">
            <button
              onClick={() => openScheduleDialog(server)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-all duration-100 inline-flex"
            >
              <Calendar className="w-4 h-4" />
            </button>
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
        title="My Servers"
        subtitle="Manage your personal simulation servers"
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
          searchPlaceholder="Search by name or status..."
          mobileCardRenderer={mobileCardRenderer}
        />
      </ResourcePageLayout>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deploy New Server</DialogTitle>
            <DialogDescription>
              Create and spawn a new simulation server.
            </DialogDescription>
          </DialogHeader>
          <form id="deploy-form" onSubmit={handleDeploy} className="space-y-4 mt-4" noValidate>
            <div className="space-y-2">
              <label className="text-sm font-medium">Server Name *</label>
              <Input
                type="text"
                required
                value={deployForm.name}
                onChange={(e) => setDeployForm({ ...deployForm, name: e.target.value })}
                placeholder="my-simulation-server"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Plan *</label>
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
            <div className="space-y-2">
              <label className="text-sm font-medium">Environment *</label>
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
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium flex items-center gap-1.5">
                  <HardDrive className="w-4 h-4" />
                  Volume Mounts
                </label>
                <button
                  type="button"
                  onClick={addVolumeMount}
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add Volume
                </button>
              </div>
              
              {volumeMounts.map((mount, index) => (
                <div key={index} className="space-y-2 p-3 rounded-lg bg-surface/50 border border-border/50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">
                      {index === 0 ? 'Primary Mount' : `Additional Mount ${index}`}
                    </span>
                    {volumeMounts.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeVolumeMount(index)}
                        className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  
                  <Select
                    value={mount.volume_id}
                    onChange={(value) => updateVolumeMount(index, 'volume_id', value)}
                    placeholder="Create new volume (default)"
                  >
                    <SelectItem value="">Create new volume</SelectItem>
                    {volumes.map((vol) => (
                      <SelectItem key={vol.id} value={vol.id}>
                        {vol.display_name} ({vol.server_count > 0 ? `${vol.server_count} servers` : 'unused'})
                      </SelectItem>
                    ))}
                  </Select>
                  
                  <div className="flex gap-2">
                    <Input
                      type="text"
                      value={mount.mount_path}
                      onChange={(e) => updateVolumeMount(index, 'mount_path', e.target.value)}
                      placeholder={index === 0 ? `/home/${user?.username || 'user'}` : '/data'}
                      className="flex-1 text-sm"
                    />
                    <div className="flex gap-1">
                      <Button
                        type="button"
                        variant={mount.mode === 'read_write' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateVolumeMount(index, 'mode', 'read_write')}
                        className="text-xs px-2"
                      >
                        RW
                      </Button>
                      <Button
                        type="button"
                        variant={mount.mode === 'read_only' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateVolumeMount(index, 'mode', 'read_only')}
                        className="text-xs px-2"
                      >
                        RO
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </form>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => { setDialogOpen(false); setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write' }]); }}>
              Cancel
            </Button>
            <Button type="submit" form="deploy-form" loading={createServer.isPending || !deployForm.environment_id}>
              {createServer.isPending ? 'Deploying...' : 'Deploy'}
            </Button>
          </DialogFooter>
          <DialogClose onClick={() => setDialogOpen(false)} />
        </DialogContent>
      </Dialog>
      {/* Edit Server Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit Server</DialogTitle>
            <DialogDescription>
              Update server configuration. Changes to plan, environment, or volumes require a container restart.
            </DialogDescription>
          </DialogHeader>
          <form id="edit-form" onSubmit={handleEdit} className="space-y-4 mt-4" noValidate>
            <div className="space-y-2">
              <label className="text-sm font-medium">Server Name</label>
              <Input
                type="text"
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                placeholder="my-simulation-server"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Plan</label>
              <Select
                value={editForm.plan_id}
                onChange={(value) => setEditForm({ ...editForm, plan_id: value })}
                placeholder="Select a plan..."
              >
                {plans.map((plan) => (
                  <SelectItem key={plan.id} value={plan.id}>
                    {plan.name} ({plan.cpu_limit} CPU / {plan.memory_limit})
                  </SelectItem>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Environment</label>
              <Select
                value={editForm.environment_id}
                onChange={(value) => setEditForm({ ...editForm, environment_id: value })}
                placeholder="Select an environment..."
              >
                {environments.map((env) => (
                  <SelectItem key={env.id} value={env.id}>
                    {env.name} ({env.slug})
                  </SelectItem>
                ))}
              </Select>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium flex items-center gap-1.5">
                  <HardDrive className="w-4 h-4" />
                  Volume Mounts
                </label>
                <button
                  type="button"
                  onClick={addEditVolumeMount}
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add Volume
                </button>
              </div>
              
              {editVolumeMounts.map((mount, index) => (
                <div key={index} className="space-y-2 p-3 rounded-lg bg-surface/50 border border-border/50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">
                      {index === 0 ? 'Primary Mount' : `Additional Mount ${index}`}
                    </span>
                    {editVolumeMounts.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeEditVolumeMount(index)}
                        className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  
                  <Select
                    value={mount.volume_id}
                    onChange={(value) => updateEditVolumeMount(index, 'volume_id', value)}
                    placeholder="Select a volume..."
                  >
                    <SelectItem value="">Create new volume</SelectItem>
                    {volumes.map((vol) => (
                      <SelectItem key={vol.id} value={vol.id}>
                        {vol.display_name} ({vol.server_count > 0 ? `${vol.server_count} servers` : 'unused'})
                      </SelectItem>
                    ))}
                  </Select>
                  
                  <div className="flex gap-2">
                    <Input
                      type="text"
                      value={mount.mount_path}
                      onChange={(e) => updateEditVolumeMount(index, 'mount_path', e.target.value)}
                      placeholder={index === 0 ? `/home/${user?.username || 'user'}` : '/data'}
                      className="flex-1 text-sm"
                    />
                    <div className="flex gap-1">
                      <Button
                        type="button"
                        variant={mount.mode === 'read_write' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateEditVolumeMount(index, 'mode', 'read_write')}
                        className="text-xs px-2"
                      >
                        RW
                      </Button>
                      <Button
                        type="button"
                        variant={mount.mode === 'read_only' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateEditVolumeMount(index, 'mode', 'read_only')}
                        className="text-xs px-2"
                      >
                        RO
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            
            <div className="flex items-center gap-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
              <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
              <p className="text-xs text-amber-400">
                Changing plan, environment, or volumes will stop and recreate the container.
              </p>
            </div>
          </form>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => { setEditDialogOpen(false); setEditServerId(null); }}>
              Cancel
            </Button>
            <Button type="submit" form="edit-form" loading={updateServer.isPending}>
              {updateServer.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
          </DialogFooter>
          <DialogClose onClick={() => setEditDialogOpen(false)} />
        </DialogContent>
      </Dialog>

      {/* Schedule Dialog */}
      <ScheduleDialog
        open={scheduleDialogOpen}
        onOpenChange={setScheduleDialogOpen}
        serverId={scheduleServerId}
      />

      {dialog}
    </>
  );
}

function ScheduleDialog({ open, onOpenChange, serverId }: { open: boolean; onOpenChange: (v: boolean) => void; serverId: string | null }) {
  const [showForm, setShowForm] = useState(false);
  const [newSchedule, setNewSchedule] = useState<{ action: 'start' | 'stop' | 'restart'; cron_expression: string; timezone: string; is_active: boolean }>({ action: 'start', cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true });
  const { data: schedules = [] } = useServerSchedules(serverId || '');
  const createSchedule = useCreateSchedule();
  const deleteSchedule = useDeleteSchedule();
  const { confirm, dialog } = useConfirmDialog();

  if (!serverId) return null;

  const actionMeta = (action: string) => {
    switch (action) {
      case 'start': return { icon: Play, label: 'Start', bg: 'bg-emerald-500/10', text: 'text-emerald-400', iconBg: 'bg-emerald-500/15' };
      case 'stop': return { icon: Square, label: 'Stop', bg: 'bg-amber-500/10', text: 'text-amber-400', iconBg: 'bg-amber-500/15' };
      default: return { icon: RotateCcw, label: 'Restart', bg: 'bg-primary/10', text: 'text-primary', iconBg: 'bg-primary/15' };
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Scheduled Actions</DialogTitle>
          <DialogDescription>
            Automate server start, stop, and restart.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 mt-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">Schedules</h3>
            <button
              onClick={() => setShowForm(!showForm)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-all text-sm font-medium"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Schedule
            </button>
          </div>

          {showForm && (
            <div className="p-4 rounded-xl bg-surface/50 border border-border/50 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Action</label>
                  <Select
                    value={newSchedule.action}
                    onChange={(value) => setNewSchedule({ ...newSchedule, action: value as 'start' | 'stop' | 'restart' })}
                  >
                    <SelectItem value="start">Start</SelectItem>
                    <SelectItem value="stop">Stop</SelectItem>
                    <SelectItem value="restart">Restart</SelectItem>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Timezone</label>
                  <Input
                    type="text"
                    value={newSchedule.timezone}
                    onChange={(e) => setNewSchedule({ ...newSchedule, timezone: e.target.value })}
                    placeholder="UTC"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Schedule</label>
                <CronBuilder
                  value={newSchedule.cron_expression}
                  onChange={(cron) => setNewSchedule({ ...newSchedule, cron_expression: cron })}
                />
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    createSchedule.mutate({ serverId, data: newSchedule });
                    setShowForm(false);
                    setNewSchedule({ action: 'start', cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true });
                  }}
                  className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                >
                  Create Schedule
                </button>
                <button
                  onClick={() => setShowForm(false)}
                  className="px-4 py-2 rounded-lg bg-muted text-muted-foreground text-sm font-medium hover:bg-muted/80 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {!showForm && schedules.length === 0 && (
            <div className="text-center py-10 text-muted-foreground">
              <Calendar className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p className="text-sm">No schedules configured</p>
              <p className="text-xs mt-1">Create a schedule to automate server actions</p>
            </div>
          )}

          {schedules.length > 0 && (
            <div className="space-y-2">
              {schedules.map((schedule) => {
                const meta = actionMeta(schedule.action);
                const ActionIcon = meta.icon;
                const parsed = parseCron(schedule.cron_expression);
                const humanCron = humanizeSchedule(parsed.minute, parsed.hour, parsed.days);
                return (
                  <div key={schedule.id} className="flex items-center gap-3 p-3 rounded-xl bg-surface/50 border border-border/50">
                    <div className={cn("p-2.5 rounded-xl flex-shrink-0", meta.iconBg)}>
                      <ActionIcon className={cn("w-4 h-4", meta.text)} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium capitalize">{meta.label}</span>
                        <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", schedule.is_active ? "bg-emerald-500/10 text-emerald-400" : "bg-muted text-muted-foreground")}>
                          {schedule.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <Clock className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                        <span className="text-xs text-muted-foreground">{humanCron}</span>
                      </div>
                      {schedule.next_run_at && (
                        <p className="text-xs text-muted-foreground/70 mt-0.5">
                          Next: {formatDate(schedule.next_run_at)}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={async () => {
                        const confirmed = await confirm({
                          title: 'Delete Schedule',
                          description: 'Are you sure you want to delete this schedule?',
                          confirmLabel: 'Delete',
                          cancelLabel: 'Cancel',
                          variant: 'danger',
                        });
                        if (confirmed) deleteSchedule.mutate({ serverId, scheduleId: schedule.id });
                      }}
                      className="p-2 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors flex-shrink-0"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {dialog}
        <DialogClose onClick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
