import { createFileRoute, useSearch } from '@tanstack/react-router';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  CreditCard,
  AlertTriangle,
  UserCheck,
  History,
  Zap,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from 'lucide-react';
import { useUsers } from '../hooks/use-users';
import { useLowBalanceUsers } from '../hooks/use-credits';
import { useDataTable } from '../hooks/use-data-table';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { cn } from '../lib/utils';
import { CreditAdjustDialog } from '../components/admin/credit-adjust-dialog';
import { CreditHistoryDialog } from '../components/admin/credit-history-dialog';
import { DataTable } from '../components/data/data-table';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { StatCard } from '../components/data/stat-card';
import { Tooltip } from '../components/ui/tooltip';
import { Button } from '../components/ui/button';
import type { User } from '../types/api';
import type { ColumnDef, SortingState, ColumnFiltersState, VisibilityState } from '@tanstack/react-table';

export const Route = createFileRoute('/admin/credits')({
  component: CreditsAdminPage,
});

function CreditsAdminPage() {
  const hasPermission = useAuthStore((state) => state.hasPermission);
  const canGrant = hasPermission(PERMISSIONS.CREDITS_GRANT);
  const canDeduct = hasPermission(PERMISSIONS.CREDITS_DEDUCT);
  const canManageCredits = canGrant || canDeduct;

  const searchParams = useSearch({ from: '/admin/credits' }) as { user?: string };

  const {
    state: tableState,
    setPage,
    setLimit,
    setSort,
    setSearch,
  } = useDataTable({ defaultLimit: 20, defaultSortBy: 'nuke_balance', defaultSortOrder: 'asc' });

  const [sorting, setSorting] = useState<SortingState>([
    { id: tableState.sortBy, desc: tableState.sortOrder === 'desc' }
  ]);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [adjustDialogOpen, setAdjustDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);

  const { data: usersData, isLoading, isError, error } = useUsers({
    page: tableState.page,
    limit: tableState.limit,
    sort_by: sorting[0]?.id || 'nuke_balance',
    sort_order: sorting[0]?.desc ? 'desc' : 'asc',
    search: tableState.search,
  });

  const { data: lowBalanceData } = useLowBalanceUsers({ threshold: 100, page: 1, limit: 3 });

  useEffect(() => {
    if (searchParams.user && usersData?.data) {
      const user = usersData.data.find((u) => u.id === searchParams.user);
      if (user) setSelectedUser(user);
    }
  }, [searchParams.user, usersData]);

  const users = usersData?.data || [];
  const pagination = usersData?.pagination;
  const lowBalanceUsers = lowBalanceData?.users || [];

  const usersMap = useMemo(() => {
    const map: Record<string, string> = {};
    users.forEach((u) => { map[u.id] = u.username; });
    lowBalanceUsers.forEach((u) => { map[u.id] = u.username; });
    return map;
  }, [users, lowBalanceUsers]);

  const handleAdjust = useCallback((user: User) => {
    setSelectedUser(user);
    setAdjustDialogOpen(true);
  }, []);

  const handleViewHistory = useCallback((user: User) => {
    setSelectedUser(user);
    setHistoryDialogOpen(true);
  }, []);

  const SortIcon = ({ columnId }: { columnId: string }) => {
    const sort = sorting.find((s) => s.id === columnId);
    if (!sort) return <ArrowUpDown className="w-3 h-3 opacity-30" />;
    return sort.desc ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />;
  };

  const columns: ColumnDef<User>[] = [
    {
      accessorKey: 'username',
      header: () => (
        <button
          onClick={() => {
            const isAsc = sorting[0]?.id === 'username' && !sorting[0]?.desc;
            setSorting([{ id: 'username', desc: isAsc }]);
            setSort('username', isAsc ? 'desc' : 'asc');
          }}
          className="flex items-center gap-1 hover:text-primary transition-colors"
        >
          User
          <SortIcon columnId="username" />
        </button>
      ),
      cell: ({ row }) => {
        const user = row.original;
        const isLow = user.nuke_balance <= 100;
        return (
          <div className="flex items-center gap-3">
            <div className={cn(
              'w-9 h-9 rounded-full flex items-center justify-center shrink-0',
              isLow ? 'bg-amber-500/10' : 'bg-primary/10'
            )}>
              <span className={cn('text-xs font-medium', isLow ? 'text-amber-400' : 'text-primary')}>
                {user.username.slice(0, 2).toUpperCase()}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm">{user.username}</span>
              {isLow && (
                <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
                  <AlertTriangle className="w-2.5 h-2.5" />
                  Low
                </span>
              )}
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'email',
      header: () => (
        <button
          onClick={() => {
            const isAsc = sorting[0]?.id === 'email' && !sorting[0]?.desc;
            setSorting([{ id: 'email', desc: isAsc }]);
            setSort('email', isAsc ? 'desc' : 'asc');
          }}
          className="flex items-center gap-1 hover:text-primary transition-colors"
        >
          Email
          <SortIcon columnId="email" />
        </button>
      ),
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground">{row.getValue('email')}</span>
      ),
    },
    {
      accessorKey: 'nuke_balance',
      header: () => (
        <button
          onClick={() => {
            const isAsc = sorting[0]?.id === 'nuke_balance' && !sorting[0]?.desc;
            setSorting([{ id: 'nuke_balance', desc: isAsc }]);
            setSort('nuke_balance', isAsc ? 'desc' : 'asc');
          }}
          className="flex items-center gap-1 hover:text-primary transition-colors ml-auto"
        >
          Balance
          <SortIcon columnId="nuke_balance" />
        </button>
      ),
      cell: ({ row }) => {
        const balance = row.getValue('nuke_balance') as number;
        const isLow = balance <= 100;
        return (
          <div className="text-right">
            <div className={cn('font-mono font-semibold text-sm', isLow ? 'text-amber-400' : 'text-foreground')}>
              {balance.toLocaleString()}
            </div>
            <div className="text-[10px] text-muted-foreground">NUKE</div>
          </div>
        );
      },
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
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const user = row.original;
        return (
          <div className="flex items-center justify-end gap-1">
            <Tooltip content="View History">
              <Button
                variant="ghost"
                size="icon"
                className="w-8 h-8"
                onClick={() => handleViewHistory(user)}
              >
                <History className="w-4 h-4" />
              </Button>
            </Tooltip>
            {canManageCredits && (
              <Tooltip content="Adjust Credits">
                <Button
                  variant="ghost"
                  size="icon"
                  className="w-8 h-8 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10"
                  onClick={() => handleAdjust(user)}
                >
                  <CreditCard className="w-4 h-4" />
                </Button>
              </Tooltip>
            )}
          </div>
        );
      },
    },
  ];

  const stats = [
    {
      title: 'Low Balance',
      value: lowBalanceData?.pagination?.total || 0,
      icon: AlertTriangle,
      iconColor: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
    },
    {
      title: 'Total Users',
      value: pagination?.total || 0,
      icon: UserCheck,
      iconColor: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
    },
  ];

  const mobileCardRenderer = (user: User) => {
    const isLow = user.nuke_balance <= 100;
    return (
      <div className="p-4 space-y-3">
        <div className="flex items-center gap-3">
          <div className={cn('w-10 h-10 rounded-full flex items-center justify-center', isLow ? 'bg-amber-500/10' : 'bg-primary/10')}>
            <span className={cn('text-sm font-medium', isLow ? 'text-amber-400' : 'text-primary')}>
              {user.username.slice(0, 2).toUpperCase()}
            </span>
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium">{user.username}</span>
              {isLow && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400">Low</span>
              )}
            </div>
            <span className="text-xs text-muted-foreground">{user.email}</span>
          </div>
          <div className="text-right">
            <div className={cn('font-mono font-semibold', isLow ? 'text-amber-400' : '')}>
              {user.nuke_balance.toLocaleString()}
            </div>
            <div className="text-[10px] text-muted-foreground">NUKE</div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => handleViewHistory(user)}>
            <History className="w-3.5 h-3.5 mr-1" />
            History
          </Button>
          {canManageCredits && (
            <Button size="sm" variant="outline" onClick={() => handleAdjust(user)}>
              <CreditCard className="w-3.5 h-3.5 mr-1" />
              Adjust
            </Button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div>
          <h2 className="text-2xl font-bold">Credit Management</h2>
          <p className="text-muted-foreground mt-1">
            Manage user credits, view transaction history, and monitor low balances
          </p>
        </div>
      </motion.div>

      {/* Stats + Quick Actions */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-1 lg:grid-cols-3 gap-4"
      >
        {stats.map((stat) => (
          <StatCard
            key={stat.title}
            title={stat.title}
            value={stat.value}
            icon={stat.icon}
            iconColor={stat.iconColor}
            bgColor={stat.bgColor}
            variant="compact"
          />
        ))}

        <Card className="lg:col-span-1">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Zap className="w-4 h-4 text-amber-400" />
              Quick Actions
              {lowBalanceData && lowBalanceData.pagination.total > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
                  {lowBalanceData.pagination.total}
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {lowBalanceUsers.length === 0 ? (
              <p className="text-sm text-muted-foreground">No low balance users right now.</p>
            ) : (
              <div className="space-y-2">
                {lowBalanceUsers.map((lbUser) => (
                  <div
                    key={lbUser.id}
                    className="flex items-center justify-between p-2 rounded-lg bg-amber-500/5 border border-amber-500/10"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-7 h-7 rounded-full bg-amber-500/10 flex items-center justify-center shrink-0">
                        <span className="text-[10px] font-medium text-amber-400">
                          {lbUser.username.slice(0, 2).toUpperCase()}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{lbUser.username}</p>
                        <p className="text-xs text-amber-400">{lbUser.nuke_balance.toLocaleString()} NUKE</p>
                      </div>
                    </div>
                    {canGrant && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 shrink-0"
                        onClick={() => {
                          // Construct minimal User from LowBalanceUser data
                          handleAdjust({
                            id: lbUser.id,
                            username: lbUser.username,
                            email: lbUser.email,
                            nuke_balance: lbUser.nuke_balance,
                            role: 'user',
                            is_active: true,
                            is_verified: true,
                            display_name: lbUser.username,
                            avatar_url: '',
                          } as User);
                        }}
                      >
                        Grant
                      </Button>
                    )}
                  </div>
                ))}
                {lowBalanceData && lowBalanceData.pagination.total > 3 && (
                  <button
                    onClick={() => {
                      setPage(1);
                      setSorting([{ id: 'nuke_balance', desc: false }]);
                      setSort('nuke_balance', 'asc');
                    }}
                    className="w-full text-xs text-muted-foreground hover:text-primary transition-colors py-1"
                  >
                    View all {lowBalanceData.pagination.total} low balance users →
                  </button>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* DataTable */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
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
          searchable
          searchPlaceholder="Search users..."
          mobileCardRenderer={mobileCardRenderer}
        />
      </motion.div>

      {/* Dialogs */}
      <CreditAdjustDialog
        user={selectedUser}
        open={adjustDialogOpen}
        onOpenChange={setAdjustDialogOpen}
      />
      <CreditHistoryDialog
        user={selectedUser}
        open={historyDialogOpen}
        onClose={() => setHistoryDialogOpen(false)}
        usersMap={usersMap}
      />
    </div>
  );
}
