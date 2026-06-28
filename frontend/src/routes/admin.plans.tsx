import { createFileRoute } from '@tanstack/react-router'
import {
  CreditCard,
  Cpu,
  MemoryStick,
  HardDrive,
  CheckCircle2,
  XCircle,
  Pencil,
  Trash2,
  Users,
  Building2,
  Shield,
  User,
  Headset,
  UserCircle,
} from 'lucide-react'
import { useState, useMemo, useEffect, useRef } from 'react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { DataTable } from '../components/data/data-table'
import { StatusBadge } from '../components/data/status-badge'
import {
  usePlans,
  usePlanActions,
  usePlanUsers,
  usePlanWorkspaces,
  usePlanAccessActions,
} from '../hooks/use-plans'
import { useQueryClient } from '@tanstack/react-query'
import { useDiscoverUsers } from '../hooks/use-users'
import { useWorkspaces } from '../hooks/use-workspaces'
import { useDataTable } from '../hooks/use-data-table'
import { useThemeStore } from '../stores/theme-store'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { usePageGuard } from '../hooks/use-page-guard'
import { formatDate, formatPlanResource } from '../lib/utils'
import type { Plan } from '../types/api'
import type {
  ColumnDef,
  ColumnFiltersState,
  VisibilityState,
  SortingState,
} from '@tanstack/react-table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../components/ui/dialog'
import { Input } from '../components/ui/input'
import { Button } from '../components/ui/button'
import { Textarea } from '../components/ui/textarea'
import { Label } from '../components/ui/label'
import { Checkbox } from '../components/ui/checkbox'
import { Combobox } from '../components/ui/combobox'
import { motion } from 'framer-motion'
import { Tooltip } from '../components/ui/tooltip'
import { useConfirmDialog } from '../components/ui/confirm-dialog'
import type { PlanUserAccess, PlanWorkspaceAccess } from '../hooks/use-plans'

export const Route = createFileRoute('/admin/plans')({
  component: PlansPage,
})

const ROLE_OPTIONS = [
  { value: 'guest', label: 'Guest', icon: UserCircle },
  { value: 'user', label: 'User', icon: User },
  { value: 'support', label: 'Support', icon: Headset },
  { value: 'moderator', label: 'Moderator', icon: Shield },
]

