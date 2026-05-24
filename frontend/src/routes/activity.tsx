import { createFileRoute } from '@tanstack/react-router';
import { useState, useEffect, useRef } from 'react';
import type { ColumnDef, SortingState, ColumnFiltersState } from '@tanstack/react-table';
import {
  Activity,
  Server,
  User,
  Settings,
  CreditCard,
  HardDrive,
  Box,
  Shield,
  Clock,
  Hash,
  Eye,
} from 'lucide-react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { useDataTable } from '../hooks/use-data-table';
import { useActivity, type ActivityItem } from '../hooks/use-activity';
import { formatDate, cn } from '../lib/utils';
import { useThemeStore } from '../stores/theme-store';
import { Dialog, DialogContent, DialogClose } from '../components/ui/dialog';

const actionIcons: Record<string, typeof Hash> = {
  server: Server,
  user: User,
  setting: Settings,
  config: Settings,
  credit: CreditCard,
  nuke: CreditCard,
  volume: HardDrive,
  environment: Box,
  plan: Box,
  admin: Shield,
  permission: Shield,
  login: User,
  logout: User,
};

const actionColors: Record<string, string> = {
  create: 'text-emerald-400 bg-emerald-400/10',
  spawn: 'text-emerald-400 bg-emerald-400/10',
  start: 'text-emerald-400 bg-emerald-400/10',
  enable: 'text-emerald-400 bg-emerald-400/10',
  update: 'text-amber-400 bg-amber-400/10',
  edit: 'text-amber-400 bg-amber-400/10',
  delete: 'text-red-400 bg-red-400/10',
  remove: 'text-red-400 bg-red-400/10',
  stop: 'text-red-400 bg-red-400/10',
  disable: 'text-red-400 bg-red-400/10',
  login: 'text-blue-400 bg-blue-400/10',
  auth: 'text-blue-400 bg-blue-400/10',
};

function getActionIcon(action: string) {
  const key = Object.keys(actionIcons).find((k) => action.toLowerCase().includes(k));
  return key ? actionIcons[key] : Activity;
}

function getActionColor(action: string) {
  const key = Object.keys(actionColors).find((k) => action.toLowerCase().includes(k));
  return key ? actionColors[key] : 'text-muted-foreground bg-muted/30';
}

function formatActionName(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}

function formatDetailValue(_key: string, value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 40);
  return String(value).slice(0, 60);
}

export const Route = createFileRoute('/activity')({
  component: ActivityPage,
});

