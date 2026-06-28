import { createFileRoute } from '@tanstack/react-router'
import { Boxes, Layers, GitBranch, CheckCircle2, XCircle, Copy, Pencil, Trash2 } from 'lucide-react'
import { useState, useMemo, useEffect, useRef } from 'react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { DataTable } from '../components/data/data-table'
import { StatusBadge } from '../components/data/status-badge'
import { useEnvironments, useEnvironmentActions } from '../hooks/use-environments'
import { useDataTable } from '../hooks/use-data-table'
import { useThemeStore } from '../stores/theme-store'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { usePageGuard } from '../hooks/use-page-guard'
import { formatDate } from '../lib/utils'
import type { Environment as EnvironmentType } from '../types/api'
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
import { Label } from '../components/ui/label'
import { Button } from '../components/ui/button'
import { Select, SelectItem } from '../components/ui/select'
import { Textarea } from '../components/ui/textarea'
import { motion } from 'framer-motion'
import { Tooltip } from '../components/ui/tooltip'
import { useConfirmDialog } from '../components/ui/confirm-dialog'

export const Route = createFileRoute('/admin/environments')({
  component: EnvironmentsPage,
})

function EnvironmentsPage() {
  const allowed = usePageGuard({
    permissions: [
      PERMISSIONS.ENVIRONMENT_CREATE,
      PERMISSIONS.ENVIRONMENT_UPDATE,
      PERMISSIONS.ENVIRONMENT_DELETE,
    ],
  })
  const density = useThemeStore((state) => state.density)
  const { confirm, dialog } = useConfirmDialog()
  const canManageEnvironments = useAuthStore((state) => state.canManageEnvironments())

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

  const { data, isLoading, isError, error } = useEnvironments({
    category: tableState.filters.category as string,
    is_active:
      tableState.filters.is_active === 'true'
        ? true
        : tableState.filters.is_active === 'false'
          ? false
          : undefined,
    search: tableState.search,
    page: tableState.page,
    limit: tableState.limit,
  })

  const {
    createEnvironment,
    updateEnvironment,
    deleteEnvironment,
    activateEnvironment,
    deactivateEnvironment,
    cloneEnvironment,
  } = useEnvironmentActions()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingEnv, setEditingEnv] = useState<EnvironmentType | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    slug: '',
    image: '',
    description: '',
    category: 'simulation',
    icon: '',
    color: '',
    is_public: true,
  })

  const environments = useMemo(() => data?.data || [], [data?.data])
  const pagination = data?.pagination

  const openCreateDialog = () => {
    setEditingEnv(null)
    setFormData({
      name: '',
      slug: '',
      image: '',
      description: '',
      category: 'simulation',
      icon: '',
      color: '',
      is_public: true,
    })
    setDialogOpen(true)
  }

  const openEditDialog = (env: EnvironmentType) => {
    setEditingEnv(env)
    setFormData({
      name: env.name,
      slug: env.slug,
      image: env.image,
      description: env.description || '',
      category: env.category || 'simulation',
      icon: env.icon || '',
      color: env.color || '',
      is_public: env.is_public,
    })
    setDialogOpen(true)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingEnv) {
      updateEnvironment.mutate({
        envId: editingEnv.id,
        data: {
          name: formData.name,
          image: formData.image,
          description: formData.description || undefined,
          category: formData.category,
          icon: formData.icon || undefined,
          color: formData.color || undefined,
          is_public: formData.is_public,
        },
      })
    } else {
      createEnvironment.mutate({
        name: formData.name,
        slug: formData.slug,
        image: formData.image,
        description: formData.description || undefined,
        category: formData.category,
        icon: formData.icon || undefined,
        color: formData.color || undefined,
        is_public: formData.is_public,
      })
    }
    setDialogOpen(false)
  }

  const columns: ColumnDef<EnvironmentType>[] = [
    ...(canManageEnvironments
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
        const category = row.getValue('category') as string
        return category ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-secondary text-secondary-foreground">
            {category}
          </span>
        ) : (
          <span className="text-muted-foreground text-sm">—</span>
        )
      },
    },
    ...(canManageEnvironments
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
    ...(canManageEnvironments
      ? [
          {
            id: 'actions' as const,
            header: 'Actions',
            cell: ({ row }: { row: { original: EnvironmentType } }) => {
              const env = row.original
              return (
                <div className="flex items-center gap-1">
                  <Tooltip content="Edit">
                    <motion.button
                      onClick={() => openEditDialog(env)}
                      className="inline-flex p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
                    >
                      <Pencil className="w-4 h-4" />
                    </motion.button>
                  </Tooltip>
                  {env.is_active ? (
                    <Tooltip content="Deactivate">
                      <motion.button
                        onClick={() => deactivateEnvironment.mutate(env.id)}
                        disabled={deactivateEnvironment.isPending}
                        className="inline-flex p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors"
                      >
                        <XCircle className="w-4 h-4" />
                      </motion.button>
                    </Tooltip>
                  ) : (
                    <Tooltip content="Activate">
                      <motion.button
                        onClick={() => activateEnvironment.mutate(env.id)}
                        disabled={activateEnvironment.isPending}
                        className="inline-flex p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors"
                      >
                        <CheckCircle2 className="w-4 h-4" />
                      </motion.button>
                    </Tooltip>
                  )}
                  <Tooltip content="Clone">
                    <motion.button
                      onClick={() => {
                        const name = prompt('New name:', env.name + ' Copy')
                        const slug = prompt('New slug:', env.slug + '-copy')
                        if (name && slug) {
                          cloneEnvironment.mutate({ envId: env.id, name, slug })
                        }
                      }}
                      disabled={cloneEnvironment.isPending}
                      className="inline-flex p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
                    >
                      <Copy className="w-4 h-4" />
                    </motion.button>
                  </Tooltip>
                  <Tooltip content="Delete">
                    <motion.button
                      onClick={async () => {
                        const confirmed = await confirm({
                          title: 'Delete Environment',
                          description: `Are you sure you want to delete ${env.name}?`,
                          confirmLabel: 'Delete',
                          cancelLabel: 'Cancel',
                          variant: 'danger',
                        })
                        if (confirmed) deleteEnvironment.mutate(env.id)
                      }}
                      disabled={deleteEnvironment.isPending}
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

  const activeEnvs = environments.filter((e) => e.is_active).length
  const publicEnvs = environments.filter((e) => e.is_public).length

  const stats = [
    {
      title: 'Environments',
      value: pagination?.total || environments.length,
      icon: Boxes,
      iconColor: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
    },
    {
      title: 'Active',
      value: activeEnvs,
      icon: CheckCircle2,
      iconColor: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
    },
    {
      title: 'Public',
      value: publicEnvs,
      icon: GitBranch,
      iconColor: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
    },
    {
      title: 'Categories',
      value: new Set(environments.map((e) => e.category).filter(Boolean)).size,
      icon: Layers,
      iconColor: 'text-violet-400',
      bgColor: 'bg-violet-500/10',
    },
  ]

  const bulkActions = canManageEnvironments
    ? [
        {
          label: 'Activate',
          icon: <CheckCircle2 className="w-4 h-4" />,
          onClick: (ids: string[]) => {
            ids.forEach((id) => activateEnvironment.mutate(id))
          },
        },
        {
          label: 'Deactivate',
          icon: <XCircle className="w-4 h-4" />,
          onClick: (ids: string[]) => {
            ids.forEach((id) => deactivateEnvironment.mutate(id))
          },
        },
      ]
    : []

  // Derive categories dynamically from actual data
  const categories = useMemo(() => {
    const cats = [...new Set(environments.map((e) => e.category).filter(Boolean))]
    return cats.map((cat) => ({ label: cat as string, value: cat as string }))
  }, [environments])

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

  const mobileCardRenderer = (env: EnvironmentType) => (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">{env.name}</div>
        <StatusBadge
          status={env.is_active ? 'running' : 'stopped'}
          label={env.is_active ? 'Active' : 'Inactive'}
          pulse={env.is_active}
        />
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
      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-muted-foreground">Created: {formatDate(env.created_at)}</span>
        <div className="flex items-center gap-1">
          {canManageEnvironments && (
            <>
              <Tooltip content="Edit">
                <button
                  onClick={() => openEditDialog(env)}
                  className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
                >
                  <Pencil className="w-4 h-4" />
                </button>
              </Tooltip>
              {env.is_active ? (
                <Tooltip content="Deactivate">
                  <button
                    onClick={() => deactivateEnvironment.mutate(env.id)}
                    disabled={deactivateEnvironment.isPending}
                    className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors inline-flex"
                  >
                    <XCircle className="w-4 h-4" />
                  </button>
                </Tooltip>
              ) : (
                <Tooltip content="Activate">
                  <button
                    onClick={() => activateEnvironment.mutate(env.id)}
                    disabled={activateEnvironment.isPending}
                    className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors inline-flex"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                  </button>
                </Tooltip>
              )}
              <Tooltip content="Clone">
                <button
                  onClick={() => {
                    const name = prompt('New environment name:', `${env.name} (Copy)`)
                    const slug = prompt('New slug:', `${env.slug}-copy`)
                    if (name && slug) {
                      cloneEnvironment.mutate({ envId: env.id, name, slug })
                    }
                  }}
                  disabled={cloneEnvironment.isPending}
                  className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </Tooltip>
              <Tooltip content="Delete">
                <button
                  onClick={async () => {
                    const confirmed = await confirm({
                      title: 'Delete Environment',
                      description: `Are you sure you want to delete ${env.name}?`,
                      confirmLabel: 'Delete',
                      cancelLabel: 'Cancel',
                      variant: 'danger',
                    })
                    if (confirmed) deleteEnvironment.mutate(env.id)
                  }}
                  disabled={deleteEnvironment.isPending}
                  className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors inline-flex"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </Tooltip>
            </>
          )}
        </div>
      </div>
    </div>
  )

  if (!allowed) return null

  return (
    <>
      <ResourcePageLayout
        title="Environments"
        subtitle="Manage deployment environments"
        icon={Boxes}
        backTo="/admin"
        stats={stats}
        actions={
          canManageEnvironments
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
          searchPlaceholder="Search environments..."
          density={density}
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={canManageEnvironments}
        />
      </ResourcePageLayout>

      {canManageEnvironments && (
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{editingEnv ? 'Edit Environment' : 'Create Environment'}</DialogTitle>
              <DialogDescription>
                {editingEnv ? 'Update environment details.' : 'Create a new environment template.'}
              </DialogDescription>
            </DialogHeader>
            <form id="env-form" onSubmit={handleSubmit} className="space-y-4 mt-4" noValidate>
              <div className="space-y-2">
                <Label>Name *</Label>
                <Input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Ubuntu 22.04"
                />
              </div>
              {!editingEnv && (
                <div className="space-y-2">
                  <Label>Slug *</Label>
                  <Input
                    type="text"
                    value={formData.slug}
                    onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                    placeholder="ubuntu-2204"
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label>Docker Image *</Label>
                <Input
                  type="text"
                  value={formData.image}
                  onChange={(e) => setFormData({ ...formData, image: e.target.value })}
                  placeholder="ubuntu:22.04"
                />
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={3}
                  placeholder="Optional description..."
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Category</Label>
                  <Input
                    type="text"
                    list="env-categories"
                    value={formData.category}
                    onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                    placeholder="e.g. simulation, development"
                  />
                  <datalist id="env-categories">
                    {categories.map((cat) => (
                      <option key={cat.value} value={cat.value} />
                    ))}
                  </datalist>
                </div>
                <div className="space-y-2">
                  <Label>Visibility</Label>
                  <Select
                    value={String(formData.is_public)}
                    onChange={(value) => setFormData({ ...formData, is_public: value === 'true' })}
                  >
                    <SelectItem value="true">Public</SelectItem>
                    <SelectItem value="false">Private</SelectItem>
                  </Select>
                </div>
              </div>
            </form>
            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                form="env-form"
                loading={createEnvironment.isPending || updateEnvironment.isPending}
              >
                {editingEnv ? 'Update' : 'Create'}
              </Button>
            </DialogFooter>
            <DialogClose onClick={() => setDialogOpen(false)} />
          </DialogContent>
        </Dialog>
      )}
      {dialog}
    </>
  )
}
