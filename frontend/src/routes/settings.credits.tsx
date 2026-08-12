// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Zap,
  History,
  ArrowDownLeft,
  Server,
  Gift,
  Clock,
  ChevronLeft,
  ChevronRight,
  SlidersHorizontal,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Wallet,
  HandCoins,
  MessageSquare,
  XCircle,
} from 'lucide-react'
import { useMyCreditSummary, useMyCreditHistory } from '../hooks/use-credits'
import { useMyCreditRequests, useCancelCreditRequest } from '../hooks/use-credit-requests'
import { useAuthStore } from '../stores/auth-store'
import { formatDate, formatRelativeTime, cn } from '../lib/utils'
import { Button } from '../components/ui/button'
import { useConfirmDialog } from '../components/ui/confirm-dialog'
import { CreditRequestDialog } from '../components/credit-request-dialog'
import { CreditRequestThreadDialog } from '../components/credit-request-thread-dialog'
import type { CreditRequest, CreditTransaction } from '../types/api'

const TYPE_CONFIG: Record<
  string,
  { label: string; icon: React.ElementType; color: string; bg: string }
> = {
  admin_grant: { label: 'Grant', icon: Gift, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  admin_deduct: {
    label: 'Deduct',
    icon: ArrowDownLeft,
    color: 'text-red-400',
    bg: 'bg-red-500/10',
  },
  server_usage: {
    label: 'Server Usage',
    icon: Server,
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
  },
  daily_allowance: {
    label: 'Daily Allowance',
    icon: Gift,
    color: 'text-violet-400',
    bg: 'bg-violet-500/10',
  },
}

const FILTER_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'admin_grant', label: 'Grant' },
  { value: 'admin_deduct', label: 'Deduct' },
  { value: 'server_usage', label: 'Usage' },
  { value: 'daily_allowance', label: 'Allowance' },
]