function ActivityPage() {
  const [selectedActivity, setSelectedActivity] = useState<ActivityItem | null>(null);
  const [sorting, setSorting] = useState<SortingState>([{ id: 'timestamp', desc: true }]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);

  const {
    state: tableState,
    setPage,
    setLimit,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 25, defaultSortBy: 'timestamp' });

  // Sync React Table column filters with API filter state
  const prevColumnFiltersRef = useRef<ColumnFiltersState>([]);
  useEffect(() => {
    const currentIds = new Set(columnFilters.map((f) => f.id));

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

  const { data, isLoading, isError, error } = useActivity({
    page: tableState.page,
    limit: tableState.limit,
    action: tableState.filters.action as string,
    target_type: tableState.filters.target_type as string,
  });

  const activities = data?.activities || [];
  const pagination = data?.pagination;

  const columns: ColumnDef<ActivityItem>[] = [
    {
      accessorKey: 'action',
      header: 'Action',
      cell: ({ row }) => {
        const action = row.getValue('action') as string;
        const Icon = getActionIcon(action);
        return (
          <div className="flex items-center gap-2">
            <div className={cn('p-1.5 rounded-md', getActionColor(action))}>
              <Icon className="w-3.5 h-3.5" />
            </div>
            <span className="font-medium text-sm">{formatActionName(action)}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'target_type',
      header: 'Target',
      cell: ({ row }) => {
        const targetType = row.getValue('target_type') as string;
        const targetId = row.original.target_id;
        return (
          <div className="text-sm">
            <span className="text-muted-foreground">{targetType}</span>
            {targetId && (
              <span className="ml-1.5 font-mono text-xs">{targetId.slice(0, 8)}...</span>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'timestamp',
      header: 'Time',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">{formatDate(row.getValue('timestamp') as string)}</span>
        </div>
      ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <button
          onClick={() => setSelectedActivity(row.original)}
          className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
        >
          <Eye className="w-4 h-4" />
        </button>
      ),
      enableSorting: false,
      size: 50,
    },
  ];

  const filters = [
    {
      key: 'action',
      label: 'Action',
      options: [
        { label: 'Create', value: 'create' },
        { label: 'Update', value: 'update' },
        { label: 'Delete', value: 'delete' },
        { label: 'Start', value: 'start' },
        { label: 'Stop', value: 'stop' },
        { label: 'Restart', value: 'restart' },
      ],
    },
    {
      key: 'target_type',
      label: 'Target',
      options: [
        { label: 'Servers', value: 'servers' },
        { label: 'Volumes', value: 'volumes' },
        { label: 'Users', value: 'users' },
      ],
    },
  ];

  const mobileCardRenderer = (item: ActivityItem) => {
    const Icon = getActionIcon(item.action);
    return (
      <div className="p-3 space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className={cn('p-1 rounded', getActionColor(item.action), 'shrink-0')}>
              <Icon className="w-3 h-3" />
            </div>
            <span className="font-medium text-sm truncate">{formatActionName(item.action)}</span>
          </div>
          <button
            onClick={() => setSelectedActivity(item)}
            className="p-1 rounded-md hover:bg-primary/10 text-primary transition-colors inline-flex shrink-0"
          >
            <Eye className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground flex-wrap">
          <span className="text-foreground font-medium">{item.target_type}</span>
          <span className="text-border">·</span>
          <span className="tabular-nums">{formatDate(item.timestamp)}</span>
        </div>
      </div>
    );
  };

  return (
    <>
      <ResourcePageLayout
        title="Activity"
        subtitle="Track your actions across the platform"
        icon={Activity}
      >
        <DataTable
          columns={columns}
          data={activities}
          totalCount={pagination?.total || 0}
          pageCount={pagination?.total_pages || 1}
          page={tableState.page}
          limit={tableState.limit}
          sorting={sorting}
          rowSelection={{}}
          columnFilters={[]}
          columnVisibility={{}}
          globalFilter={tableState.search}
          isLoading={isLoading}
          isError={isError}
          errorMessage={error?.message}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onSortingChange={setSorting}
          onRowSelectionChange={() => {}}
          onColumnFiltersChange={setColumnFilters}
          onColumnVisibilityChange={() => {}}
          onGlobalFilterChange={setSearch}
          getRowId={(row) => row.id}
          filters={filters}
          searchable
          searchPlaceholder="Search activity..."
          density={useThemeStore().density}
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={false}
        />
      </ResourcePageLayout>

      {/* Detail Drawer */}
      <Dialog open={!!selectedActivity} onOpenChange={(open) => !open && setSelectedActivity(null)}>
        <DialogContent className="sm:max-w-lg pt-6">
          <DialogClose onClick={() => setSelectedActivity(null)} />
          {selectedActivity && (
            <div className="space-y-5">
              <div className="flex items-start gap-3">
                <div className={cn('p-2.5 rounded-xl', getActionColor(selectedActivity.action), 'shrink-0')}>
                  {(() => {
                    const Icon = getActionIcon(selectedActivity.action);
                    return <Icon className="w-5 h-5" />;
                  })()}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-base leading-tight">
                    {formatActionName(selectedActivity.action)}
                  </h3>
                  <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                    <Clock className="w-3 h-3" />
                    <span>{formatDate(selectedActivity.timestamp)}</span>
                  </div>
                </div>
              </div>

              <div className="space-y-3">
                {selectedActivity.target_type && (
                  <div className="bubble p-3.5">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">Target</p>
                    <p className="text-sm font-medium">{selectedActivity.target_type}</p>
                    {selectedActivity.target_id && (
                      <p className="text-xs text-muted-foreground font-mono mt-0.5">{selectedActivity.target_id}</p>
                    )}
                  </div>
                )}

                {Object.keys(selectedActivity.details).length > 0 && (
                  <div className="bubble p-3.5 space-y-2">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Details</p>
                    {Object.entries(selectedActivity.details).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
                        <span className="text-xs text-muted-foreground">{key}</span>
                        <span className="text-sm font-mono">{formatDetailValue(key, value)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
