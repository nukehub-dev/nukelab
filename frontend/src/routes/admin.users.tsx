import { createFileRoute } from '@tanstack/react-router';
import { Users, Shield, UserCheck, UserX, Mail, Calendar, Pencil, Trash2, CreditCard, BadgeCheck, LogIn } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useUsers, useUserActions } from '../hooks/use-users';
import { useDataTable } from '../hooks/use-data-table';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { usePageGuard } from '../hooks/use-page-guard';
import { formatDate, cn } from '../lib/utils';
import type { User as UserType } from '../types/api';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { Select, SelectItem } from '../components/ui/select';
import { motion } from 'framer-motion';
import { Tooltip } from '../components/ui/tooltip';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { CreditAdjustDialog } from '../components/admin/credit-adjust-dialog';

export const Route = createFileRoute('/admin/users')({
  component: UsersPage,
});

function UsersPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.USERS_READ });
  if (!allowed) return null;

  const hasPermission = useAuthStore((state) => state.hasPermission);
  const canCreateUsers = hasPermission(PERMISSIONS.USERS_CREATE);
  const canUpdateUsers = hasPermission(PERMISSIONS.USERS_UPDATE);
  const canDeleteUsers = hasPermission(PERMISSIONS.USERS_DELETE);
  const canManageCredits = hasPermission(PERMISSIONS.CREDITS_GRANT) || hasPermission(PERMISSIONS.CREDITS_DEDUCT);
  const canManageUsers = canCreateUsers || canUpdateUsers || canDeleteUsers;

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

  const { data, isLoading, isError, error } = useUsers({
    role: tableState.filters.role as string,
    status: tableState.filters.status as string,
    search: tableState.search,
    sort_by: sorting[0]?.id || 'created_at',
    sort_order: sorting[0]?.desc ? 'desc' : 'asc',
    page: tableState.page,
    limit: tableState.limit,
  });

  const { createUser, updateUser, disableUser, deleteUser } = useUserActions();
  const { confirm, dialog } = useConfirmDialog();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserType | null>(null);
  const [adjustUser, setAdjustUser] = useState<UserType | null>(null);
  const [adjustDialogOpen, setAdjustDialogOpen] = useState(false);
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    role: 'user',
    first_name: '',
    last_name: '',
  });

  const users = data?.data || [];
  const pagination = data?.pagination;

  const openCreateDialog = () => {
    setEditingUser(null);
    setFormData({
      username: '',
      email: '',
      password: '',
      role: 'user',
      first_name: '',
      last_name: '',
    });
    setDialogOpen(true);
  };

  const openEditDialog = (user: UserType) => {
    setEditingUser(user);
    setFormData({
      username: user.username,
      email: user.email,
      password: '',
      role: user.role,
      first_name: user.first_name || '',
      last_name: user.last_name || '',
    });
    setDialogOpen(true);
  };

  const openAdjustDialog = (user: UserType) => {
    setAdjustUser(user);
    setAdjustDialogOpen(true);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingUser) {
      const updateData: Record<string, unknown> = {
        first_name: formData.first_name || undefined,
        last_name: formData.last_name || undefined,
        email: formData.email,
        role: formData.role,
      };
      // Only send credits if user has permission to manage them
      // Credit management is now handled via dedicated credit API, not user update
      updateUser.mutate(
        {
          userId: editingUser.id,
          data: updateData,
        },
        {
          onSuccess: () => setDialogOpen(false),
        }
      );
    } else {
      createUser.mutate(
        {
          username: formData.username,
          email: formData.email,
          password: formData.password,
          role: formData.role,
          first_name: formData.first_name || undefined,
          last_name: formData.last_name || undefined,
          credits: 500,
        },
        {
          onSuccess: () => setDialogOpen(false),
        }
      );
    }
  };

  const columns: ColumnDef<UserType>[] = [
    ...(canManageUsers ? [{
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
      accessorKey: 'username',
      header: 'Username',
      cell: ({ row }) => (
        <div className="flex items-center gap-3"
        >
          {row.original.avatar_url ? (
            <img
              src={row.original.avatar_url}
              alt={row.original.username}
              className="w-8 h-8 rounded-full"
            />
          ) : (
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center"
            >
              <span className="text-xs font-medium text-primary"
              >
                {row.original.username.slice(0, 2).toUpperCase()}
              </span>
            </div>
          )}
          <div>
            <div className="font-medium"
            >{row.getValue('username')}</div>
            <div className="text-xs text-muted-foreground"
            >{row.original.display_name}</div>
          </div>
        </div>
      ),
    },
    {
      accessorKey: 'email',
      header: 'Email',
      cell: ({ row }) => (
        <div className="flex items-center gap-2"
        >
          <Mail className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm"
            >{row.getValue('email')}</span>
        </div>
      ),
    },
    {
      accessorKey: 'role',
      header: 'Role',
      cell: ({ row }) => (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary"
        >
          {row.getValue('role')}
        </span>
      ),
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
          />
        );
      },
    },
    {
      accessorKey: 'is_verified',
      header: 'Verified',
      cell: ({ row }) => {
        const verified = row.getValue('is_verified') as boolean;
        return verified ? (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
            <BadgeCheck className="w-3.5 h-3.5" />
            Yes
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">No</span>
        );
      },
    },
    {
      accessorKey: 'nuke_balance',
      header: 'Credits',
      cell: ({ row }) => {
        const balance = row.getValue('nuke_balance') as number;
        const isLow = balance <= 100;
        return (
          <span className={cn('font-mono text-sm', isLow && 'text-amber-400')}>
            {balance.toLocaleString()}
          </span>
        );
      },
    },
    {
      accessorKey: 'daily_allowance',
      header: 'Daily',
      cell: ({ row }) => (
        <span className="font-mono text-sm text-muted-foreground">
          {(row.getValue('daily_allowance') as number).toLocaleString()}
        </span>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Joined',
      cell: ({ row }) => (
        <div className="flex items-center gap-2"
        >
          <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground"
          >
            {formatDate(row.getValue('created_at') as string)}
          </span>
        </div>
      ),
    },
    {
      accessorKey: 'login_count',
      header: 'Logins',
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <LogIn className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="font-mono text-sm text-muted-foreground">
            {(row.getValue('login_count') as number).toLocaleString()}
          </span>
        </div>
      ),
    },
    ...(canManageUsers ? [{
      id: 'actions' as const,
      header: 'Actions',
      cell: ({ row }: { row: { original: UserType } }) => {
        const user = row.original;
        return (
          <div className="flex items-center gap-1"
          >
            <Tooltip content="Edit">
              <motion.button
                onClick={() => openEditDialog(user)}
                className="inline-flex p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors"
                
                
              >
                <Pencil className="w-4 h-4" />
              </motion.button>
            </Tooltip>
            {canManageCredits && (
              <Tooltip content="Adjust Credits">
                <motion.button
                  onClick={() => openAdjustDialog(user)}
                  className="inline-flex p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors"
                >
                  <CreditCard className="w-4 h-4" />
                </motion.button>
              </Tooltip>
            )}
            {canDeleteUsers && (
              <Tooltip content="Delete">
                <motion.button
                  onClick={async () => {
                    const confirmed = await confirm({
                      title: 'Delete User',
                      description: `Are you sure you want to delete ${user.username}?`,
                      confirmLabel: 'Delete',
                      cancelLabel: 'Cancel',
                      variant: 'danger',
                    });
                    if (confirmed) deleteUser.mutate(user.id);
                  }}
                  disabled={deleteUser.isPending}
                  className="inline-flex p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </motion.button>
              </Tooltip>
            )}
          </div>
        );
      },
      enableSorting: false,
    }] : []),
  ];

  const activeUsers = users.filter((u) => u.is_active).length;
  const adminUsers = users.filter((u) => u.role === 'admin').length;

  const stats = [
    { title: 'Total Users', value: pagination?.total || users.length, icon: Users, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: activeUsers, icon: UserCheck, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Admins', value: adminUsers, icon: Shield, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Inactive', value: users.length - activeUsers, icon: UserX, iconColor: 'text-gray-400', bgColor: 'bg-gray-500/10' },
  ];

  const bulkActions = canManageUsers ? [
    {
      label: 'Deactivate',
      icon: <UserX className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => disableUser.mutate({ userId: id, disabled: true }));
      },
    },
    {
      label: 'Activate',
      icon: <UserCheck className="w-4 h-4" />,
      onClick: (ids: string[]) => {
        ids.forEach((id) => disableUser.mutate({ userId: id, disabled: false }));
      },
    },
  ] : [];

  const filters = [
    ...(canManageUsers ? [{
      key: 'role' as const,
      label: 'Role',
      options: [
        { label: 'Admin', value: 'admin' },
        { label: 'Moderator', value: 'moderator' },
        { label: 'User', value: 'user' },
      ],
    }] : []),
    {
      key: 'status' as const,
      label: 'Status',
      options: [
        { label: 'Active', value: 'active' },
        { label: 'Inactive', value: 'disabled' },
      ],
    },
  ];

  const mobileCardRenderer = (user: UserType) => (
    <div className="p-4 space-y-3"
    >
      <div className="flex items-center gap-3"
      >
        {user.avatar_url ? (
          <img src={user.avatar_url} alt={user.username} className="w-10 h-10 rounded-full" />
        ) : (
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center"
          >
            <span className="text-sm font-medium text-primary"
            >{user.username.slice(0, 2).toUpperCase()}</span>
          </div>
        )}
        <div className="flex-1"
        >
          <div className="font-medium"
          >{user.username}</div>
          <div className="text-sm text-muted-foreground"
          >{user.email}</div>
        </div>
        <StatusBadge status={user.is_active ? 'running' : 'stopped'} label={user.is_active ? 'Active' : 'Disabled'} />
      </div>
      <div className="flex items-center justify-between text-sm"
      >
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary"
        >
          {user.role}
        </span>
        <div className="flex items-center gap-3"
        >
          {user.is_verified && <BadgeCheck className="w-4 h-4 text-emerald-500" />}
          <span className={cn('text-muted-foreground', user.nuke_balance <= 100 && 'text-amber-400')}>
            Credits: {user.nuke_balance.toLocaleString()}
          </span>
          <span className="text-muted-foreground">
            Daily: {user.daily_allowance.toLocaleString()}
          </span>
          {canManageUsers && (
            <div className="flex items-center gap-1">
              <Tooltip content="Edit">
                <button
                  onClick={() => openEditDialog(user)}
                  className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
                >
                  <Pencil className="w-4 h-4" />
                </button>
              </Tooltip>
              {canDeleteUsers && (
                <Tooltip content="Delete">
                  <button
                    onClick={async () => {
                      const confirmed = await confirm({
                        title: 'Delete User',
                        description: `Are you sure you want to delete ${user.username}?`,
                        confirmLabel: 'Delete',
                        cancelLabel: 'Cancel',
                        variant: 'danger',
                      });
                      if (confirmed) deleteUser.mutate(user.id);
                    }}
                    disabled={deleteUser.isPending}
                    className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors inline-flex"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </Tooltip>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <>
      <ResourcePageLayout
        title="Users"
        subtitle="Manage platform users"
        icon={Users}
        backTo="/admin"
        stats={stats}
        actions={canManageUsers ? [
          { 
            action: 'create', 
            onClick: openCreateDialog 
          },
        ] : []}
      >
        <DataTable
          columns={columns}
          data={users}
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
          searchPlaceholder="Search users..."
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={canManageUsers}
        />
      </ResourcePageLayout>

      {/* Credit Adjust Dialog */}
      <CreditAdjustDialog
        user={adjustUser}
        open={adjustDialogOpen}
        onOpenChange={setAdjustDialogOpen}
      />

      {canManageUsers && (
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}
      >
        <DialogContent
        >
          <DialogHeader>
            <DialogTitle>{editingUser ? 'Edit User' : 'Create User'}</DialogTitle>
            <DialogDescription>
              {editingUser ? 'Update user details.' : 'Create a new user account.'}
            </DialogDescription>
          </DialogHeader>
          <form id="users-form" onSubmit={handleSubmit} className="space-y-4 mt-4" noValidate
          >
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Username</label>
              <Input
                type="text"
                disabled={!!editingUser}
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                placeholder="johndoe"
              />
            </div>
            <div className="space-y-2"
            >
              <label className="text-sm font-medium"
              >Email</label>
              <Input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                placeholder="john@example.com"
              />
            </div>
            {!editingUser && (
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >Password</label>
                <Input
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  placeholder="Min 6 characters"
                />
              </div>
            )}
            <div className="grid grid-cols-2 gap-4"
            >
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >First Name</label>
                <Input
                  type="text"
                  value={formData.first_name}
                  onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                />
              </div>
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >Last Name</label>
                <Input
                  type="text"
                  value={formData.last_name}
                  onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4"
            >
              <div className="space-y-2"
              >
                <label className="text-sm font-medium"
                >Role</label>
                <Select
                  value={formData.role}
                  onChange={(value) => setFormData({ ...formData, role: value })}
                >
                  <SelectItem value="user">User</SelectItem>
                  <SelectItem value="moderator">Moderator</SelectItem>
                  <SelectItem value="support">Support</SelectItem>
                  <SelectItem value="guest">Guest</SelectItem>
                  {canDeleteUsers && <SelectItem value="admin">Admin</SelectItem>}
                  {canDeleteUsers && <SelectItem value="super_admin">Super Admin</SelectItem>}
                </Select>
              </div>

            </div>
          </form>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" form="users-form" loading={createUser.isPending || updateUser.isPending}>
              {editingUser ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
          <DialogClose onClick={() => setDialogOpen(false)} />
        </DialogContent>
      </Dialog>
      )}
      {dialog}
    </>
  );
}