const REQUEST_STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: 'Pending', color: 'text-amber-400', bg: 'bg-amber-500/10' },
  needs_info: { label: 'Awaiting your reply', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  approved: { label: 'Approved', color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  rejected: { label: 'Rejected', color: 'text-red-400', bg: 'bg-red-500/10' },
  cancelled: { label: 'Cancelled', color: 'text-muted-foreground', bg: 'bg-muted' },
}

function isOpenRequest(req: CreditRequest) {
  return req.status === 'pending' || req.status === 'needs_info'
}

function getTypeConfig(type: string) {
  return (
    TYPE_CONFIG[type] || {
      label: type,
      icon: Clock,
      color: 'text-muted-foreground',
      bg: 'bg-muted',
    }
  )
}

function getSortIcon(column: string, sortBy: string, sortDesc: boolean): React.ReactNode {
  if (sortBy !== column) return <ArrowUpDown className="w-3 h-3 opacity-30" />
  return sortDesc ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />
}

export const Route = createFileRoute('/settings/credits')({
  component: CreditsSettingsPage,
})

function CreditsSettingsPage() {
  const user = useAuthStore((state) => state.user)
  const { data: summaryData } = useMyCreditSummary()
  const [page, setPage] = useState(1)
  const [limit] = useState(10)
  const [typeFilter, setTypeFilter] = useState('')
  const [sortBy, setSortBy] = useState('created_at')
  const [sortDesc, setSortDesc] = useState(true)
  const [requestDialogOpen, setRequestDialogOpen] = useState(false)
  const [threadRequest, setThreadRequest] = useState<CreditRequest | null>(null)
  const [threadDialogOpen, setThreadDialogOpen] = useState(false)

  const cancelRequest = useCancelCreditRequest()
  const { confirm, dialog: confirmDialog } = useConfirmDialog()

  const { data: openRequests } = useMyCreditRequests({ status: 'open', limit: 1 })
  const hasOpenRequest = (openRequests?.pagination.total ?? 0) > 0
  const { data: myRequestsData, isLoading: myRequestsLoading } = useMyCreditRequests({ limit: 5 })
  const myRequests = myRequestsData?.requests || []

  const handleViewThread = (req: CreditRequest) => {
    setThreadRequest(req)
    setThreadDialogOpen(true)
  }

  const handleCancelRequest = async (req: CreditRequest) => {
    const confirmed = await confirm({
      title: 'Cancel credit request?',
      description: `This cancels your request for ${req.amount.toLocaleString()} NUKE. You can submit a new request afterwards.`,
      confirmLabel: 'Cancel Request',
      variant: 'warning',
    })
    if (confirmed) cancelRequest.mutate(req.id)
  }

  const { data: historyData, isLoading } = useMyCreditHistory({
    page,
    limit,
    transaction_type: typeFilter || undefined,
    sort_by: sortBy,
    sort_order: sortDesc ? 'desc' : 'asc',
  })

  const summary = summaryData?.summary
  const balance = summaryData?.balance ?? user?.nuke_balance ?? 0
  const daily = summaryData?.daily_allowance ?? user?.daily_allowance ?? 0

  const transactions = historyData?.transactions || []
  const totalPages = historyData?.pagination.total_pages || 1
  const total = historyData?.pagination.total || 0

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortDesc(!sortDesc)
    } else {
      setSortBy(column)
      setSortDesc(column === 'created_at')
    }
    setPage(1)
  }

  return (
    <div className="min-h-screen space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3 px-6 lg:px-10 pt-6 lg:pt-8"
      >
        <Link
          to="/settings"
          className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="p-2 rounded-xl bg-amber-500/10">
          <Zap className="w-5 h-5 text-amber-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold">Credits</h1>
          <p className="text-sm text-muted-foreground">
            View your credit balance and transaction history
          </p>
        </div>
        <div className="ml-auto flex flex-col items-end gap-1">
          <Button
            size="sm"
            onClick={() => setRequestDialogOpen(true)}
            disabled={hasOpenRequest}
            className="gap-1.5"
            data-testid="request-credits-button"
          >
            <HandCoins className="w-4 h-4" />
            Request Credits
          </Button>
          {hasOpenRequest && (
            <p className="text-xs text-muted-foreground">
              Request pending review or awaiting your reply
            </p>
          )}
        </div>
      </motion.div>

      <div className="px-6 lg:px-10 pb-10 space-y-6">
        {/* Balance Cards */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="grid grid-cols-1 sm:grid-cols-3 gap-4"
        >
          <div className="p-5 rounded-xl bg-card/50 border border-border/50 space-y-1">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Wallet className="w-4 h-4" />
              <span className="text-xs font-medium uppercase tracking-wider">Current Balance</span>
            </div>
            <p className="text-2xl font-bold font-mono">
              {balance.toLocaleString()} <span className="text-sm text-muted-foreground">NUKE</span>
            </p>
          </div>
          <div className="p-5 rounded-xl bg-card/50 border border-border/50 space-y-1">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Gift className="w-4 h-4" />
              <span className="text-xs font-medium uppercase tracking-wider">Daily Allowance</span>
            </div>
            <p className="text-2xl font-bold font-mono">
              {daily.toLocaleString()} <span className="text-sm text-muted-foreground">NUKE</span>
            </p>
          </div>
          <div className="p-5 rounded-xl bg-card/50 border border-border/50 space-y-1">
            <div className="flex items-center gap-2 text-muted-foreground">
              <History className="w-4 h-4" />
              <span className="text-xs font-medium uppercase tracking-wider">
                Total Transactions
              </span>
            </div>
            <p className="text-2xl font-bold font-mono">{total.toLocaleString()}</p>
          </div>
        </motion.div>

        {/* Summary Stats */}
        {summary && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="grid grid-cols-2 sm:grid-cols-4 gap-4"
          >
            <div className="p-4 rounded-xl bg-primary/[0.03] border border-primary/10 text-center">
              <p className="text-xs text-muted-foreground mb-1">Total Earned</p>
              <p className="text-lg font-semibold font-mono text-emerald-400">
                +{summary.total_earned.toLocaleString()}
              </p>
            </div>
            <div className="p-4 rounded-xl bg-primary/[0.03] border border-primary/10 text-center">
              <p className="text-xs text-muted-foreground mb-1">Total Consumed</p>
              <p className="text-lg font-semibold font-mono text-red-400">
                -{summary.total_consumed.toLocaleString()}
              </p>
            </div>
            <div className="p-4 rounded-xl bg-primary/[0.03] border border-primary/10 text-center">
              <p className="text-xs text-muted-foreground mb-1">Today Consumed</p>
              <p className="text-lg font-semibold font-mono text-blue-400">
                {summary.today_consumed.toLocaleString()}
              </p>
            </div>
            <div className="p-4 rounded-xl bg-primary/[0.03] border border-primary/10 text-center">
              <p className="text-xs text-muted-foreground mb-1">Net Change</p>
              <p
                className={cn(
                  'text-lg font-semibold font-mono',
                  summary.total_earned - summary.total_consumed >= 0
                    ? 'text-emerald-400'
                    : 'text-red-400'
                )}
              >
                {summary.total_earned - summary.total_consumed >= 0 ? '+' : ''}
                {(summary.total_earned - summary.total_consumed).toLocaleString()}
              </p>
            </div>
          </motion.div>
        )}

        {/* My Requests */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.18 }}
          className="rounded-xl bg-card/50 border border-border/50 overflow-hidden"
        >
          <div className="flex items-center gap-2 p-4 border-b border-border/50">
            <HandCoins className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-medium">My Requests</span>
            <span className="text-xs text-muted-foreground">
              ({myRequestsData?.pagination.total ?? 0})
            </span>
          </div>

          {myRequestsLoading ? (
            <div className="divide-y divide-border/20">
              {[1, 2].map((i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-3 animate-pulse">
                  <div className="h-5 w-16 bg-muted rounded-full" />
                  <div className="h-4 w-20 bg-muted rounded" />
                  <div className="h-4 flex-1 bg-muted rounded" />
                  <div className="h-3 w-16 bg-muted rounded" />
                </div>
              ))}
            </div>
          ) : myRequests.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-3">
                <HandCoins className="w-6 h-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium text-muted-foreground">No credit requests yet</p>
            </div>
          ) : (
            <div className="divide-y divide-border/20">
              {myRequests.map((req) => (
                <RequestRow
                  key={req.id}
                  request={req}
                  onViewThread={handleViewThread}
                  onCancel={handleCancelRequest}
                />
              ))}
            </div>
          )}
        </motion.div>

        {/* Transaction History */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="rounded-xl bg-card/50 border border-border/50 overflow-hidden"
        >
          {/* Filter + Title */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 border-b border-border/50">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-muted-foreground" />
              <span className="text-sm font-medium">Transaction History</span>
              <span className="text-xs text-muted-foreground">({total})</span>
            </div>
            <div className="flex items-center gap-1 p-1 bg-muted rounded-lg self-start">
              <SlidersHorizontal className="w-3 h-3 text-muted-foreground ml-2 mr-1" />
              {FILTER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => {
                    setTypeFilter(opt.value)
                    setPage(1)
                  }}
                  className={cn(
                    'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                    typeFilter === opt.value
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            {/* Column Headers */}
            <div className="grid grid-cols-[100px_1fr_100px_100px_130px] gap-3 px-5 py-2.5 text-xs font-medium text-muted-foreground border-b border-border/30 bg-muted/20 min-w-[600px]">
              <button
                onClick={() => handleSort('type')}
                className="flex items-center gap-1 hover:text-primary transition-colors text-left"
              >
                Type {getSortIcon('type', sortBy, sortDesc)}
              </button>
              <button
                onClick={() => handleSort('description')}
                className="flex items-center gap-1 hover:text-primary transition-colors text-left"
              >
                Description {getSortIcon('description', sortBy, sortDesc)}
              </button>
              <button
                onClick={() => handleSort('amount')}
                className="flex items-center gap-1 hover:text-primary transition-colors justify-end"
              >
                Amount {getSortIcon('amount', sortBy, sortDesc)}
              </button>
              <button
                onClick={() => handleSort('balance_after')}
                className="flex items-center gap-1 hover:text-primary transition-colors justify-end"
              >
                Balance {getSortIcon('balance_after', sortBy, sortDesc)}
              </button>
              <button
                onClick={() => handleSort('created_at')}
                className="flex items-center gap-1 hover:text-primary transition-colors justify-end"
              >
                Time {getSortIcon('created_at', sortBy, sortDesc)}
              </button>
            </div>

            {isLoading ? (
              <TransactionSkeleton />
            ) : transactions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16">
                <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-3">
                  <History className="w-6 h-6 text-muted-foreground" />
                </div>
                <p className="text-sm font-medium text-muted-foreground">No transactions found</p>
              </div>
            ) : (
              <div className="divide-y divide-border/20 min-w-[600px]">
                {transactions.map((tx) => (
                  <TransactionRow key={tx.id} transaction={tx} />
                ))}
              </div>
            )}
          </div>

          {/* Footer Pagination */}
          <div className="p-3 border-t border-border/50 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {total > 0
                ? `Showing ${(page - 1) * limit + 1} to ${Math.min(page * limit, total)} of ${total}`
                : 'No results'}
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(1)}
                  disabled={page <= 1}
                  className="h-7 w-7 p-0"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => p - 1)}
                  disabled={page <= 1}
                  className="h-7 w-7 p-0"
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <div className="flex items-center gap-1 px-2">
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    let pageNum: number
                    if (totalPages <= 5) {
                      pageNum = i + 1
                    } else if (page <= 3) {
                      pageNum = i + 1
                    } else if (page >= totalPages - 2) {
                      pageNum = totalPages - 4 + i
                    } else {
                      pageNum = page - 2 + i
                    }
                    return (
                      <button
                        key={pageNum}
                        onClick={() => setPage(pageNum)}
                        className={cn(
                          'min-w-[1.75rem] h-7 px-1.5 rounded-lg text-xs font-medium transition-colors',
                          page === pageNum
                            ? 'bg-primary text-primary-foreground'
                            : 'hover:bg-accent'
                        )}
                      >
                        {pageNum}
                      </button>
                    )
                  })}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= totalPages}
                  className="h-7 w-7 p-0"
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(totalPages)}
                  disabled={page >= totalPages}
                  className="h-7 w-7 p-0"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </Button>
              </div>
            )}
          </div>
        </motion.div>

        <CreditRequestDialog open={requestDialogOpen} onOpenChange={setRequestDialogOpen} />
        <CreditRequestThreadDialog
          request={threadRequest}
          open={threadDialogOpen}
          onOpenChange={setThreadDialogOpen}
        />
        {confirmDialog}
      </div>
    </div>
  )
}