function PlansPage() {
  const allowed = usePageGuard({
    permissions: [PERMISSIONS.PLAN_CREATE, PERMISSIONS.PLAN_UPDATE, PERMISSIONS.PLAN_DELETE],
  })
  const density = useThemeStore((state) => state.density)
  const { confirm, dialog } = useConfirmDialog()
  const canManagePlans = useAuthStore((state) => state.canManagePlans())

  const {
    state: tableState,
    setPage,
    setLimit,
    setSort,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 20 })

  const [sorting, setSorting] = useState<SortingState>([
    { id: tableState.sortBy, desc: tableState.sortOrder === 'desc' },
  ])
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({})
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})

  // Sync React Table column filters with API filter state
  const prevColumnFiltersRef = useRef<ColumnFiltersState>([])
  useEffect(() => {
    const currentIds = new Set(columnFilters.map((f) => f.id))

    // Add/update filters
    columnFilters.forEach((filter) => {
      if (filter.value !== undefined && filter.value !== null) {
        setFilter(filter.id, String(filter.value))
      }
    })

    // Remove filters that no longer exist
    prevColumnFiltersRef.current.forEach((filter) => {
      if (!currentIds.has(filter.id)) {
        setFilter(filter.id, null)
      }
    })

    prevColumnFiltersRef.current = columnFilters
  }, [columnFilters, setFilter])

  const { data, isLoading, isError, error } = usePlans({
    category: tableState.filters.category as string,
    is_active:
      tableState.filters.is_active === 'true'
        ? true
        : tableState.filters.is_active === 'false'
          ? false
          : undefined,
    page: tableState.page,
    limit: tableState.limit,
  })

  const { createPlan, updatePlan, deletePlan, activatePlan, deactivatePlan } = usePlanActions()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingPlan, setEditingPlan] = useState<Plan | null>(null)
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
    is_public: false,
    visible_to_roles: ['user'] as string[],
    priority: 0,
  })

  // Access management dialog
  const [accessDialogOpen, setAccessDialogOpen] = useState(false)
  const [accessPlan, setAccessPlan] = useState<Plan | null>(null)

  const plans = useMemo(() => data?.data || [], [data?.data])
  const pagination = data?.pagination

  const openCreateDialog = () => {
    setEditingPlan(null)
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
      is_public: false,
      visible_to_roles: ['user'],
      priority: 0,
    })
    setDialogOpen(true)
  }

  const openEditDialog = (plan: Plan) => {
    setEditingPlan(plan)
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
      is_public: plan.is_public,
      visible_to_roles: plan.visible_to_roles || ['user'],
      priority: plan.priority,
    })
    setDialogOpen(true)
  }

  const openAccessDialog = (plan: Plan) => {
    setAccessPlan(plan)
    setAccessDialogOpen(true)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
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
          is_public: formData.is_public,
          visible_to_roles: formData.visible_to_roles,
          priority: formData.priority,
        },
      })
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
        is_public: formData.is_public,
        visible_to_roles: formData.visible_to_roles,
        priority: formData.priority,
      })
    }
    setDialogOpen(false)
  }

  const toggleRole = (role: string, checked: boolean) => {
    // Admin and super_admin always have access — cannot be toggled off
    if (role === 'admin' || role === 'super_admin') return
    setFormData((prev) => {
      const current = new Set(prev.visible_to_roles)
      if (checked) {
        current.add(role)
      } else {
        current.delete(role)
      }
      return { ...prev, visible_to_roles: Array.from(current) }
    })
  }

  const columns: ColumnDef<Plan>[] = [
    ...(canManagePlans
      ? [
          {
            id: 'select' as const,
            header: ({
              table,
            }: {
              table: {
                getIsAllPageRowsSelected: () => boolean
                getToggleAllPageRowsSelectedHandler: () => (
                  e: React.ChangeEvent<HTMLInputElement>
                ) => void
              }
            }) => (
              <input
                type="checkbox"
                checked={table.getIsAllPageRowsSelected()}
                onChange={table.getToggleAllPageRowsSelectedHandler()}
                className="rounded border-border"
              />
            ),
            cell: ({
              row,
            }: {
              row: {
                getIsSelected: () => boolean
                getToggleSelectedHandler: () => (e: React.ChangeEvent<HTMLInputElement>) => void
              }
            }) => (
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
        ]
      : []),
    {
      accessorKey: 'name',
      header: 'Name',
      cell: ({ row }) => (
        <div className="space-y-1">
          <div className="font-medium">{row.getValue('name')}</div>
          {row.original.description && (
            <div className="text-xs text-muted-foreground line-clamp-1">
              {row.original.description}
            </div>
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
      accessorKey: 'cpu_limit',
      header: 'CPU',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm">{row.getValue('cpu_limit')} cores</span>
        </div>
      ),
    },
    {
      accessorKey: 'memory_limit',
      header: 'Memory',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <MemoryStick className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm">
            {formatPlanResource(row.getValue('memory_limit') as string)}
          </span>
        </div>
      ),
    },
    {
      accessorKey: 'disk_limit',
      header: 'Disk',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <HardDrive className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm">
            {formatPlanResource(row.getValue('disk_limit') as string)}
          </span>
        </div>
      ),
    },
    {
      accessorKey: 'cost_per_hour',
      header: 'Cost/hr',
      cell: ({ row }) => (
        <span className="font-mono text-sm">{row.getValue('cost_per_hour')} nukes</span>
      ),
    },
    ...(canManagePlans
      ? [
          {
            accessorKey: 'is_active' as const,
            header: 'Status',
            cell: ({ row }: { row: { getValue: (key: string) => unknown } }) => {
              const isActive = row.getValue('is_active') as boolean
              return (
                <StatusBadge
                  status={isActive ? 'running' : 'stopped'}
                  label={isActive ? 'Active' : 'Inactive'}
                  pulse={isActive}
                />
              )
            },
          },
        ]
      : []),
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: ({ row }) => formatDate(row.getValue('created_at') as string),
    },
    ...(canManagePlans
      ? [
          {
            id: 'actions' as const,
            header: 'Actions',
            cell: ({ row }: { row: { original: Plan } }) => {
              const plan = row.original
              return (
                <div className="flex items-center gap-1">
                  <Tooltip content="Edit">
                    <motion.button
                      onClick={() => openEditDialog(plan)}
                      className="inline-flex p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
                    >
                      <Pencil className="w-4 h-4" />
                    </motion.button>
                  </Tooltip>
                  <Tooltip content="Manage Access">
                    <motion.button
                      onClick={() => openAccessDialog(plan)}
                      className="inline-flex p-1.5 rounded-lg hover:bg-violet-500/10 text-violet-400 transition-colors"
                    >
                      <Users className="w-4 h-4" />
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
                      onClick={async () => {
                        const confirmed = await confirm({
                          title: 'Delete Plan',
                          description: `Are you sure you want to delete ${plan.name}?`,
                          confirmLabel: 'Delete',
                          cancelLabel: 'Cancel',
                          variant: 'danger',
                        })
                        if (confirmed) deletePlan.mutate(plan.id)
                      }}
                      disabled={deletePlan.isPending}
                      className="inline-flex p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </motion.button>
                  </Tooltip>
                </div>
              )
            },
            enableSorting: false,
          },
        ]
      : []),
  ]

  const activePlans = plans.filter((p) => p.is_active).length
  const totalCpu = plans.reduce((acc, p) => acc + (p.cpu_limit || 0), 0)

  const stats = [
    {
      title: 'Plans',
      value: pagination?.total || plans.length,
      icon: CreditCard,
      iconColor: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
    },
    {
      title: 'Active',
      value: activePlans,
      icon: CheckCircle2,
      iconColor: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
    },
    {
      title: 'Total CPU',
      value: `${totalCpu} cores`,
      icon: Cpu,
      iconColor: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
    },
    {
      title: 'Avg Cost',
      value:
        plans.length > 0
          ? `${Math.round(plans.reduce((acc, p) => acc + p.cost_per_hour, 0) / plans.length)} nukes/hr`
          : '0',
      icon: CreditCard,
      iconColor: 'text-violet-400',
      bgColor: 'bg-violet-500/10',
    },
  ]

  const bulkActions = canManagePlans
    ? [
        {
          label: 'Activate',
          icon: <CheckCircle2 className="w-4 h-4" />,
          onClick: (ids: string[]) => {
            ids.forEach((id) => activatePlan.mutate(id))
          },
        },
        {
          label: 'Deactivate',
          icon: <XCircle className="w-4 h-4" />,
          onClick: (ids: string[]) => {
            ids.forEach((id) => deactivatePlan.mutate(id))
          },
        },
      ]
    : []

  // Derive categories dynamically from actual data
  const categories = useMemo(() => {
    const cats = [...new Set(plans.map((p) => p.category).filter(Boolean))]
    return cats.map((cat) => ({ label: cat as string, value: cat as string }))
  }, [plans])

  const filters = [
    ...(categories.length > 0
      ? [
          {
            key: 'category' as const,
            label: 'Category',
            options: categories,
          },
        ]
      : []),
    {
      key: 'is_active' as const,
      label: 'Status',
      options: [
        { label: 'Active', value: 'true' },
        { label: 'Inactive', value: 'false' },
      ],
    },
  ]

  const mobileCardRenderer = (plan: Plan) => (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{plan.name}</div>
        <StatusBadge
          status={plan.is_active ? 'running' : 'stopped'}
          label={plan.is_active ? 'Active' : 'Inactive'}
          pulse={plan.is_active}
        />
      </div>
      <div className="text-xs text-muted-foreground">{plan.description || 'No description'}</div>
      <div className="flex items-center gap-2 text-sm">
        <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{plan.slug}</code>
        <span className="text-muted-foreground">
          {plan.cpu_limit} CPU · {formatPlanResource(plan.memory_limit)} RAM
        </span>
      </div>
      {canManagePlans ? (
        <div className="flex items-center justify-between pt-1">
          <span className="text-sm text-muted-foreground">{plan.cost_per_hour} nukes/hr</span>
          <div className="flex items-center gap-1">
            <Tooltip content="Edit">
              <button
                onClick={() => openEditDialog(plan)}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
              >
                <Pencil className="w-4 h-4" />
              </button>
            </Tooltip>
            <Tooltip content="Manage Access">
              <button
                onClick={() => openAccessDialog(plan)}
                className="p-1.5 rounded-lg hover:bg-violet-500/10 text-violet-400 transition-colors inline-flex"
              >
                <Users className="w-4 h-4" />
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
                onClick={async () => {
                  const confirmed = await confirm({
                    title: 'Delete Plan',
                    description: `Are you sure you want to delete ${plan.name}?`,
                    confirmLabel: 'Delete',
                    cancelLabel: 'Cancel',
                    variant: 'danger',
                  })
                  if (confirmed) deletePlan.mutate(plan.id)
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
        <div className="text-sm text-muted-foreground pt-1">{plan.cost_per_hour} nukes/hr</div>
      )}
    </div>
  )

  if (!allowed) return null

  return (
    <>
      <ResourcePageLayout
        title="Plans"
        subtitle="Manage server plans"
        icon={CreditCard}
        backTo="/admin"
        stats={stats}
        actions={
          canManagePlans
            ? [
                {
                  action: 'create',
                  onClick: openCreateDialog,
                },
              ]
            : []
        }
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
            setSorting(newSorting)
            if (newSorting.length > 0) {
              setSort(newSorting[0].id, newSorting[0].desc ? 'desc' : 'asc')
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
          density={density}
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={canManagePlans}
        />
      </ResourcePageLayout>

      {/* Create/Edit Dialog */}
      {canManagePlans && (
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{editingPlan ? 'Edit Plan' : 'Create Plan'}</DialogTitle>
              <DialogDescription>
                {editingPlan ? 'Update plan details.' : 'Create a new server plan.'}
              </DialogDescription>
            </DialogHeader>
            <form id="plans-form" onSubmit={handleSubmit} className="space-y-4 mt-4" noValidate>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Name *</Label>
                  <Input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="Basic"
                  />
                </div>
                {!editingPlan && (
                  <div className="space-y-2">
                    <Label>Slug *</Label>
                    <Input
                      type="text"
                      value={formData.slug}
                      onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                      placeholder="basic"
                    />
                  </div>
                )}
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={2}
                  placeholder="Optional description..."
                />
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label>CPU Limit</Label>
                  <Input
                    type="number"
                    step="0.5"
                    min={0.5}
                    value={formData.cpu_limit}
                    onChange={(e) =>
                      setFormData({ ...formData, cpu_limit: parseFloat(e.target.value) || 1 })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label>Memory</Label>
                  <Input
                    type="text"
                    value={formData.memory_limit}
                    onChange={(e) => setFormData({ ...formData, memory_limit: e.target.value })}
                    placeholder="2g"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Disk</Label>
                  <Input
                    type="text"
                    value={formData.disk_limit}
                    onChange={(e) => setFormData({ ...formData, disk_limit: e.target.value })}
                    placeholder="10g"
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label>GPU</Label>
                  <Input
                    type="number"
                    min={0}
                    value={formData.gpu_limit}
                    onChange={(e) =>
                      setFormData({ ...formData, gpu_limit: parseInt(e.target.value) || 0 })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Servers</Label>
                  <Input
                    type="number"
                    min={1}
                    value={formData.max_servers_per_user}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        max_servers_per_user: parseInt(e.target.value) || 1,
                      })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label>Cost/hr</Label>
                  <Input
                    type="number"
                    min={0}
                    value={formData.cost_per_hour}
                    onChange={(e) =>
                      setFormData({ ...formData, cost_per_hour: parseInt(e.target.value) || 0 })
                    }
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Category</Label>
                  <Input
                    type="text"
                    list="plan-categories"
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    placeholder="cpu, gpu, memory..."
                  />
                  <datalist id="plan-categories">
                    {categories.map((cat) => (
                      <option key={cat.value} value={cat.value} />
                    ))}
                  </datalist>
                </div>
                <div className="space-y-2">
                  <Label>Priority</Label>
                  <Input
                    type="number"
                    value={formData.priority}
                    onChange={(e) =>
                      setFormData({ ...formData, priority: parseInt(e.target.value) || 0 })
                    }
                  />
                </div>
              </div>
              <label className="flex items-center gap-3 cursor-pointer group">
                <Checkbox
                  checked={formData.is_public}
                  onChange={(checked) => setFormData({ ...formData, is_public: checked })}
                />
                <span className="text-sm">Public — visible to all users</span>
              </label>
              {!formData.is_public && (
                <div className="space-y-2">
                  <Label>Visible to Roles</Label>
                  <div className="flex flex-wrap gap-4">
                    {/* Admin always has access */}
                    <label className="flex items-center gap-2 cursor-not-allowed opacity-60">
                      <Checkbox checked disabled onChange={() => {}} />
                      <span className="text-sm">Admin</span>
                    </label>
                    {ROLE_OPTIONS.filter((r) => r.value !== 'admin').map((role) => (
                      <label key={role.value} className="flex items-center gap-2 cursor-pointer">
                        <Checkbox
                          checked={formData.visible_to_roles.includes(role.value)}
                          onChange={(checked) => toggleRole(role.value, checked)}
                        />
                        <span className="text-sm">{role.label}</span>
                      </label>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Admin always has access. Only users with the selected roles (plus
                    direct/workspace access) can see this plan.
                  </p>
                </div>
              )}
            </form>
            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                form="plans-form"
                loading={createPlan.isPending || updatePlan.isPending}
              >
                {editingPlan ? 'Update' : 'Create'}
              </Button>
            </DialogFooter>
            <DialogClose onClick={() => setDialogOpen(false)} />
          </DialogContent>
        </Dialog>
      )}

      {/* Access Management Dialog */}
      {canManagePlans && accessPlan && (
        <AccessManagementDialog
          plan={accessPlan}
          open={accessDialogOpen}
          onOpenChange={setAccessDialogOpen}
        />
      )}
      {dialog}
    </>
  )
}

// ─── Access Management Dialog ───

function AccessManagementDialog({
  plan,
  open,
  onOpenChange,
}: {
  plan: Plan
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const density = useThemeStore((state) => state.density)
  const [tab, setTab] = useState<'users' | 'workspaces'>('users')

  // ─── Users Tab State ───
  const usersTable = useDataTable({ defaultLimit: 10, defaultSortBy: 'granted_at' })
  const [usersSorting, setUsersSorting] = useState<SortingState>([{ id: 'granted_at', desc: true }])
  const [usersRowSelection, setUsersRowSelection] = useState<Record<string, boolean>>({})
  const [usersColumnFilters, setUsersColumnFilters] = useState<ColumnFiltersState>([])
  const [usersColumnVisibility, setUsersColumnVisibility] = useState<VisibilityState>({})
  const [selectedUserId, setSelectedUserId] = useState('')

  // ─── Workspaces Tab State ───
  const workspacesTable = useDataTable({ defaultLimit: 10, defaultSortBy: 'granted_at' })
  const [workspacesSorting, setWorkspacesSorting] = useState<SortingState>([
    { id: 'granted_at', desc: true },
  ])
  const [workspacesRowSelection, setWorkspacesRowSelection] = useState<Record<string, boolean>>({})
  const [workspacesColumnFilters, setWorkspacesColumnFilters] = useState<ColumnFiltersState>([])
  const [workspacesColumnVisibility, setWorkspacesColumnVisibility] = useState<VisibilityState>({})
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState('')

  const queryClient = useQueryClient()

  // Invalidate queries when dialog opens
  useEffect(() => {
    if (open && plan) {
      queryClient.invalidateQueries({ queryKey: ['plans', plan.id, 'users'] })
      queryClient.invalidateQueries({ queryKey: ['plans', plan.id, 'workspaces'] })
    }
  }, [open, plan, plan.id, queryClient])

  // ─── Data ───
  const { data: planUsers, isLoading: usersLoading } = usePlanUsers(plan.id)
  const { data: planWorkspaces, isLoading: workspacesLoading } = usePlanWorkspaces(plan.id)
  const { grantUserAccess, revokeUserAccess, grantWorkspaceAccess, revokeWorkspaceAccess } =
    usePlanAccessActions()

  const { data: discoverableUsers } = useDiscoverUsers()
  const { data: allWorkspaces } = useWorkspaces()

  // ─── Computed: available options for combobox ───
  const assignedUserIds = useMemo(
    () => new Set(planUsers?.map((u) => u.user_id) || []),
    [planUsers]
  )
  const assignedWorkspaceIds = useMemo(
    () => new Set(planWorkspaces?.map((w) => w.workspace_id) || []),
    [planWorkspaces]
  )

  const availableUserOptions = useMemo(() => {
    return (discoverableUsers || [])
      .filter((u) => !assignedUserIds.has(u.id))
      .map((u) => ({
        value: u.id,
        label: `${u.display_name || u.username} (@${u.username})`,
        image: u.avatar_url,
      }))
  }, [discoverableUsers, assignedUserIds])

  const availableWorkspaceOptions = useMemo(() => {
    return (allWorkspaces || [])
      .filter((w) => !assignedWorkspaceIds.has(w.id))
      .map((w) => ({
        value: w.id,
        label: `${w.name} (${w.member_count} members)`,
        description: w.owner_name
          ? `Owner: ${w.owner_name}${w.owner_username ? ` (@${w.owner_username})` : ''}`
          : undefined,
      }))
  }, [allWorkspaces, assignedWorkspaceIds])

  // ─── Client-side filter + paginate for Users ───
  const filteredUsers = useMemo(() => {
    let data = planUsers || []
    if (usersTable.state.search) {
      const q = usersTable.state.search.toLowerCase()
      data = data.filter(
        (u) =>
          (u.username && u.username.toLowerCase().includes(q)) ||
          (u.display_name && u.display_name.toLowerCase().includes(q)) ||
          u.user_id.toLowerCase().includes(q)
      )
    }
    // Sort
    const sortKey = usersSorting[0]?.id as keyof PlanUserAccess
    const desc = usersSorting[0]?.desc
    if (sortKey) {
      data = [...data].sort((a, b) => {
        const av = (a[sortKey] ?? '') as string
        const bv = (b[sortKey] ?? '') as string
        const cmp = av.localeCompare(bv)
        return desc ? -cmp : cmp
      })
    }
    return data
  }, [planUsers, usersTable.state.search, usersSorting])

  const paginatedUsers = useMemo(() => {
    const start = (usersTable.state.page - 1) * usersTable.state.limit
    return filteredUsers.slice(start, start + usersTable.state.limit)
  }, [filteredUsers, usersTable.state.page, usersTable.state.limit])

  const usersTotalPages = Math.max(1, Math.ceil(filteredUsers.length / usersTable.state.limit))

  // ─── Client-side filter + paginate for Workspaces ───
  const filteredWorkspaces = useMemo(() => {
    let data = planWorkspaces || []
    if (workspacesTable.state.search) {
      const q = workspacesTable.state.search.toLowerCase()
      data = data.filter(
        (w) =>
          (w.workspace_name && w.workspace_name.toLowerCase().includes(q)) ||
          w.workspace_id.toLowerCase().includes(q)
      )
    }
    // Sort
    const sortKey = workspacesSorting[0]?.id as keyof PlanWorkspaceAccess
    const desc = workspacesSorting[0]?.desc
    if (sortKey) {
      data = [...data].sort((a, b) => {
        const av = (a[sortKey] ?? '') as string
        const bv = (b[sortKey] ?? '') as string
        const cmp = av.localeCompare(bv)
        return desc ? -cmp : cmp
      })
    }
    return data
  }, [planWorkspaces, workspacesTable.state.search, workspacesSorting])

  const paginatedWorkspaces = useMemo(() => {
    const start = (workspacesTable.state.page - 1) * workspacesTable.state.limit
    return filteredWorkspaces.slice(start, start + workspacesTable.state.limit)
  }, [filteredWorkspaces, workspacesTable.state.page, workspacesTable.state.limit])

  const workspacesTotalPages = Math.max(
    1,
    Math.ceil(filteredWorkspaces.length / workspacesTable.state.limit)
  )

  // ─── Columns ───
  const userColumns: ColumnDef<PlanUserAccess>[] = [
    {
      accessorKey: 'username',
      header: 'User',
      cell: ({ row }) => {
        const access = row.original
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded flex-shrink-0 bg-primary/10">
              <User className="w-3.5 h-3.5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium">
                {access.display_name || access.username || 'Unknown'}
              </p>
              {access.username && (
                <p className="text-xs text-muted-foreground">@{access.username}</p>
              )}
            </div>
          </div>
        )
      },
    },
    {
      accessorKey: 'granted_by_username',
      header: 'Granted By',
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {row.original.granted_by_username || 'System'}
        </span>
      ),
    },
    {
      accessorKey: 'granted_at',
      header: 'Granted',
      cell: ({ row }) => (row.original.granted_at ? formatDate(row.original.granted_at) : '-'),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <Tooltip content="Remove access">
          <button
            onClick={() =>
              revokeUserAccess.mutate({ planId: plan.id, userId: row.original.user_id })
            }
            disabled={revokeUserAccess.isPending}
            className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors inline-flex"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </Tooltip>
      ),
      enableSorting: false,
      size: 50,
    },
  ]

  const workspaceColumns: ColumnDef<PlanWorkspaceAccess>[] = [
    {
      accessorKey: 'workspace_name',
      header: 'Workspace',
      cell: ({ row }) => {
        const access = row.original
        return (
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded flex-shrink-0 bg-primary/10">
              <Building2 className="w-3.5 h-3.5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium">{access.workspace_name || 'Unknown'}</p>
              {access.owner_name && (
                <p className="text-xs text-muted-foreground">
                  Owner: {access.owner_name}
                  {access.owner_username && (
                    <span className="opacity-60"> (@{access.owner_username})</span>
                  )}
                </p>
              )}
            </div>
          </div>
        )
      },
    },
    {
      accessorKey: 'granted_by_username',
      header: 'Granted By',
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {row.original.granted_by_username || 'System'}
        </span>
      ),
    },
    {
      accessorKey: 'granted_at',
      header: 'Granted',
      cell: ({ row }) => (row.original.granted_at ? formatDate(row.original.granted_at) : '-'),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <Tooltip content="Remove access">
          <button
            onClick={() =>
              revokeWorkspaceAccess.mutate({
                planId: plan.id,
                workspaceId: row.original.workspace_id,
              })
            }
            disabled={revokeWorkspaceAccess.isPending}
            className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors inline-flex"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </Tooltip>
      ),
      enableSorting: false,
      size: 50,
    },
  ]

  // ─── Mobile card renderers ───
  const userMobileCard = (access: PlanUserAccess) => (
    <div className="p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1 rounded flex-shrink-0 bg-primary/10">
            <User className="w-3 h-3 text-primary" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">
              {access.display_name || access.username || 'Unknown'}
            </p>
            {access.username && (
              <p className="text-xs text-muted-foreground truncate">@{access.username}</p>
            )}
          </div>
        </div>
        <button
          onClick={() => revokeUserAccess.mutate({ planId: plan.id, userId: access.user_id })}
          disabled={revokeUserAccess.isPending}
          className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors inline-flex shrink-0"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )

  const workspaceMobileCard = (access: PlanWorkspaceAccess) => (
    <div className="p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1 rounded flex-shrink-0 bg-primary/10">
            <Building2 className="w-3 h-3 text-primary" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{access.workspace_name || 'Unknown'}</p>
            {access.owner_name && (
              <p className="text-xs text-muted-foreground truncate">
                Owner: {access.owner_name}
                {access.owner_username && (
                  <span className="opacity-60"> (@{access.owner_username})</span>
                )}
              </p>
            )}
          </div>
        </div>
        <button
          onClick={() =>
            revokeWorkspaceAccess.mutate({ planId: plan.id, workspaceId: access.workspace_id })
          }
          disabled={revokeWorkspaceAccess.isPending}
          className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors inline-flex shrink-0"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="xl">
      <DialogContent className="overflow-hidden flex flex-col">
        <DialogClose onClick={() => onOpenChange(false)} />
        <DialogHeader>
          <DialogTitle>Manage Access: {plan.name}</DialogTitle>
          <DialogDescription>
            Control which users and workspaces can access this plan.
          </DialogDescription>
        </DialogHeader>

        {/* Tabs */}
        <div className="flex gap-2 mt-2">
          <button
            type="button"
            onClick={() => setTab('users')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              tab === 'users'
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:bg-accent'
            }`}
          >
            <Users className="w-4 h-4" />
            Users ({planUsers?.length || 0})
          </button>
          <button
            type="button"
            onClick={() => setTab('workspaces')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              tab === 'workspaces'
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:bg-accent'
            }`}
          >
            <Building2 className="w-4 h-4" />
            Workspaces ({planWorkspaces?.length || 0})
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto min-h-0 mt-4 space-y-4">
          {tab === 'users' ? (
            <>
              {/* Add User */}
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <Label className="mb-1.5 block">Add User</Label>
                  <Combobox
                    value={selectedUserId}
                    onChange={setSelectedUserId}
                    options={availableUserOptions}
                    placeholder="Select a user..."
                    searchPlaceholder="Search users..."
                  />
                </div>
                <Button
                  onClick={() => {
                    if (!selectedUserId) return
                    grantUserAccess.mutate(
                      { planId: plan.id, userId: selectedUserId },
                      { onSuccess: () => setSelectedUserId('') }
                    )
                  }}
                  disabled={!selectedUserId || grantUserAccess.isPending}
                  loading={grantUserAccess.isPending}
                >
                  Add
                </Button>
              </div>

              {/* Users Table */}
              <DataTable
                columns={userColumns}
                data={paginatedUsers}
                totalCount={filteredUsers.length}
                pageCount={usersTotalPages}
                page={usersTable.state.page}
                limit={usersTable.state.limit}
                sorting={usersSorting}
                rowSelection={usersRowSelection}
                columnFilters={usersColumnFilters}
                columnVisibility={usersColumnVisibility}
                globalFilter={usersTable.state.search}
                isLoading={usersLoading}
                onPageChange={usersTable.setPage}
                onLimitChange={usersTable.setLimit}
                onSortingChange={setUsersSorting}
                onRowSelectionChange={setUsersRowSelection}
                onColumnFiltersChange={setUsersColumnFilters}
                onColumnVisibilityChange={setUsersColumnVisibility}
                onGlobalFilterChange={usersTable.setSearch}
                getRowId={(row) => row.user_id}
                searchable
                searchPlaceholder="Search assigned users..."
                density={density}
                mobileCardRenderer={userMobileCard}
                enableRowSelection={false}
                emptyState={
                  <div className="text-center py-8 text-muted-foreground">
                    <Users className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">No users have direct access</p>
                    <p className="text-xs mt-1">Use the dropdown above to grant access</p>
                  </div>
                }
              />
            </>
          ) : (
            <>
              {/* Add Workspace */}
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <Label className="mb-1.5 block">Add Workspace</Label>
                  <Combobox
                    value={selectedWorkspaceId}
                    onChange={setSelectedWorkspaceId}
                    options={availableWorkspaceOptions}
                    placeholder="Select a workspace..."
                    searchPlaceholder="Search workspaces..."
                  />
                </div>
                <Button
                  onClick={() => {
                    if (!selectedWorkspaceId) return
                    grantWorkspaceAccess.mutate(
                      { planId: plan.id, workspaceId: selectedWorkspaceId },
                      { onSuccess: () => setSelectedWorkspaceId('') }
                    )
                  }}
                  disabled={!selectedWorkspaceId || grantWorkspaceAccess.isPending}
                  loading={grantWorkspaceAccess.isPending}
                >
                  Add
                </Button>
              </div>

              {/* Workspaces Table */}
              <DataTable
                columns={workspaceColumns}
                data={paginatedWorkspaces}
                totalCount={filteredWorkspaces.length}
                pageCount={workspacesTotalPages}
                page={workspacesTable.state.page}
                limit={workspacesTable.state.limit}
                sorting={workspacesSorting}
                rowSelection={workspacesRowSelection}
                columnFilters={workspacesColumnFilters}
                columnVisibility={workspacesColumnVisibility}
                globalFilter={workspacesTable.state.search}
                isLoading={workspacesLoading}
                onPageChange={workspacesTable.setPage}
                onLimitChange={workspacesTable.setLimit}
                onSortingChange={setWorkspacesSorting}
                onRowSelectionChange={setWorkspacesRowSelection}
                onColumnFiltersChange={setWorkspacesColumnFilters}
                onColumnVisibilityChange={setWorkspacesColumnVisibility}
                onGlobalFilterChange={workspacesTable.setSearch}
                getRowId={(row) => row.workspace_id}
                searchable
                searchPlaceholder="Search assigned workspaces..."
                density={density}
                mobileCardRenderer={workspaceMobileCard}
                enableRowSelection={false}
                emptyState={
                  <div className="text-center py-8 text-muted-foreground">
                    <Building2 className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">No workspaces have access</p>
                    <p className="text-xs mt-1">Use the dropdown above to grant access</p>
                  </div>
                }
              />
            </>
          )}
        </div>

        <DialogFooter className="mt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
