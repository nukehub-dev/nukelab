import { createFileRoute } from '@tanstack/react-router';
import { Users, Shield, UserCheck, UserX, Mail, Calendar } from 'lucide-react';
import { useState } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { StatusBadge } from '../components/data/status-badge';
import { useUsers, useUserActions } from '../hooks/use-users';
import { useDataTable } from '../hooks/use-data-table';
import { formatDate } from '../lib/utils';
import type { User as UserType } from '../types/api';
import type { ColumnDef, ColumnFiltersState, VisibilityState, SortingState } from '@tanstack/react-table';

export const Route = createFileRoute('/users')({
  component: UsersPage,
});

function UsersPage() {
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

  const { data, isLoading, isError, error } = useUsers({
    role: tableState.filters.role as string,
    status: tableState.filters.status as string,
    search: tableState.search,
    sort_by: sorting[0]?.id || 'created_at',
    sort_order: sorting[0]?.desc ? 'desc' : 'asc',
    page: tableState.page,
    limit: tableState.limit,
  });

  const { disableUser } = useUserActions();

  const users = data?.data || [];
  const pagination = data?.pagination;

  const columns: ColumnDef<UserType>[] = [
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
      accessorKey: 'username',
      header: 'Username',
      cell: ({ row }) => (
        <div className="flex items-center gap-3">
          {row.original.avatar_url ? (
            <img
              src={row.original.avatar_url}
              alt={row.original.username}
              className="w-8 h-8 rounded-full"
            />
          ) : (
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
              <span className="text-xs font-medium text-primary">
                {row.original.username.slice(0, 2).toUpperCase()}
              </span>
            </div>
          )}
          <div>
            <div className="font-medium">{row.getValue('username')}</div>
            <div className="text-xs text-muted-foreground">{row.original.display_name}</div>
          </div>
        </div>
      ),
    },
    {
      accessorKey: 'email',
      header: 'Email',
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Mail className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm">{row.getValue('email')}</span>
        </div>
      ),
    },
    {
      accessorKey: 'role',
      header: 'Role',
      cell: ({ row }) => (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">
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
      accessorKey: 'nuke_balance',
      header: 'Credits',
      cell: ({ row }) => (
        <span className="font-mono text-sm">
          {(row.getValue('nuke_balance') as number).toLocaleString()}
        </span>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Joined',
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {formatDate(row.getValue('created_at') as string)}
          </span>
        </div>
      ),
    },
  ];

  const activeUsers = users.filter((u) => u.is_active).length;
  const adminUsers = users.filter((u) => u.role === 'admin').length;

  const stats = [
    { title: 'Total Users', value: pagination?.total || users.length, icon: Users, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: activeUsers, icon: UserCheck, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Admins', value: adminUsers, icon: Shield, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Inactive', value: users.length - activeUsers, icon: UserX, iconColor: 'text-gray-400', bgColor: 'bg-gray-500/10' },
  ];

  const bulkActions = [
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
  ];

  const filters = [
    {
      key: 'role',
      label: 'Role',
      options: [
        { label: 'Admin', value: 'admin' },
        { label: 'Moderator', value: 'moderator' },
        { label: 'User', value: 'user' },
      ],
    },
    {
      key: 'status',
      label: 'Status',
      options: [
        { label: 'Active', value: 'active' },
        { label: 'Inactive', value: 'disabled' },
      ],
    },
  ];

  const mobileCardRenderer = (user: UserType) => (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-3">
        {user.avatar_url ? (
          <img src={user.avatar_url} alt={user.username} className="w-10 h-10 rounded-full" />
        ) : (
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
            <span className="text-sm font-medium text-primary">{user.username.slice(0, 2).toUpperCase()}</span>
          </div>
        )}
        <div className="flex-1">
          <div className="font-medium">{user.username}</div>
          <div className="text-sm text-muted-foreground">{user.email}</div>
        </div>
        <StatusBadge status={user.is_active ? 'running' : 'stopped'} />
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">
          {user.role}
        </span>
        <span className="text-muted-foreground">
          Credits: {user.nuke_balance.toLocaleString()}
        </span>
      </div>
    </div>
  );

  return (
    <ResourcePageLayout
      title="Users"
      subtitle="Manage platform users"
      icon={Users}
      stats={stats}
      actions={[
        { action: 'deploy', onClick: () => console.log('Create user') },
      ]}
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
      />
    </ResourcePageLayout>
  );
}