function RequestRow({
  request: req,
  onViewThread,
  onCancel,
}: {
  request: CreditRequest
  onViewThread: (req: CreditRequest) => void
  onCancel: (req: CreditRequest) => void
}) {
  const config = REQUEST_STATUS_CONFIG[req.status] || {
    label: req.status,
    color: 'text-muted-foreground',
    bg: 'bg-muted',
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="px-5 py-3 space-y-1.5 hover:bg-muted/20 transition-colors"
    >
      <div className="flex items-center gap-3">
        <span
          className={cn(
            'text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0',
            config.bg,
            config.color
          )}
        >
          {config.label}
        </span>
        <span className="font-mono font-semibold text-sm">
          {req.amount.toLocaleString()} <span className="text-muted-foreground">NUKE</span>
        </span>
        {req.status === 'approved' && req.granted_amount !== null && (
          <span className="text-xs text-emerald-400">
            granted {req.granted_amount.toLocaleString()} NUKE
          </span>
        )}
        <span className="text-xs text-muted-foreground ml-auto whitespace-nowrap">
          {formatRelativeTime(req.created_at)}
        </span>
      </div>
      <p className="text-sm text-muted-foreground line-clamp-2">{req.reason}</p>
      {req.review_note && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Admin note:</span> {req.review_note}
        </p>
      )}
      {isOpenRequest(req) && (
        <div className="flex items-center gap-2 pt-0.5">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs gap-1.5"
            onClick={() => onViewThread(req)}
            data-testid="credit-request-view-thread"
          >
            <MessageSquare className="w-3 h-3" />
            View Thread
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1.5 text-red-400 hover:text-red-300 hover:bg-red-500/10"
            onClick={() => onCancel(req)}
            data-testid="credit-request-cancel"
          >
            <XCircle className="w-3 h-3" />
            Cancel
          </Button>
        </div>
      )}
    </motion.div>
  )
}

