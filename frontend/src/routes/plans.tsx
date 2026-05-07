import { createFileRoute } from '@tanstack/react-router';
import { CreditCard, Cpu, MemoryStick, HardDrive, CheckCircle2, XCircle, Pencil, Trash2 } from 'lucide-react';
import { useState, useMemo, useEffect, useRef } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { usePlans, usePlanActions } from '../hooks/use-plans';
import { useDataTable } from '../hooks/use-data-table';
import { useAuthStore } from '../stores/auth-store';
import { formatDate } from '../lib/utils';
import type { Plan } from '../types/api';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { motion } from 'framer-motion';
import { Tooltip } from '../components/ui/tooltip';

export const Route = createFileRoute('/plans')({
  component: PlansPage,
});

function PlansPage() {
  const canManagePlans = useAuthStore((state) => state.canManagePlans());

  const {
    state: tableState,
    setPage,
    setLimit,
    setSort,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 20 });

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
    
    // Add/update filters
    columnFilters.forEach((filter) => {
      if (filter.value !== undefined && filter.value !== null) {
        setFilter(filter.id, String(filter.value));
      }
    });
    
    // Remove filters that no longer exist
    prevColumnFiltersRef.current.forEach((filter) => {
      if (!currentIds.has(filter.id)) {
        setFilter(filter.id, null);
      }
    });
    
    prevColumnFiltersRef.current = columnFilters;
  }, [columnFilters, setFilter]);

  const { data, isLoading, isError, error } = usePlans({
    category: tableState.filters.category as string,
    is_active: tableState.filters.is_active === 'true' ? true : tableState.filters.is_active === 'false' ? false : undefined,
    page: tableState.page,
    limit: tableState.limit,
  });

  const { createPlan, updatePlan, deletePlan, activatePlan, deactivatePlan } = usePlanActions();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingPlan, setEditingPlan] = useState<Plan | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    slug: '',
    description: '',
    category: 'cpu',
    cpu_limit: 1,
    memory_limit: '2g',
    disk_limit: '10g',
    gpu_limit: 0,
    max_servers_per_user: 3,
    cost_per_hour: 10,
    cooldown_seconds: 0,
    requires_approval: false,
    allowed_roles: ['user'],
    priority: 0,
  });

  const plans = data?.data || [];
  const pagination = data?.pagination;

  const openCreateDialog = () => {
    setEditingPlan(null);
    setFormData({
      name: '',
      slug: '',
      description: '',
      category: 'cpu',
      cpu_limit: 1,
      memory_limit: '2g',
      disk_limit: '10g',
      gpu_limit: 0,
      max_servers_per_user: 3,
      cost_per_hour: 10,
      cooldown_seconds: 0,
      requires_approval: false,
      allowed_roles: ['user'],
      priority: 0,
    });
    setDialogOpen(true);
  };

  const openEditDialog = (plan: Plan) => {
    setEditingPlan(plan);
    setFormData({
      name: plan.name,
      slug: plan.slug,
      description: plan.description || '',
      category: plan.category,
      cpu_limit: plan.cpu_limit,
      memory_limit: plan.memory_limit,
      disk_limit: plan.disk_limit,
      gpu_limit: plan.gpu_limit,
      max_servers_per_user: plan.max_servers_per_user,
      cost_per_hour: plan.cost_per_hour,
      cooldown_seconds: plan.cooldown_seconds,
      requires_approval: plan.requires_approval,
      allowed_roles: plan.allowed_roles || ['user'],
      priority: plan.priority,
    });
    setDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingPlan) {
      updatePlan.mutate({
        planId: editingPlan.id,
        data: {
          name: formData.name,
          description: formData.description || undefined,
          category: formData.category,
          cpu_limit: formData.cpu_limit,
          memory_limit: formData.memory_limit,
          disk_limit: formData.disk_limit,
          gpu_limit: formData.gpu_limit,
          max_servers_per_user: formData.max_servers_per_user,
          cost_per_hour: formData.cost_per_hour,
          cooldown_seconds: formData.cooldown_seconds,
          requires_approval: formData.requires_approval,
          allowed_roles: formData.allowed_roles,
          priority: formData.priority,
        },
      });
    } else {
      createPlan.mutate({
        name: formData.name,
        slug: formData.slug,
        description: formData.description || undefined,
        category: formData.category,
        cpu_limit: formData.cpu_limit,
        memory_limit: formData.memory_limit,
        disk_limit: formData.disk_limit,
        gpu_limit: formData.gpu_limit,
        max_servers_per_user: formData.max_servers_per_user,
        cost_per_hour: formData.cost_per_hour,
        cooldown_seconds: formData.cooldown_seconds,
        requires_approval: formData.requires_approval,
        allowed_roles: formData.allowed_roles,
        priority: formData.priority,
      });
    }
    setDialogOpen(false);
  };

  const columns: ColumnDef<Plan>[] = [
    ...(canManagePlans ? [{
      id: 'select' as const,
      header: ({ table }: { table: { getIsAllPageRowsSelected: () => boolean; getToggleAllPageRowsSelectedHandler: () => (e: React.ChangeEvent<HTMLInputElement>) => void } }) => (
        <input
          type="checkbox"
          checked={table.getIsAllPageRowsSelected()}
          onChange={table.getToggleAllPageRowsSelectedHandler()}
          className="rounded border-border"
        />
      ),
      cell: ({ row }: { row: { getIsSelected: () => boolean; getToggleSelectedHandler: () => (e: React.ChangeEvent<HTMLInputElement>) => void } }) => (
        <input
          type="checkbox"
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          className="rounded border-border"
        />
      ),
      enableSorting: false,
      size: 40,
    }] : []),
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <div className="space-y-1"
        >
          <div className="font-medium"
          >{row.getValue('name')}</div>
          {row.original.description && (
            <div className="text-xs text-muted-foreground line-clamp-1"
            >{row.original.description}</div>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'slug',
      header: 'Slug',
      cell: ({ row }) => (
        <code className="text-xs bg-muted px-1.5 py-0.5 rounded"
        >{row.getValue('slug')}</code>
      ),
    },
    {
      accessorKey: 'cpu_limit',
      header: 'CPU',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5"
        >
          <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm"
          >{row.getValue('cpu_limit')} cores</span>
        </div>
      ),
    },
    {
      accessorKey: 'memory_limit',
      header: 'Memory',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5"
        >
          <MemoryStick className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm"
          >{row.getValue('memory_limit')}</span>
        </div>
      ),
    },
    {
      accessorKey: 'disk_limit',
      header: 'Disk',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5"
        >
          <HardDrive className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm"
          >{row.getValue('disk_limit')}</span>
        </div>
      ),
    },
    {
      accessorKey: 'cost_per_hour',
      header: 'Cost/hr',
      cell: ({ row }) => (
        <span className="font-mono text-sm"
        >{row.getValue('cost_per_hour')} nukes</span>
      ),
    },
    ...(canManagePlans ? [{
      accessorKey: 'is_active' as const,
      header: 'Status',
      cell: ({ row }: { row: { getValue: (key: string) => unknown } }) => {
        const isActive = row.getValue('is_active') as boolean;
        return (
          <StatusBadge
            status={isActive ? 'running' : 'stopped'}
            label={isActive ? 'Active' : 'Inactive'}
            pulse={isActive}
          />
        );
      },
    }] : []),
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: ({ row }) => formatDate(row.getValue('created_at') as string),
    },
    ...(canManagePlans ? [{
      id: 'actions' as const,
      header: 'Actions',
      cell: ({ row }: { row: { original: Plan } }) => {
        const plan = row.original;
        return (
          <div className="flex items-center gap-1"
          >
            <Tooltip content="Edit">
              <motion.button
                onClick={() => openEditDialog(plan)}
                className="inline-flex p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
                
                
              >
                <Pencil className="w-4 h-4" />
              </motion.button>
            </Tooltip>
            {plan.is_active ? (
              <Tooltip content="Deactivate">
                <motion.button
                  onClick={() => deactivatePlan.mutate(plan.id)}
                  disabled={deactivatePlan.isPending}
                  className="inline-flex p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors"
                  
                  
                >
                  <XCircle className="w-4 h-4" />
                </motion.button>
              </Tooltip>
            ) : (
              <Tooltip content="Activate">
                <motion.button
                  onClick={() => activatePlan.mutate(plan.id)}
                  disabled={activatePlan.isPending}
                  className="inline-flex p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors"
                  
                  
                >
                  <CheckCircle2 className="w-4 h-4" />
                </motion.button>
              </Tooltip>
            )}
            <Tooltip content="Delete">
              <motion.button
                onClick={() => {
                  if (confirm(`Are you sure you want to delete ${plan.name}?`)) {
                    deletePlan.mutate(plan.id);
                  }
                }}
                disabled={deletePlan.isPending}
                  className="inline-flex p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
                  
                  
                >
                  <Trash2 className="w-4 h-4" />
              </motion.button>
            </Tooltip>
          </div>
        );
      },
      enableSorting: false,
    }] : []),
  ];

  const activePlans = plans.filter((p) => p.is_active).length;
  const totalCpu = plans.reduce((acc, p) => acc + (p.cpu_limit || 0), 0);

  const stats = [
    { title: 'Plans', value: pagination?.total || plans.length, icon: CreditCard, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: activePlans, icon: CheckCircle2, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Total CPU', value: `${totalCpu} cores`, icon: Cpu, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Avg Cost', value: plans.length > 0 ? `${Math.round(plans.reduce((acc, p) => acc + p.cost_per_hour, 0) / plans.length)} nukes/hr` : '0', icon: CreditCard, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
  ];

  const bulkActions = canManagePlans ? [
    {
      label: 'Activate',
      icon: <CheckCircle2 className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => activatePlan.mutate(id));
      },
    },
    {
      label: 'Deactivate',
      icon: <XCircle className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => deactivatePlan.mutate(id));
      },
    },
  ] : [];

  // Derive categories dynamically from actual data
  const categories = useMemo(() => {
    const cats = [...new Set(plans.map((p) => p.category).filter(Boolean))];
    return cats.map((cat) => ({ label: cat as string, value: cat as string }));
  }, [plans]);

  const filters = [
    ...(categories.length > 0 ? [{
      key: 'category' as const,
      label: 'Category',
      options: categories,
    }] : []),
    {
      key: 'is_active' as const,
      label: 'Status',
      options: [
        { label: 'Active', value: 'true' },
        { label: 'Inactive', value: 'false' },
      ],
    },
  ];

  const mobileCardRenderer = (plan: Plan) => (
    <div className="p-4 space-y-3"
    >
      <div className="flex items-center justify-between"
      >
        <div className="font-medium"
        >{plan.name}</div>
        <StatusBadge status={plan.is_active ? 'running' : 'stopped'} label={plan.is_active ? 'Active' : 'Inactive'} pulse={plan.is_active} />
      </div>
      <div className="text-xs text-muted-foreground"
      >{plan.description || 'No description'}</div>
      <div className="flex items-center gap-2 text-sm"
      >
        <code className="text-xs bg-muted px-1.5 py-0.5 rounded"
        >{plan.slug}</code>
        <span className="text-muted-foreground"
        >{plan.cpu_limit} CPU · {plan.memory_limit} RAM</span>
      </div>
      {canManagePlans ? (
        <div className="flex items-center justify-between pt-1">
          <span className="text-sm text-muted-foreground">
            {plan.cost_per_hour} nukes/hr
          </span>
          <div className="flex items-center gap-1">
          <Tooltip content="Edit">
            <button
              onClick={() => openEditDialog(plan)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
            >
              <Pencil className="w-4 h-4" />
            </button>
          </Tooltip>
          {plan.is_active ? (
            <Tooltip content="Deactivate">
              <button
                onClick={() => deactivatePlan.mutate(plan.id)}
                disabled={deactivatePlan.isPending}
                className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors inline-flex"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </Tooltip>
          ) : (
            <Tooltip content="Activate">
              <button
                onClick={() => activatePlan.mutate(plan.id)}
                disabled={activatePlan.isPending}
                className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors inline-flex"
              >
                <CheckCircle2 className="w-4 h-4" />
              </button>
            </Tooltip>
          )}
          <Tooltip content="Delete">
            <button
              onClick={() => {
                if (confirm(`Are you sure you want to delete ${plan.name}?`)) {
                  deletePlan.mutate(plan.id);
                }
              }}
              disabled={deletePlan.isPending}
              className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors inline-flex"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </Tooltip>
        </div>
      </div>
      ) : (
        <div className="text-sm text-muted-foreground pt-1">
          {plan.cost_per_hour} nukes/hr
        </div>
      )}
    </div>
  );

  return (
    <>
      <ResourcePageLayout
        title="Plans"
        subtitle="Manage server plans"
        icon={CreditCard}
        stats={stats}
        actions={canManagePlans ? [
          { 
            action: 'create',
            onClick: openCreateDialog 
          },
        ] : []}
      >
        <DataTable
          columns={columns}
          data={plans}
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
          searchPlaceholder="Search plans..."
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={canManagePlans}
        />
      </ResourcePageLayout>

      {canManagePlans && (
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}
      >
        <DialogContent className="max-w-lg"
        >
          <DialogHeader>
            <DialogTitle>{editingPlan ? 'Edit Plan' : 'Create Plan'}</DialogTitle>
            <DialogDescription>
              {editingPlan ? 'Update plan details.' : 'Create a new server plan.'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4 mt-4"
          >
            <div className="grid grid-cols-2 gap-4"
            >
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >Name *</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                  placeholder="Basic"
                />
              </div>
              {!editingPlan && (
                <div className="space-y-2"
                >
                  <label className="text-sm font-medium"
                  >Slug *</label>
                  <input
                    type="text"
                    required
                    value={formData.slug}
                    onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                    placeholder="basic"
                  />
                </div>
              )}
            </div>
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Description</label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none resize-none"
                rows={2}
                placeholder="Optional description..."
              />
            </div>
            <div className="grid grid-cols-3 gap-4"
            >
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >CPU Limit</label>
                <input
                  type="number"
                  step="0.5"
                  min={0.5}
                  value={formData.cpu_limit}
                  onChange={(e) => setFormData({ ...formData, cpu_limit: parseFloat(e.target.value) || 1 })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                />
              </div>
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >Memory</label>
                <input
                  type="text"
                  value={formData.memory_limit}
                  onChange={(e) => setFormData({ ...formData, memory_limit: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                  placeholder="2g"
                />
              </div>
              <div className="space-y-2"
              >
                <label className="text-sm font-medium">Disk</label>
                <input
                  type="text"
                  value={formData.disk_limit}
                  onChange={(e) => setFormData({ ...formData, disk_limit: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                  placeholder="10g"
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4"
            >
              <div className="space-y-2"
              >
                <label className="text-sm font-medium">GPU</label>
                <input
                  type="number"
                  min={0}
                  value={formData.gpu_limit}
                  onChange={(e) => setFormData({ ...formData, gpu_limit: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                />
              </div>
              <div className="space-y-2"
              >
                <label className="text-sm font-medium">Max Servers</label>
                <input
                  type="number"
                  min={1}
                  value={formData.max_servers_per_user}
                  onChange={(e) => setFormData({ ...formData, max_servers_per_user: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                />
              </div>
              <div className="space-y-2"
              >
                <label className="text-sm font-medium">Cost/hr</label>
                <input
                  type="number"
                  min={0}
                  value={formData.cost_per_hour}
                  onChange={(e) => setFormData({ ...formData, cost_per_hour: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4"
            >
              <div className="space-y-2"
              >
                <label className="text-sm font-medium">Category</label>
                <input
                  type="text"
                  list="plan-categories"
                  value={formData.category}
                  onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                  placeholder="cpu, gpu, memory..."
                />
                <datalist id="plan-categories">
                  {categories.map((cat) => (
                    <option key={cat.value} value={cat.value} />
                  ))}
                </datalist>
              </div>
              <div className="space-y-2"
              >
                <label className="text-sm font-medium">Priority</label>
                <input
                  type="number"
                  value={formData.priority}
                  onChange={(e) => setFormData({ ...formData, priority: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                />
              </div>
            </div>
            <div className="flex items-center gap-2"
            >
              <input
                type="checkbox"
                id="requires-approval"
                checked={formData.requires_approval}
                onChange={(e) => setFormData({ ...formData, requires_approval: e.target.checked })}
                className="rounded border-border"
              />
              <label htmlFor="requires-approval" className="text-sm">Requires admin approval</label>
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
                disabled={createPlan.isPending || updatePlan.isPending}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {editingPlan ? 'Update' : 'Create'}
              </button>
            </DialogFooter>
          </form>
          <DialogClose onClick={() => setDialogOpen(false)} />
        </DialogContent>
      </Dialog>
      )}
    </>
  );
}
