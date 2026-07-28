// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, useSearch, Link } from '@tanstack/react-router'
import { useState, useEffect, useCallback, useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  CreditCard,
  AlertTriangle,
  UserCheck,
  History,
  Zap,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  Wallet,
  RefreshCw,
  Users,
  X,
  Clock,
  Gift,
  Scale,
  Check,
  Coins,
} from 'lucide-react'
import { useUsers } from '../hooks/use-users'
import { useLowBalanceUsers } from '../hooks/use-credits'
import {
  useSystemDailyAllowance,
  useUpdateSystemDailyAllowance,
  useSystemMaxBalance,
  useUpdateSystemMaxBalance,
  useSystemInitialBalance,
  useUpdateSystemInitialBalance,
  useSystemAllowanceLoginWindow,
  useUpdateSystemAllowanceLoginWindow,
} from '../hooks/use-system-config'
import { useDataTable } from '../hooks/use-data-table'
import { useThemeStore } from '../stores/theme-store'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { usePageGuard } from '../hooks/use-page-guard'
import { cn, parseUtcDate } from '../lib/utils'
import { CreditAdjustDialog } from '../components/admin/credit-adjust-dialog'
import { CreditHistoryDialog } from '../components/admin/credit-history-dialog'
import { DailyAllowanceDialog } from '../components/admin/daily-allowance-dialog'
import { BulkCreditDialog } from '../components/admin/bulk-credit-dialog'
import { AllowanceOverrideDialog } from '../components/admin/allowance-override-dialog'
import { DataTable } from '../components/data/data-table'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { StatCard } from '../components/data/stat-card'
import { Tooltip } from '../components/ui/tooltip'
import { Button } from '../components/ui/button'
import type { User } from '../types/api'
import type {
  ColumnDef,
  SortingState,
  ColumnFiltersState,
  VisibilityState,
} from '@tanstack/react-table'

export const Route = createFileRoute('/admin/credits')({
  component: CreditsAdminPage,
})

function CreditsAdminPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.CREDITS_READ_ALL })
  const density = useThemeStore((state) => state.density)
  const hasPermission = useAuthStore((state) => state.hasPermission)
  const canGrant = hasPermission(PERMISSIONS.CREDITS_GRANT)
  const canDeduct = hasPermission(PERMISSIONS.CREDITS_DEDUCT)
  const canManageCredits = canGrant || canDeduct
  const canManageAllowance = canGrant
  const canManageSystemAllowance = hasPermission(PERMISSIONS.ADMIN_ACCESS)

  const {
    data: systemAllowanceData,
    isLoading: systemAllowanceLoading,
    refetch: refetchSystemAllowance,
  } = useSystemDailyAllowance()
  const updateSystemAllowance = useUpdateSystemDailyAllowance()

  const {
    data: systemMaxBalanceData,
    isLoading: systemMaxBalanceLoading,
    refetch: refetchSystemMaxBalance,
  } = useSystemMaxBalance()
  const updateSystemMaxBalance = useUpdateSystemMaxBalance()

  const {
    data: systemInitialBalanceData,
    isLoading: systemInitialBalanceLoading,
    refetch: refetchSystemInitialBalance,
  } = useSystemInitialBalance()
  const updateSystemInitialBalance = useUpdateSystemInitialBalance()

  const {
    data: systemLoginWindowData,
    isLoading: systemLoginWindowLoading,
    refetch: refetchSystemLoginWindow,
  } = useSystemAllowanceLoginWindow()
  const updateSystemLoginWindow = useUpdateSystemAllowanceLoginWindow()

  const [systemAllowanceInput, setSystemAllowanceInput] = useState('')
  const systemAllowanceValue = systemAllowanceData?.default_daily_allowance

  const [systemMaxBalanceInput, setSystemMaxBalanceInput] = useState('')
  const systemMaxBalanceValue = systemMaxBalanceData?.max_balance

  const [systemInitialBalanceInput, setSystemInitialBalanceInput] = useState('')
  const systemInitialBalanceValue = systemInitialBalanceData?.initial_balance

  const [systemLoginWindowInput, setSystemLoginWindowInput] = useState('')
  const systemLoginWindowValue = systemLoginWindowData?.login_window_hours

  const searchParams = useSearch({ from: '/admin/credits' }) as { user?: string }

  const {
    state: tableState,
    setPage,
    setLimit,
    setSort,
    setSearch,
  } = useDataTable({ defaultLimit: 20, defaultSortBy: 'nuke_balance', defaultSortOrder: 'asc' })

  const [sorting, setSorting] = useState<SortingState>([
    { id: tableState.sortBy, desc: tableState.sortOrder === 'desc' },
  ])
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({})
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})

  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [adjustDialogOpen, setAdjustDialogOpen] = useState(false)
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false)
  const [allowanceDialogOpen, setAllowanceDialogOpen] = useState(false)
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [bulkMode, setBulkMode] = useState<'grant' | 'allowance'>('grant')
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false)

  const selectedUserIds = useMemo(
    () => Object.keys(rowSelection).filter((id) => rowSelection[id]),
    [rowSelection]
  )
  const selectedCount = selectedUserIds.length

  const {
    data: usersData,
    isLoading,
    isError,
    error,
  } = useUsers({
    page: tableState.page,
    limit: tableState.limit,
    sort_by: sorting[0]?.id || 'nuke_balance',
    sort_order: sorting[0]?.desc ? 'desc' : 'asc',
    search: tableState.search,
  })

  const { data: lowBalanceData } = useLowBalanceUsers({ threshold: 100, page: 1, limit: 3 })

  useEffect(() => {
    if (searchParams.user && usersData?.data) {
      const user = usersData.data.find((u) => u.id === searchParams.user)
      if (user) queueMicrotask(() => setSelectedUser(user))
    }
  }, [searchParams.user, usersData])

  useEffect(() => {
    if (systemAllowanceValue !== undefined) {
      setSystemAllowanceInput(String(systemAllowanceValue))
    }
  }, [systemAllowanceValue])

  useEffect(() => {
    if (systemMaxBalanceValue !== undefined) {
      setSystemMaxBalanceInput(String(systemMaxBalanceValue))
    }
  }, [systemMaxBalanceValue])

  useEffect(() => {
    if (systemInitialBalanceValue !== undefined) {
      setSystemInitialBalanceInput(String(systemInitialBalanceValue))
    }
  }, [systemInitialBalanceValue])

  useEffect(() => {
    if (systemLoginWindowValue !== undefined) {
      setSystemLoginWindowInput(String(systemLoginWindowValue))
    }
  }, [systemLoginWindowValue])

  const users = useMemo(() => usersData?.data || [], [usersData?.data])
  const pagination = usersData?.pagination
  const lowBalanceUsers = useMemo(() => lowBalanceData?.users || [], [lowBalanceData?.users])

  const usersMap = useMemo(() => {
    const map: Record<string, string> = {}
    users.forEach((u) => {
      map[u.id] = u.username
    })
    lowBalanceUsers.forEach((u) => {
      map[u.id] = u.username
    })
    return map
  }, [users, lowBalanceUsers])

  const handleAdjust = useCallback((user: User) => {
    setSelectedUser(user)
    setAdjustDialogOpen(true)
  }, [])

  const handleViewHistory = useCallback((user: User) => {
    setSelectedUser(user)
    setHistoryDialogOpen(true)
  }, [])

  const handleSetAllowance = useCallback((user: User) => {
    setSelectedUser(user)
    setAllowanceDialogOpen(true)
  }, [])

  const handleSaveSystemAllowance = () => {
    const value = parseInt(systemAllowanceInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemAllowanceValue) return
    updateSystemAllowance.mutate(value)
  }

  const handleSaveSystemMaxBalance = () => {
    const value = parseInt(systemMaxBalanceInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemMaxBalanceValue) return
    updateSystemMaxBalance.mutate(value)
  }

  const handleSaveSystemInitialBalance = () => {
    const value = parseInt(systemInitialBalanceInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemInitialBalanceValue) return
    updateSystemInitialBalance.mutate(value)
  }

  const handleSaveSystemLoginWindow = () => {
    const value = parseInt(systemLoginWindowInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemLoginWindowValue) return
    updateSystemLoginWindow.mutate(value)
  }

  const systemSettings = [
    {
      key: 'allowance',
      title: 'Default Daily Allowance',
      description: 'NUKE / day applied to new users',
      icon: Coins,
      iconBg: 'bg-violet-500/10',
      iconColor: 'text-violet-400',
      input: systemAllowanceInput,
      setInput: setSystemAllowanceInput,
      value: systemAllowanceValue,
      loading: systemAllowanceLoading,
      isPending: updateSystemAllowance.isPending,
      onSave: handleSaveSystemAllowance,
      saveLabel: 'Save Default',
      display: (v?: number) => `${(v ?? 0).toLocaleString()} NUKE / day`,
    },
    {
      key: 'max-balance',
      title: 'Max Balance',
      description: 'Hard cap in NUKE, 0 = unlimited',
      icon: Scale,
      iconBg: 'bg-rose-500/10',
      iconColor: 'text-rose-400',
      input: systemMaxBalanceInput,
      setInput: setSystemMaxBalanceInput,
      value: systemMaxBalanceValue,
      loading: systemMaxBalanceLoading,
      isPending: updateSystemMaxBalance.isPending,
      onSave: handleSaveSystemMaxBalance,
      saveLabel: 'Save Cap',
      display: (v?: number) => (v === 0 ? 'Unlimited' : `${(v ?? 0).toLocaleString()} NUKE`),
    },
    {
      key: 'initial-balance',
      title: 'Signup Initial Balance',
      description: 'NUKE granted on first signup',
      icon: Gift,
      iconBg: 'bg-emerald-500/10',
      iconColor: 'text-emerald-400',
      input: systemInitialBalanceInput,
      setInput: setSystemInitialBalanceInput,
      value: systemInitialBalanceValue,
      loading: systemInitialBalanceLoading,
      isPending: updateSystemInitialBalance.isPending,
      onSave: handleSaveSystemInitialBalance,
      saveLabel: 'Save Initial Balance',
      display: (v?: number) => `${(v ?? 0).toLocaleString()} NUKE`,
    },
    {
      key: 'login-window',
      title: 'Allowance Login Window',
      description: 'Hours of recent login required',
      icon: Clock,
      iconBg: 'bg-amber-500/10',
      iconColor: 'text-amber-400',
      input: systemLoginWindowInput,
      setInput: setSystemLoginWindowInput,
      value: systemLoginWindowValue,
      loading: systemLoginWindowLoading,
      isPending: updateSystemLoginWindow.isPending,
      onSave: handleSaveSystemLoginWindow,
      saveLabel: 'Save Window',
      display: (v?: number) => `${v ?? 0} hours`,
    },
  ]

  const openBulkGrant = useCallback(() => {
    setBulkMode('grant')
    setBulkDialogOpen(true)
  }, [])

  const openBulkAllowance = useCallback(() => {
    setBulkMode('allowance')
    setBulkDialogOpen(true)
  }, [])

  const handleSetOverride = useCallback((user: User) => {
    setSelectedUser(user)
    setOverrideDialogOpen(true)
  }, [])

  const handleClearSelection = useCallback(() => {
    setRowSelection({})
  }, [])

  const SortIcon = ({ columnId }: { columnId: string }) => {
    const sort = sorting.find((s) => s.id === columnId)
    if (!sort) return <ArrowUpDown className="w-3 h-3 opacity-30" />
    return sort.desc ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />
  }

  const columns: ColumnDef<User>[] = [
    {
      accessorKey: 'username',
      header: () => (
        <button
          onClick={() => {
            const isAsc = sorting[0]?.id === 'username' && !sorting[0]?.desc
            setSorting([{ id: 'username', desc: isAsc }])
            setSort('username', isAsc ? 'desc' : 'asc')
          }}
          className="flex items-center gap-1 hover:text-primary transition-colors"
        >
          User
          <SortIcon columnId="username" />
        </button>
      ),
      cell: ({ row }) => {
        const user = row.original
        const isLow = user.nuke_balance <= 100
        return (
          <div className="flex items-center gap-3">
            <div
              className={cn(
                'w-9 h-9 rounded-full flex items-center justify-center shrink-0',
                isLow ? 'bg-amber-500/10' : 'bg-primary/10'
              )}
            >
              <span
                className={cn('text-xs font-medium', isLow ? 'text-amber-400' : 'text-primary')}
              >
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
        )
      },
    },
    {
      accessorKey: 'email',
      header: () => (
        <button
          onClick={() => {
            const isAsc = sorting[0]?.id === 'email' && !sorting[0]?.desc
            setSorting([{ id: 'email', desc: isAsc }])
            setSort('email', isAsc ? 'desc' : 'asc')
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
            const isAsc = sorting[0]?.id === 'nuke_balance' && !sorting[0]?.desc
            setSorting([{ id: 'nuke_balance', desc: isAsc }])
            setSort('nuke_balance', isAsc ? 'desc' : 'asc')
          }}
          className="flex items-center gap-1 hover:text-primary transition-colors ml-auto"
        >
          Balance
          <SortIcon columnId="nuke_balance" />
        </button>
      ),
      cell: ({ row }) => {
        const balance = row.getValue('nuke_balance') as number
        const isLow = balance <= 100
        return (
          <div className="text-right">
            <div
              className={cn(
                'font-mono font-semibold text-sm',
                isLow ? 'text-amber-400' : 'text-foreground'
              )}
            >
              {balance.toLocaleString()}
            </div>
            <div className="text-[10px] text-muted-foreground">NUKE</div>
          </div>
        )
      },
    },
    {
      accessorKey: 'daily_allowance',
      header: () => (
        <button
          onClick={() => {
            const isAsc = sorting[0]?.id === 'daily_allowance' && !sorting[0]?.desc
            setSorting([{ id: 'daily_allowance', desc: isAsc }])
            setSort('daily_allowance', isAsc ? 'desc' : 'asc')
          }}
          className="flex items-center gap-1 hover:text-primary transition-colors"
        >
          Allowance
          <SortIcon columnId="daily_allowance" />
        </button>
      ),
      cell: ({ row }) => {
        const user = row.original
        const allowance = row.getValue('daily_allowance') as number
        const overrideActive = user.has_active_allowance_override
        return (
          <div className="flex items-center gap-1.5 text-sm">
            <Wallet className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="font-mono">{(allowance ?? 0).toLocaleString()}</span>
            <span className="text-[10px] text-muted-foreground">/day</span>
            {overrideActive && (
              <Tooltip
                content={`Override active: ${user.daily_allowance_override} / day until ${user.daily_allowance_override_until ? parseUtcDate(user.daily_allowance_override_until).toLocaleString() : 'soon'}`}
              >
                <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400 cursor-help">
                  <Clock className="w-2.5 h-2.5" />
                  Override
                </span>
              </Tooltip>
            )}
          </div>
        )
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
      header: 'Actions',
      cell: ({ row }) => {
        const user = row.original
        return (
          <div className="flex items-center gap-1">
            <Tooltip content="View History">
              <button
                onClick={() => handleViewHistory(user)}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
              >
                <History className="w-4 h-4" />
              </button>
            </Tooltip>
            {canManageCredits && (
              <Tooltip content="Adjust Credits">
                <button
                  onClick={() => handleAdjust(user)}
                  className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors inline-flex"
                >
                  <CreditCard className="w-4 h-4" />
                </button>
              </Tooltip>
            )}
            {canManageAllowance && (
              <Tooltip content="Set Daily Allowance">
                <button
                  onClick={() => handleSetAllowance(user)}
                  className="p-1.5 rounded-lg hover:bg-violet-500/10 text-violet-400 transition-colors inline-flex"
                >
                  <Wallet className="w-4 h-4" />
                </button>
              </Tooltip>
            )}
            {canManageAllowance && (
              <Tooltip content="Time-boxed Override">
                <button
                  onClick={() => handleSetOverride(user)}
                  className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors inline-flex"
                >
                  <Clock className="w-4 h-4" />
                </button>
              </Tooltip>
            )}
          </div>
        )
      },
    },
  ]

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
  ]

  const mobileCardRenderer = (user: User) => {
    const isLow = user.nuke_balance <= 100
    return (
      <div className="p-4 space-y-3">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'w-10 h-10 rounded-full flex items-center justify-center',
              isLow ? 'bg-amber-500/10' : 'bg-primary/10'
            )}
          >
            <span className={cn('text-sm font-medium', isLow ? 'text-amber-400' : 'text-primary')}>
              {user.username.slice(0, 2).toUpperCase()}
            </span>
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{user.username}</span>
              {isLow && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
                  Low
                </span>
              )}
              {user.has_active_allowance_override && (
                <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
                  <Clock className="w-2.5 h-2.5" />
                  Override
                </span>
              )}
            </div>
            <span className="text-xs text-muted-foreground">{user.email}</span>
          </div>
          <div className="text-right space-y-0.5">
            <div className={cn('font-mono font-semibold', isLow ? 'text-amber-400' : '')}>
              {user.nuke_balance.toLocaleString()}
            </div>
            <div className="text-[10px] text-muted-foreground">NUKE</div>
            <div className="flex items-center justify-end gap-1 text-[11px] text-muted-foreground pt-0.5">
              <Wallet className="w-3 h-3" />
              <span className="font-mono">{(user.daily_allowance ?? 0).toLocaleString()}</span>
              <span>/day</span>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-1">
          <Tooltip content="View History">
            <button
              onClick={() => handleViewHistory(user)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
            >
              <History className="w-4 h-4" />
            </button>
          </Tooltip>
          {canManageCredits && (
            <Tooltip content="Adjust Credits">
              <button
                onClick={() => handleAdjust(user)}
                className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-emerald-400 transition-colors inline-flex"
              >
                <CreditCard className="w-4 h-4" />
              </button>
            </Tooltip>
          )}
          {canManageAllowance && (
            <Tooltip content="Set Daily Allowance">
              <button
                onClick={() => handleSetAllowance(user)}
                className="p-1.5 rounded-lg hover:bg-violet-500/10 text-violet-400 transition-colors inline-flex"
              >
                <Wallet className="w-4 h-4" />
              </button>
            </Tooltip>
          )}
          {canManageAllowance && (
            <Tooltip content="Time-boxed Override">
              <button
                onClick={() => handleSetOverride(user)}
                className="p-1.5 rounded-lg hover:bg-amber-500/10 text-amber-400 transition-colors inline-flex"
              >
                <Clock className="w-4 h-4" />
              </button>
            </Tooltip>
          )}
        </div>
      </div>
    )
  }

  if (!allowed) return null

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <Link
          to="/admin"
          className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="p-2 rounded-xl bg-primary/10">
          <CreditCard className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">Credit Management</h1>
          <p className="text-sm text-muted-foreground">
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
                        <p className="text-xs text-amber-400">
                          {lbUser.nuke_balance.toLocaleString()} NUKE
                        </p>
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
                          } as User)
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
                      setPage(1)
                      setSorting([{ id: 'nuke_balance', desc: false }])
                      setSort('nuke_balance', 'asc')
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

      {/* System Credit Settings */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="bubble p-5 space-y-4"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wallet className="w-4 h-4 text-violet-400" />
            <h3 className="font-semibold text-sm">System Credit Settings</h3>
          </div>
          <Tooltip content="Refresh all">
            <button
              onClick={() => {
                refetchSystemAllowance()
                refetchSystemMaxBalance()
                refetchSystemInitialBalance()
                refetchSystemLoginWindow()
              }}
              className="p-1.5 rounded-lg hover:bg-accent transition-colors"
            >
              <RefreshCw className="w-4 h-4 text-muted-foreground" />
            </button>
          </Tooltip>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-x-10">
          {systemSettings.map((s) => (
            <div
              key={s.key}
              className="flex items-center gap-3 py-3 border-b border-border/50 first:pt-0 last:border-0 xl:[&:nth-child(n+3)]:border-b-0 xl:[&:nth-child(n+3)]:pb-0"
            >
              <div
                className={cn(
                  'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
                  s.iconBg
                )}
              >
                <s.icon className={cn('w-4 h-4', s.iconColor)} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium leading-tight">{s.title}</p>
                <p className="text-xs text-muted-foreground leading-tight truncate">
                  {s.description}
                </p>
              </div>
              {s.loading && s.value === undefined ? (
                <div className="h-8 w-32 bg-muted/50 rounded-lg animate-pulse" />
              ) : canManageSystemAllowance ? (
                <div className="flex items-center gap-2 shrink-0">
                  <input
                    type="number"
                    min={0}
                    step={1}
                    aria-label={s.title}
                    value={s.input}
                    onChange={(e) => s.setInput(e.target.value)}
                    disabled={s.isPending}
                    className="w-28 h-8 px-2.5 text-sm text-right bg-background border border-border/50 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                  />
                  <Tooltip content={s.saveLabel}>
                    <Button
                      size="sm"
                      onClick={s.onSave}
                      disabled={
                        s.isPending ||
                        Number.isNaN(parseInt(s.input, 10)) ||
                        parseInt(s.input, 10) < 0 ||
                        parseInt(s.input, 10) === s.value
                      }
                      className="h-8 w-8 p-0 shrink-0"
                    >
                      {s.isPending ? (
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Check className="w-3.5 h-3.5" />
                      )}
                    </Button>
                  </Tooltip>
                </div>
              ) : (
                <span className="font-mono font-medium text-sm shrink-0">{s.display(s.value)}</span>
              )}
            </div>
          ))}
        </div>
      </motion.div>

      {/* Bulk action bar — appears when rows are selected */}
      {selectedCount > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-wrap items-center gap-2 p-3 rounded-xl bg-primary/5 border border-primary/20"
        >
          <div className="flex items-center gap-2 text-sm font-medium">
            <Users className="w-4 h-4 text-primary" />
            {selectedCount} user{selectedCount === 1 ? '' : 's'} selected
          </div>
          <div className="flex items-center gap-2 ml-auto">
            {canGrant && (
              <Button size="sm" variant="secondary" className="h-8 text-xs" onClick={openBulkGrant}>
                <CreditCard className="w-3.5 h-3.5" />
                <span className="ml-1.5">Bulk Grant</span>
              </Button>
            )}
            {canManageAllowance && (
              <Button
                size="sm"
                variant="secondary"
                className="h-8 text-xs"
                onClick={openBulkAllowance}
              >
                <Wallet className="w-3.5 h-3.5" />
                <span className="ml-1.5">Bulk Allowance</span>
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="h-8 text-xs"
              onClick={handleClearSelection}
            >
              <X className="w-3.5 h-3.5" />
              <span className="ml-1.5">Clear</span>
            </Button>
          </div>
        </motion.div>
      )}

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
          searchable
          searchPlaceholder="Search users..."
          density={density}
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
      <DailyAllowanceDialog
        user={selectedUser}
        open={allowanceDialogOpen}
        onOpenChange={setAllowanceDialogOpen}
      />
      <BulkCreditDialog
        mode={bulkMode}
        userIds={selectedUserIds}
        open={bulkDialogOpen}
        onOpenChange={setBulkDialogOpen}
      />
      <AllowanceOverrideDialog
        user={selectedUser}
        open={overrideDialogOpen}
        onOpenChange={setOverrideDialogOpen}
      />
    </div>
  )
}