function TransactionRow({ transaction: tx }: { transaction: CreditTransaction }) {
  const config = getTypeConfig(tx.type)
  const Icon = config.icon
  const isPositive = tx.amount > 0

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="grid grid-cols-[100px_1fr_100px_100px_130px] gap-3 px-5 py-3 items-center hover:bg-muted/20 transition-colors"
    >
      {/* Type */}
      <div className="flex items-center gap-2">
        <div
          className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0', config.bg)}
        >
          <Icon className={cn('w-4 h-4', config.color)} />
        </div>
        <span
          className={cn(
            'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
            config.bg,
            config.color
          )}
        >
          {config.label}
        </span>
      </div>

      {/* Description */}
      <div className="min-w-0">
        <p className="text-sm font-medium line-clamp-2">{tx.description}</p>
      </div>

      {/* Amount */}
      <span
        className={cn(
          'font-mono font-semibold text-sm text-right',
          isPositive ? 'text-emerald-400' : 'text-red-400'
        )}
      >
        {isPositive ? '+' : ''}
        {tx.amount.toLocaleString()}
      </span>

      {/* Balance After */}
      <span className="font-mono text-sm text-right text-muted-foreground">
        {tx.balance_after.toLocaleString()}
      </span>

      {/* Time */}
      <span className="text-xs text-muted-foreground text-right whitespace-nowrap">
        {formatDate(tx.created_at)}
      </span>
    </motion.div>
  )
}

function TransactionSkeleton() {
  return (
    <div className="divide-y divide-border/20 min-w-[600px]">
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className="grid grid-cols-[100px_1fr_100px_100px_130px] gap-3 px-5 py-3 items-center animate-pulse"
        >
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-muted shrink-0" />
            <div className="h-4 w-14 bg-muted rounded" />
          </div>
          <div className="space-y-1.5">
            <div className="h-4 w-48 bg-muted rounded" />
          </div>
          <div className="h-4 w-12 bg-muted rounded justify-self-end" />
          <div className="h-4 w-12 bg-muted rounded justify-self-end" />
          <div className="h-3 w-20 bg-muted rounded justify-self-end" />
        </div>
      ))}
    </div>
  )
}
