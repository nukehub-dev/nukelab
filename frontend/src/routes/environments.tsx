import { createFileRoute } from '@tanstack/react-router';
import { Boxes, Layers, GitBranch, CheckCircle2, XCircle, Copy, Pencil, Trash2 } from 'lucide-react';
import { useState, useMemo } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useEnvironments, useEnvironmentActions } from '../hooks/use-environments';
import { useDataTable } from '../hooks/use-data-table';
import { useAuthStore } from '../stores/auth-store';
import { formatDate } from '../lib/utils';
import type { Environment as EnvironmentType } from '../types/api';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { motion } from 'framer-motion';

export const Route = createFileRoute('/environments')({
  component: EnvironmentsPage,
});

function EnvironmentsPage() {
  const canManageEnvironments = useAuthStore((state) => state.canManageEnvironments());

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

  const { createEnvironment, updateEnvironment, deleteEnvironment, activateEnvironment, deactivateEnvironment, cloneEnvironment } = useEnvironmentActions();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEnv, setEditingEnv] = useState<EnvironmentType | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    slug: '',
    image: '',
    description: '',
    category: 'simulation',
    icon: '',
    color: '',
    is_public: true,
  });

  const environments = data?.data || [];
  const pagination = data?.pagination;

  const openCreateDialog = () => {
    setEditingEnv(null);
    setFormData({
      name: '',
      slug: '',
      image: '',
      description: '',
      category: 'simulation',
      icon: '',
      color: '',
      is_public: true,
    });
    setDialogOpen(true);
  };

  const openEditDialog = (env: EnvironmentType) => {
    setEditingEnv(env);
    setFormData({
      name: env.name,
      slug: env.slug,
      image: env.image,
      description: env.description || '',
      category: env.category || 'simulation',
      icon: env.icon || '',
      color: env.color || '',
      is_public: env.is_public,
    });
    setDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
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
      });
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
      });
    }
    setDialogOpen(false);
  };

  const columns: ColumnDef<EnvironmentType>[] = [
    ...(canManageEnvironments ? [{
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
      accessorKey: 'image',
      header: 'Image',
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground font-mono"
        >{row.getValue('image')}</span>
      ),
    },
    {
      accessorKey: 'category',
      header: 'Category',
      cell: ({ row }) => {
        const category = row.getValue('category') as string;
        return category ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-secondary text-secondary-foreground"
          >
            {category}
          </span>
        ) : (
          <span className="text-muted-foreground text-sm"
          >—</span>
        );
      },
    },
    ...(canManageEnvironments ? [{
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
    ...(canManageEnvironments ? [{
      id: 'actions' as const,
      header: 'Actions',
      cell: ({ row }: { row: { original: EnvironmentType } }) => {
        const env = row.original;
        return (
          <div className="flex items-center gap-1"
          >
            <motion.button
              onClick={() => openEditDialog(env)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              title="Edit"
            >
              <Pencil className="w-4 h-4" />
            </motion.button>
            {env.is_active ? (
              <motion.button
                onClick={() => deactivateEnvironment.mutate(env.id)}
                disabled={deactivateEnvironment.isPending}
                className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors"
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                title="Deactivate"
              >
                <XCircle className="w-4 h-4" />
              </motion.button>
            ) : (
              <motion.button
                onClick={() => activateEnvironment.mutate(env.id)}
                disabled={activateEnvironment.isPending}
                className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors"
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                title="Activate"
              >
                <CheckCircle2 className="w-4 h-4" />
              </motion.button>
            )}
            <motion.button
              onClick={() => {
                const name = prompt('New name:', env.name + ' Copy');
                const slug = prompt('New slug:', env.slug + '-copy');
                if (name && slug) {
                  cloneEnvironment.mutate({ envId: env.id, name, slug });
                }
              }}
              disabled={cloneEnvironment.isPending}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
              whileHover={{ scale: 1.1 }}
              whileTap={{ scale: 0.9 }}
              title="Clone"
            >
              <Copy className="w-4 h-4" />
            </motion.button>
            <motion.button
              onClick={() => {
                if (confirm(`Are you sure you want to delete ${env.name}?`)) {
                  deleteEnvironment.mutate(env.id);
                }
              }}
              disabled={deleteEnvironment.isPending}
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
    }] : []),
  ];

  const activeEnvs = environments.filter((e) => e.is_active).length;
  const publicEnvs = environments.filter((e) => e.is_public).length;

  const stats = [
    { title: 'Environments', value: pagination?.total || environments.length, icon: Boxes, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: activeEnvs, icon: CheckCircle2, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Public', value: publicEnvs, icon: GitBranch, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Categories', value: new Set(environments.map((e) => e.category).filter(Boolean)).size, icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
  ];

  const bulkActions = canManageEnvironments ? [
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
  ] : [];

  // Derive categories dynamically from actual data
  const categories = useMemo(() => {
    const cats = [...new Set(environments.map((e) => e.category).filter(Boolean))];
    return cats.map((cat) => ({ label: cat as string, value: cat as string }));
  }, [environments]);

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

  const mobileCardRenderer = (env: EnvironmentType) => (
    <div className="p-4 space-y-3"
    >
      <div className="flex items-center justify-between"
      >
        <div className="font-medium"
        >{env.name}</div>
        <StatusBadge status={env.is_active ? 'running' : 'stopped'} label={env.is_active ? 'Active' : 'Inactive'} pulse={env.is_active} />
      </div>
      <div className="text-xs text-muted-foreground"
      >{env.description || 'No description'}</div>
      <div className="flex items-center gap-2"
      >
        <code className="text-xs bg-muted px-1.5 py-0.5 rounded"
        >{env.slug}</code>
        {env.category && (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-secondary"
          >
            {env.category}
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground"
      >
        Created: {formatDate(env.created_at)}
      </div>
    </div>
  );

  return (
    <>
      <ResourcePageLayout
        title="Environments"
        subtitle="Manage deployment environments"
        icon={Boxes}
        stats={stats}
        actions={canManageEnvironments ? [
          { 
            action: 'create',
            onClick: openCreateDialog 
          },
        ] : []}
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
          enableRowSelection={canManageEnvironments}
        />
      </ResourcePageLayout>

      {canManageEnvironments && (
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}
      >
        <DialogContent className="max-w-md"
        >
          <DialogHeader>
            <DialogTitle>{editingEnv ? 'Edit Environment' : 'Create Environment'}</DialogTitle>
            <DialogDescription>
              {editingEnv ? 'Update environment details.' : 'Create a new environment template.'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4 mt-4"
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
                placeholder="Ubuntu 22.04"
              />
            </div>
            {!editingEnv && (
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
                  placeholder="ubuntu-2204"
                />
              </div>
            )}
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Docker Image *</label>
              <input
                type="text"
                required
                value={formData.image}
                onChange={(e) => setFormData({ ...formData, image: e.target.value })}
                className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                placeholder="ubuntu:22.04"
              />
            </div>
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Description</label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none resize-none"
                rows={3}
                placeholder="Optional description..."
              />
            </div>
            <div className="grid grid-cols-2 gap-4"
            >
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >Category</label>
                <input
                  type="text"
                  list="env-categories"
                  value={formData.category}
                  onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                  placeholder="e.g. simulation, development"
                />
                <datalist id="env-categories">
                  {categories.map((cat) => (
                    <option key={cat.value} value={cat.value} />
                  ))}
                </datalist>
              </div>
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >Visibility</label>
                <select
                  value={String(formData.is_public)}
                  onChange={(e) => setFormData({ ...formData, is_public: e.target.value === 'true' })}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-input/80 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                >
                  <option value="true">Public</option>
                  <option value="false">Private</option>
                </select>
              </div>
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
                disabled={createEnvironment.isPending || updateEnvironment.isPending}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {editingEnv ? 'Update' : 'Create'}
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
