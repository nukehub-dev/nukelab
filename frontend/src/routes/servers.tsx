import { createFileRoute, Link } from '@tanstack/react-router';
import { Server, Activity, Cpu, MemoryStick, Play, Square, RotateCcw, Trash2, ExternalLink, Eye } from 'lucide-react';
import { useState } from 'react';
import { type ColumnDef, type SortingState, type ColumnFiltersState, type VisibilityState } from '@tanstack/react-table';
import { motion } from 'framer-motion';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useServers, useServerActions } from '../hooks/use-servers';
import { useEnvironments } from '../hooks/use-environments';
import { useDataTable } from '../hooks/use-data-table';
import { formatDate } from '../lib/utils';
import type { Server as ServerType } from '../types/api';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';

export const Route = createFileRoute('/servers')({
  component: ServersPage,
});

function ServersPage() {
  const { data: servers = [], isLoading, isError, error } = useServers();
  const { createServer, startServer, stopServer, restartServer, deleteServer } = useServerActions();
  const { data: envData } = useEnvironments({ is_active: true, limit: 100 });
  
  const {
    state: tableState,
    setPage,
    setLimit,
    setSearch,
  } = useDataTable({ defaultLimit: 10 });

  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

  const [dialogOpen, setDialogOpen] = useState(false);
  const [deployForm, setDeployForm] = useState({
    name: '',
    plan_id: 'basic',
    environment_id: '',
  });

  const environments = envData?.data || [];

  // Client-side filtering and sorting for now since API doesn't support it fully
  const filteredServers = servers.filter((server) => {
    if (tableState.search) {
      const search = tableState.search.toLowerCase();
      return (
        server.name.toLowerCase().includes(search) ||
        server.status.toLowerCase().includes(search)
      );
    }
    return true;
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
    createServer.mutate({
      name: deployForm.name,
      plan_id: deployForm.plan_id,
      environment_id: deployForm.environment_id,
    });
    setDialogOpen(false);
    setDeployForm({ name: '', plan_id: 'basic', environment_id: '' });
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
    {
      accessorKey: 'external_url',
      header: 'URL',
      cell: ({ row }) => {
        const url = row.getValue('external_url') as string;
        if (!url) return <span className="text-muted-foreground">—</span>;
        return (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Open
          </a>
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
            <Link
              to="/servers/$serverId"
              params={{ serverId: server.id }}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
              title="View Details"
            >
              <Eye className="w-4 h-4" />
            </Link>
            {server.status === 'stopped' && (
              <motion.button
                onClick={() => startServer.mutate(server.id)}
                disabled={startServer.isPending}
                className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors"
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                title="Start"
              >
                <Play className="w-4 h-4" />
              </motion.button>
            )}
            {server.status === 'running' && (
              <motion.button
                onClick={() => stopServer.mutate(server.id)}
                disabled={stopServer.isPending}
                className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors"
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                title="Stop"
              >
                <Square className="w-4 h-4" />
              </motion.button>
            )}
            <motion.button
              onClick={() => restartServer.mutate(server.id)}
              disabled={restartServer.isPending}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              title="Restart"
            >
              <RotateCcw className="w-4 h-4" />
            </motion.button>
            <motion.button
              onClick={() => {
                if (confirm('Are you sure you want to delete this server?')) {
                  deleteServer.mutate(server.id);
                }
              }}
              disabled={deleteServer.isPending}
              className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              title="Delete"
            >
              <Trash2 className="w-4 h-4" />
            </motion.button>
          </div>
        );
      },
      enableSorting: false,
    },
  ];

  const activeServers = servers.filter((s) => s.status === 'running').length;
  const totalMemory = servers.reduce((acc, s) => acc + (s.allocated_memory || 0), 0);

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
      onClick: (ids: string[]) => {
        if (confirm(`Are you sure you want to delete ${ids.length} servers?`)) {
          ids.forEach((id) => deleteServer.mutate(id));
        }
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
      <div className="text-sm text-muted-foreground"
      >
        Created: {formatDate(server.created_at)}
      </div>
      {server.external_url && (
        <a
          href={server.external_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          Open Server
        </a>
      )}
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
          searchPlaceholder="Search servers..."
          mobileCardRenderer={mobileCardRenderer}
        />
      </ResourcePageLayout>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}
      >
        <DialogContent className="max-w-md"
        >
          <DialogHeader>
            <DialogTitle>Deploy New Server</DialogTitle>
            <DialogDescription>
              Create and spawn a new simulation server.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleDeploy} className="space-y-4 mt-4"
          >
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Server Name *</label>
              <input
                type="text"
                required
                value={deployForm.name}
                onChange={(e) => setDeployForm({ ...deployForm, name: e.target.value })}
                className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                placeholder="my-simulation-server"
              />
            </div>
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Plan *</label>
              <select
                required
                value={deployForm.plan_id}
                onChange={(e) => setDeployForm({ ...deployForm, plan_id: e.target.value })}
                className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
              >
                <option value="basic">Basic (2 CPU / 4GB)</option>
                <option value="standard">Standard (4 CPU / 8GB)</option>
                <option value="premium">Premium (8 CPU / 16GB)</option>
                <option value="ultra">Ultra (16 CPU / 32GB)</option>
              </select>
            </div>
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Environment *</label>
              <select
                required
                value={deployForm.environment_id}
                onChange={(e) => setDeployForm({ ...deployForm, environment_id: e.target.value })}
                className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
              >
                <option value="">Select an environment...</option>
                {environments.map((env) => (
                  <option key={env.id} value={env.id}>
                    {env.name} ({env.slug})
                  </option>
                ))}
              </select>
            </div>
            <DialogFooter>
              <button
                type="button"
                onClick={() => setDialogOpen(false)}
                className="px-4 py-2 rounded-lg border border-input text-sm font-medium hover:bg-accent transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createServer.isPending || !deployForm.environment_id}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {createServer.isPending ? 'Deploying...' : 'Deploy'}
              </button>
            </DialogFooter>
          </form>
          <DialogClose onClick={() => setDialogOpen(false)} />
        </DialogContent>
      </Dialog>
    </>
  );
}
