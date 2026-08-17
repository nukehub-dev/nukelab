// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import {
  Check,
  Clock,
  HandCoins,
  Hourglass,
  Inbox,
  MessageSquare,
  TrendingUp,
  X,
} from 'lucide-react'
import { UserLink } from '../user-link'
import {
  useAllCreditRequests,
  useCreditRequestStats,
  useBulkReviewCreditRequests,
} from '../../../hooks/use-credit-requests'
import { useAuthStore, PERMISSIONS } from '../../../stores/auth-store'
import { cn, formatDate, formatRelativeTime, parseUtcDate } from '../../../lib/utils'
import { api } from '../../../lib/api'
import { CreditRequestReviewDialog } from '../credit-request-review-dialog'
import { Card, CardContent, CardHeader, CardTitle } from '../../ui/card'
import { StatCard } from '../../data/stat-card'
import { Tooltip } from '../../ui/tooltip'
import { Button } from '../../ui/button'
import { Checkbox } from '../../ui/checkbox'
import { Input } from '../../ui/input'
import { useConfirmDialog } from '../../ui/confirm-dialog'
import type { CreditRequest, CreditRequestListResponse } from '../../../types/api'

const REQUEST_STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: 'Pending', color: 'text-amber-400', bg: 'bg-amber-500/10' },
  needs_info: { label: 'Needs Info', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  approved: { label: 'Approved', color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  rejected: { label: 'Rejected', color: 'text-red-400', bg: 'bg-red-500/10' },
  cancelled: { label: 'Cancelled', color: 'text-muted-foreground', bg: 'bg-muted' },
}

const REQUEST_FILTER_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'needs_info', label: 'Needs Info' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
]

const REQUEST_SORT_OPTIONS = [
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
] as const

/** Open requests older than this get an amber "waiting" highlight. */
const WAITING_THRESHOLD_MS = 24 * 60 * 60 * 1000

/** Inline outcome summary shown on terminal (approved/rejected/cancelled) rows. */
function getOutcomeText(req: CreditRequest): string {
  const reviewed = formatRelativeTime(req.reviewed_at ?? req.created_at)
  if (req.status === 'approved') {
    const amount = (req.granted_amount ?? req.amount).toLocaleString()
    const granted =
      req.request_type === 'allowance' ? `Set to ${amount} NUKE/day` : `Granted ${amount} NUKE`
    return `${granted} · reviewed ${reviewed}`
  }
  if (req.status === 'rejected') {
    return `Rejected · ${req.review_note?.trim() || 'no note'} · ${reviewed}`
  }
  return `Cancelled ${formatRelativeTime(req.created_at)}`
}

/**
 * Rejection note field for the bulk-reject confirm dialog. The confirm dialog
 * stores customContent as a one-time element snapshot, so the field must own
 * its state and report the value through the stable ref.
 */
function BulkRejectNoteField({ valueRef }: { valueRef: { current: string } }) {
  const [note, setNote] = useState('')
  return (
    <Input
      type="text"
      value={note}
      onChange={(e) => {
        setNote(e.target.value)
        valueRef.current = e.target.value
      }}
      placeholder="Optional rejection note shown to the users"
    />
  )
}

async function findAllCreditRequestById(requestId: string): Promise<CreditRequest | null> {
  for (let page = 1; page <= 10; page++) {
    const data = await api.get<CreditRequestListResponse>(
      `/credit-requests/all?limit=10&page=${page}`
    )
    const found = data.requests.find((req) => req.id === requestId)
    if (found) return found
    if (data.pagination.total_pages <= page) break
  }
  return null
}

