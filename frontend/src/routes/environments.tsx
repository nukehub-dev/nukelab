import { createFileRoute } from '@tanstack/react-router';
import { Boxes, Layers, GitBranch, CheckCircle2, XCircle, Copy } from 'lucide-react';
import { useState } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useEnvironments, useEnvironmentActions } from '../hooks/use-environments';
import { useDataTable } from '../hooks/use-data-table';
import { formatDate } from '../lib/utils';
import type { Environment as EnvironmentType } from '../types/api';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';

export const Route = createFileRoute('/environments')({
  component: EnvironmentsPage,
});

function EnvironmentsPage() {
  const {
    state: tableState,
    setPage,
    setLimit,
    setSort,
    setSearch,
  } = useDataTable({ defaultLimit: 20 });

  const [sorting, setSorting] = useState<SortingState>([
    { id: tableState.sortBy, desc: tableState.sortOrder === 'desc' }
  ]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

  const { data, isLoading, isError, error } = useEnvironments({
    category: tableState.filters.category as string,
    is_active: tableState.filters.is_active === 'true' ? true : tableState.filters.is_active === 'false' ? false : undefined,
    search: tableState.search,
    page: tableState.page,
    limit: tableState.limit,
  });

  const { activateEnvironment, deactivateEnvironment } = useEnvironmentActions();

  const environments = data?.data || [];
  const pagination = data?.pagination;

  const columns: ColumnDef<EnvironmentType>[] = [
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
        <div className="space-y-1">
          <div className="font-medium">{row.getValue('name')}</div>
          {row.original.description && (
            <div className="text-xs text-muted-foreground line-clamp-1">{row.original.description}</div>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'slug',
      header: 'Slug',
      cell: ({ row }) => (
        <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{row.getValue('slug')}</code>
      ),
    },
    {
      accessorKey: 'image',
      header: 'Image',
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground font-mono">{row.getValue('image')}</span>
      ),
    },
    {
      accessorKey: 'category',
      header: 'Category',
      cell: ({ row }) => {
        const category = row.getValue('category') as string;
        return category ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-secondary text-secondary-foreground">
            {category}
          </span>
        ) : (
          <span className="text-muted-foreground text-sm">—</span>
        );
      },
    },
    {
      accessorKey: 'is_active',
      header: 'Status',
      cell: ({ row }) => {
        const isActive = row.getValue('is_active') as boolean;
        return (
          <StatusBadge
            status={isActive ? 'running' : 'stopped'}
            label={isActive ? 'Active' : 'Inactive'}
            pulse={isActive}
          />
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
        const env = row.original;
        return (
          <div className="flex items-center gap-1">
            {env.is_active ? (
              <button
                onClick={() => deactivateEnvironment.mutate(env.id)}
                disabled={deactivateEnvironment.isPending}
                className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors"
                title="Deactivate"
              >
                <XCircle className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={() => activateEnvironment.mutate(env.id)}
                disabled={activateEnvironment.isPending}
                className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors"
                title="Activate"
              >
                <CheckCircle2 className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={() => console.log('Clone', env.id)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
              title="Clone"
            >
              <Copy className="w-4 h-4" />
            </button>
          </div>
        );
      },
      enableSorting: false,
    },
  ];

  const activeEnvs = environments.filter((e) => e.is_active).length;
  const publicEnvs = environments.filter((e) => e.is_public).length;

  const stats = [
    { title: 'Environments', value: pagination?.total || environments.length, icon: Boxes, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: activeEnvs, icon: CheckCircle2, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Public', value: publicEnvs, icon: GitBranch, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Categories', value: new Set(environments.map((e) => e.category).filter(Boolean)).size, icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
  ];

  const bulkActions = [
    {
      label: 'Activate',
      icon: <CheckCircle2 className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => activateEnvironment.mutate(id));
      },
    },
    {
      label: 'Deactivate',
      icon: <XCircle className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => deactivateEnvironment.mutate(id));
      },
    },
  ];

  const filters = [
    {
      key: 'category',
      label: 'Category',
      options: [
        { label: 'Simulation', value: 'simulation' },
        { label: 'Development', value: 'development' },
        { label: 'Production', value: 'production' },
      ],
    },
    {
      key: 'is_active',
      label: 'Status',
      options: [
        { label: 'Active', value: 'true' },
        { label: 'Inactive', value: 'false' },
      ],
    },
  ];

  const mobileCardRenderer = (env: EnvironmentType) => (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{env.name}</div>
        <StatusBadge status={env.is_active ? 'running' : 'stopped'} pulse={env.is_active} />
      </div>
      <div className="text-xs text-muted-foreground">{env.description || 'No description'}</div>
      <div className="flex items-center gap-2">
        <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{env.slug}</code>
        {env.category && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-secondary">
            {env.category}
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground">
        Created: {formatDate(env.created_at)}
      </div>
    </div>
  );

  return (
    <ResourcePageLayout
      title="Environments"
      subtitle="Manage deployment environments"
      icon={Boxes}
      stats={stats}
      actions={[
        { action: 'deploy', onClick: () => console.log('Create environment') },
      ]}
    >
      <DataTable
        columns={columns}
        data={environments}
        totalCount={pagination?.total || 0}
        pageCount={pagination?.totalPages || 1}
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
        bulkActions={bulkActions}
        filters={filters}
        searchable
        searchPlaceholder="Search environments..."
        mobileCardRenderer={mobileCardRenderer}
      />
    </ResourcePageLayout>
  );
}