export function RequestsTab({ focusRequestId }: { focusRequestId?: string }) {
  const hasPermission = useAuthStore((state) => state.hasPermission)
  const canGrant = hasPermission(PERMISSIONS.CREDITS_GRANT)

  const [requestStatusFilter, setRequestStatusFilter] = useState('pending')
  const [requestSort, setRequestSort] = useState<'newest' | 'oldest'>('newest')
  const [reviewRequest, setReviewRequest] = useState<CreditRequest | null>(null)
  const [reviewAction, setReviewAction] = useState<'approve' | 'reject'>('approve')
  const [reviewDialogOpen, setReviewDialogOpen] = useState(false)
  const [selectedRequestIds, setSelectedRequestIds] = useState<Record<string, boolean>>({})
  const bulkRejectNoteRef = useRef('')
  const handledFocusRequestIdRef = useRef<string | null>(null)
  const navigate = useNavigate()

  const handleReviewDialogOpenChange = (open: boolean) => {
    setReviewDialogOpen(open)
    if (!open && focusRequestId) {
      navigate({ to: '/admin/credits', search: (prev) => ({ ...prev, request: undefined }) })
    }
  }

  useEffect(() => {
    if (!focusRequestId || handledFocusRequestIdRef.current === focusRequestId) return
    let cancelled = false
    const openDeepLinkedRequest = async () => {
      const found = await findAllCreditRequestById(focusRequestId)
      if (!cancelled) {
        if (found) {
          setReviewRequest(found)
          setReviewAction('approve')
          setReviewDialogOpen(true)
        }
        handledFocusRequestIdRef.current = focusRequestId
      }
    }
    openDeepLinkedRequest()
    return () => {
      cancelled = true
    }
  }, [focusRequestId])

  const { data: requestStats } = useCreditRequestStats()
  const bulkReview = useBulkReviewCreditRequests()
  const { confirm: confirmBulkReview, dialog: bulkReviewDialog } = useConfirmDialog()
  const { data: requestsData, isLoading: requestsLoading } = useAllCreditRequests({
    status: requestStatusFilter || undefined,
    sort: requestSort,
    page: 1,
    limit: 10,
  })
  const creditRequests = useMemo(() => requestsData?.requests || [], [requestsData?.requests])

  // Snapshot of "now" for the 24h waiting highlight (impure Date.now() must not run per-row).
  const [now] = useState(() => Date.now())

  const openRequestCount =
    (requestStats?.counts.pending ?? 0) + (requestStats?.counts.needs_info ?? 0)
  // The backend may express approval_rate as a 0..1 fraction or a 0..100 percentage.
  const approvalRatePct = requestStats
    ? Math.round(
        requestStats.approval_rate <= 1
          ? requestStats.approval_rate * 100
          : requestStats.approval_rate
      )
    : 0

  const selectedReviewIds = useMemo(
    () => Object.keys(selectedRequestIds).filter((id) => selectedRequestIds[id]),
    [selectedRequestIds]
  )
  const selectedReviewCount = selectedReviewIds.length

  const handleReviewRequest = useCallback(
    (request: CreditRequest, action: 'approve' | 'reject') => {
      setReviewRequest(request)
      setReviewAction(action)
      setReviewDialogOpen(true)
    },
    []
  )

  // Opens the review dialog without a preset decision (toggle defaults to approve);
  // terminal requests render read-only there.
  const handleViewRequest = useCallback((request: CreditRequest) => {
    setReviewRequest(request)
    setReviewAction('approve')
    setReviewDialogOpen(true)
  }, [])

  const handleToggleRequestSelected = useCallback((id: string, checked: boolean) => {
    setSelectedRequestIds((prev) => ({ ...prev, [id]: checked }))
  }, [])

  const handleBulkApprove = async () => {
    if (selectedReviewIds.length === 0) return
    const confirmed = await confirmBulkReview({
      title: `Approve ${selectedReviewIds.length} request${selectedReviewIds.length === 1 ? '' : 's'}?`,
      description: 'Each requester is granted their requested amount.',
      confirmLabel: 'Approve All',
      variant: 'info',
    })
    if (!confirmed) return
    bulkReview.mutate(
      { requestIds: selectedReviewIds, action: 'approve' },
      { onSuccess: () => setSelectedRequestIds({}) }
    )
  }

  const handleBulkReject = async () => {
    if (selectedReviewIds.length === 0) return
    bulkRejectNoteRef.current = ''
    const confirmed = await confirmBulkReview({
      title: `Reject ${selectedReviewIds.length} request${selectedReviewIds.length === 1 ? '' : 's'}?`,
      description: 'Rejected requesters can submit a new request afterwards.',
      confirmLabel: 'Reject All',
      variant: 'destructive',
      customContent: <BulkRejectNoteField valueRef={bulkRejectNoteRef} />,
    })
    if (!confirmed) return
    bulkReview.mutate(
      {
        requestIds: selectedReviewIds,
        action: 'reject',
        note: bulkRejectNoteRef.current.trim() || undefined,
      },
      {
        onSuccess: () => {
          setSelectedRequestIds({})
        },
      }
    )
  }

  return (
    <>
      {/* Credit Requests */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="space-y-4"
      >
        {/* Stats strip */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            title="Open Requests"
            value={openRequestCount}
            icon={Inbox}
            iconColor="text-amber-400"
            bgColor="bg-amber-500/10"
            variant="compact"
          />
          <StatCard
            title="Approval Rate"
            value={`${approvalRatePct}%`}
            icon={TrendingUp}
            iconColor="text-emerald-400"
            bgColor="bg-emerald-500/10"
            variant="compact"
          />
          <StatCard
            title="Avg Decision"
            value={`${(requestStats?.avg_decision_hours ?? 0).toFixed(1)}h`}
            icon={Clock}
            iconColor="text-blue-400"
            bgColor="bg-blue-500/10"
            variant="compact"
          />
          <StatCard
            title="Oldest Open"
            value={`${Math.round(requestStats?.oldest_open_hours ?? 0)}h`}
            icon={Hourglass}
            iconColor="text-violet-400"
            bgColor="bg-violet-500/10"
            variant="compact"
          />
        </div>

        <Card>
          <CardHeader className="pb-2">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <HandCoins className="w-4 h-4 text-primary" />
                Credit Requests
                {openRequestCount > 0 && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
                    {openRequestCount} open
                  </span>
                )}
              </CardTitle>
              <div className="flex items-center gap-2 flex-wrap self-start">
                <div className="flex items-center gap-1 p-1 bg-muted rounded-lg">
                  {REQUEST_FILTER_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setRequestStatusFilter(opt.value)}
                      className={cn(
                        'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                        requestStatusFilter === opt.value
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-1 p-1 bg-muted rounded-lg">
                  {REQUEST_SORT_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setRequestSort(opt.value)}
                      className={cn(
                        'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                        requestSort === opt.value
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {/* Bulk selection bar */}
            {selectedReviewCount > 0 && (
              <div className="flex flex-wrap items-center gap-2 p-2.5 mb-3 rounded-lg bg-primary/5 border border-primary/20">
                <span className="text-xs font-medium">{selectedReviewCount} selected</span>
                <div className="flex items-center gap-1.5 ml-auto">
                  {canGrant && (
                    <Button
                      size="sm"
                      className="h-7 text-xs gap-1"
                      onClick={handleBulkApprove}
                      loading={bulkReview.isPending}
                    >
                      <Check className="w-3.5 h-3.5" />
                      Approve
                    </Button>
                  )}
                  {canGrant && (
                    <Button
                      size="sm"
                      variant="destructive"
                      className="h-7 text-xs gap-1"
                      onClick={handleBulkReject}
                      disabled={bulkReview.isPending}
                    >
                      <X className="w-3.5 h-3.5" />
                      Reject
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs"
                    onClick={() => setSelectedRequestIds({})}
                    disabled={bulkReview.isPending}
                  >
                    Clear
                  </Button>
                </div>
              </div>
            )}

            {requestsLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-border/50 bg-card/50 p-4 space-y-2.5 animate-pulse"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-full bg-muted shrink-0" />
                        <div className="h-4 w-28 bg-muted rounded" />
                      </div>
                      <div className="h-5 w-24 bg-muted rounded-full" />
                    </div>
                    <div className="h-4 w-3/4 bg-muted rounded" />
                    <div className="h-4 w-1/3 bg-muted rounded" />
                  </div>
                ))}
              </div>
            ) : creditRequests.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No {requestStatusFilter || ''} credit requests
                {requestStatusFilter ? ' with this status' : ''}.
              </p>
            ) : (
              <div className="space-y-2">
                {creditRequests.map((req) => {
                  const config = REQUEST_STATUS_CONFIG[req.status] || {
                    label: req.status,
                    color: 'text-muted-foreground',
                    bg: 'bg-muted',
                  }
                  const isOpen = req.status === 'pending' || req.status === 'needs_info'
                  const isWaiting =
                    isOpen && now - parseUtcDate(req.created_at).getTime() > WAITING_THRESHOLD_MS
                  return (
                    <div
                      key={req.id}
                      onClick={() => handleViewRequest(req)}
                      className="rounded-xl border border-border/50 bg-card/50 p-4 space-y-2.5 cursor-pointer hover:border-border hover:bg-card/80 transition-colors"
                    >
                      {/* Top line: user + badges */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3 min-w-0">
                          {isOpen && canGrant && (
                            <span onClick={(e) => e.stopPropagation()} className="shrink-0 pt-1">
                              <Checkbox
                                checked={!!selectedRequestIds[req.id]}
                                onChange={(checked) => handleToggleRequestSelected(req.id, checked)}
                                data-testid="credit-request-select"
                              />
                            </span>
                          )}
                          <span className="min-w-0" onClick={(e) => e.stopPropagation()}>
                            <UserLink
                              userId={req.user_id}
                              name={req.username || req.user_id}
                              secondary={req.email}
                              size="sm"
                              className="min-w-0"
                            />
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 flex-wrap justify-end shrink-0">
                          {isWaiting && (
                            <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
                              <Clock className="w-2.5 h-2.5" />
                              waiting
                            </span>
                          )}
                          <span
                            className={cn(
                              'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
                              config.bg,
                              config.color
                            )}
                          >
                            {config.label}
                          </span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-muted text-muted-foreground">
                            {req.request_type === 'allowance' ? 'Daily' : 'One-time'}
                          </span>
                        </div>
                      </div>

                      {/* Reason — primary triage content */}
                      <Tooltip content={req.reason}>
                        <p className="text-sm line-clamp-2">{req.reason}</p>
                      </Tooltip>

                      {/* Bottom line */}
                      {isOpen ? (
                        <div className="flex items-center justify-between gap-3 flex-wrap">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <span
                              className={cn(
                                'font-mono text-xs px-2 py-0.5 rounded-full',
                                req.request_type === 'allowance'
                                  ? 'text-violet-400 bg-violet-500/10'
                                  : 'text-emerald-400 bg-emerald-500/10'
                              )}
                            >
                              {req.request_type === 'allowance'
                                ? `${req.amount.toLocaleString()} NUKE/day`
                                : `+${req.amount.toLocaleString()} NUKE`}
                            </span>
                            <Tooltip content={formatDate(req.created_at)}>
                              <span className="text-xs text-muted-foreground whitespace-nowrap">
                                {formatRelativeTime(req.created_at)}
                              </span>
                            </Tooltip>
                          </div>
                          {canGrant && (
                            <div
                              className="flex items-center gap-1.5"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <button
                                onClick={() => handleViewRequest(req)}
                                className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-lg bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors"
                              >
                                <MessageSquare className="w-3.5 h-3.5" />
                                Review
                              </button>
                              <button
                                onClick={() => handleReviewRequest(req, 'approve')}
                                className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors"
                              >
                                <Check className="w-3.5 h-3.5" />
                                Approve
                              </button>
                              <button
                                onClick={() => handleReviewRequest(req, 'reject')}
                                className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                              >
                                <X className="w-3.5 h-3.5" />
                                Reject
                              </button>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground">{getOutcomeText(req)}</p>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      <CreditRequestReviewDialog
        request={reviewRequest}
        initialAction={reviewAction}
        open={reviewDialogOpen}
        onOpenChange={handleReviewDialogOpenChange}
      />
      {bulkReviewDialog}
    </>
  )
}
