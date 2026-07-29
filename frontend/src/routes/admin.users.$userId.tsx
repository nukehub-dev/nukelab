// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Mail,
  CreditCard,
  Server,
  HardDrive,
  Activity,
  ShieldCheck,
  Clock,
  CalendarDays,
  LogIn,
  BadgeCheck,
  History,
  Cpu,
  MemoryStick,
  CircuitBoard,
  Wallet,
} from 'lucide-react'
import { usePageGuard } from '../hooks/use-page-guard'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { useUserDetail, useUserServers, useUserQuota } from '../hooks/use-users'
import { useCreditSummary, useCreditHistory } from '../hooks/use-credits'
import { useAdminVolumes } from '../hooks/use-admin-volumes'
import { useAuditLogs } from '../hooks/use-audit-logs'
import { CreditHistoryDialog } from '../components/admin/credit-history-dialog'
import { cn, formatBytes, parseUtcDate } from '../lib/utils'
import { springs } from '../lib/animations'

export const Route = createFileRoute('/admin/users/$userId')({
  component: UserDetailPage,
})

const SERVERS_VISIBLE = 6
const VOLUMES_VISIBLE = 5
const TRANSACTIONS_VISIBLE = 5
const ACTIVITY_VISIBLE = 10

function fmtDate(value?: string | null): string {
  if (!value) return '—'
  return parseUtcDate(value).toLocaleString()
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full',
        active ? 'bg-emerald-500/10 text-emerald-400' : 'bg-muted text-muted-foreground'
      )}
    >
      <span
        className={cn(
          'w-1.5 h-1.5 rounded-full',
          active ? 'bg-emerald-400' : 'bg-muted-foreground'
        )}
      />
      {active ? 'Active' : 'Inactive'}
    </span>
  )
}

function Section({
  title,
  icon: Icon,
  iconBg = 'bg-primary/10',
  iconColor = 'text-primary',
  count,
  action,
  children,
  delay = 0,
}: {
  title: string
  icon: React.ElementType
  iconBg?: string
  iconColor?: string
  count?: number
  action?: React.ReactNode
  children: React.ReactNode
  delay?: number
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, ...springs.gentle }}
      className="bubble p-5 space-y-4 w-full h-full flex flex-col"
    >
      <div className="flex items-center gap-3">
        <div className={cn('w-9 h-9 rounded-xl flex items-center justify-center shrink-0', iconBg)}>
          <Icon className={cn('w-5 h-5', iconColor)} />
        </div>
        <h3 className="font-semibold text-base">{title}</h3>
        {count !== undefined && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-medium">
            {count}
          </span>
        )}
        {action && <div className="ml-auto">{action}</div>}
      </div>
      <div className="flex-1">{children}</div>
    </motion.div>
  )
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
      <span className="text-sm text-right truncate">{children}</span>
    </div>
  )
}

function StatChip({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ElementType
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="flex items-center gap-2.5 rounded-lg bg-muted/30 px-3 py-2 min-w-0">
      <Icon className="w-4 h-4 text-muted-foreground shrink-0" />
      <div className="min-w-0">
        <p className="text-[10px] text-muted-foreground leading-tight">{label}</p>
        <p className="text-sm font-mono font-semibold leading-tight truncate">
          {value}
          {sub && <span className="text-[10px] font-normal text-muted-foreground"> {sub}</span>}
        </p>
      </div>
    </div>
  )
}

function UserDetailPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.USERS_READ })
  const canViewPii = useAuthStore((state) => state.hasPermission(PERMISSIONS.ADMIN_ACCESS))
  const canViewAudit = useAuthStore((state) => state.hasPermission(PERMISSIONS.AUDIT_READ))
  const { userId } = Route.useParams()
  const [historyOpen, setHistoryOpen] = useState(false)

  const { data: user, isLoading: userLoading } = useUserDetail(userId)
  const { data: serversData } = useUserServers(userId)
  const { data: quotaData, isError: quotaError } = useUserQuota(userId)
  const { data: creditSummary } = useCreditSummary(userId)
  const { data: creditHistory } = useCreditHistory(userId, {
    limit: TRANSACTIONS_VISIBLE,
    sort_order: 'desc',
  })
  const { data: volumesData } = useAdminVolumes({ owner_id: userId, limit: 50 })
  const { data: activityData } = useAuditLogs({ user_id: userId, limit: ACTIVITY_VISIBLE })

  if (!allowed) return null

  if (userLoading) {
    return (
      <div className="min-h-screen p-6 lg:p-10 space-y-6">
        <div className="h-24 bg-muted/50 rounded-xl animate-pulse" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="h-64 bg-muted/50 rounded-xl animate-pulse" />
          <div className="h-64 bg-muted/50 rounded-xl animate-pulse" />
        </div>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="min-h-screen p-6 lg:p-10">
        <p className="text-sm text-muted-foreground">User not found.</p>
      </div>
    )
  }

  const quota = quotaData?.data
  const allServers = serversData?.servers ?? []
  const runningCount = allServers.filter((s) => s.status === 'running').length
  const allVolumes = volumesData?.volumes ?? []
  const transactions = creditHistory?.transactions ?? []
  const transactionsTotal = creditHistory?.pagination?.total ?? transactions.length
  const activityLogs = activityData?.logs ?? []

  const quotaRows: Array<{
    label: string
    icon: React.ElementType
    usage: number
    limit: number | null | undefined
    format: (v: number) => string
  }> = quota
    ? [
        {
          label: 'Servers',
          icon: Server,
          usage: quota.usage.servers,
          limit: quota.limits.max_servers_total,
          format: String,
        },
        {
          label: 'CPU',
          icon: Cpu,
          usage: quota.usage.cpu,
          limit: quota.limits.max_cpu_total,
          format: (v) => `${v} cores`,
        },
        {
          label: 'Memory',
          icon: MemoryStick,
          usage: quota.usage.memory_mb,
          limit: quota.limits.max_memory_total,
          format: (v) => formatBytes(v * 1024 * 1024),
        },
        {
          label: 'Disk',
          icon: HardDrive,
          usage: quota.usage.disk_mb,
          limit: quota.limits.max_disk_total,
          format: (v) => formatBytes(v * 1024 * 1024),
        },
        {
          label: 'GPU',
          icon: CircuitBoard,
          usage: quota.usage.gpu,
          limit: quota.limits.max_gpu_total,
          format: String,
        },
      ]
    : []

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-6">
      {/* Header card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bubble p-5"
      >
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-center gap-4 flex-1 min-w-0">
            <Link
              to="/admin/users"
              className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={user.username}
                className="w-14 h-14 rounded-full shrink-0"
              />
            ) : (
              <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                <span className="text-lg font-semibold text-primary">
                  {user.username.slice(0, 2).toUpperCase()}
                </span>
              </div>
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl font-bold truncate">{user.display_name || user.username}</h1>
                <StatusBadge active={user.is_active} />
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary">
                  {user.role}
                </span>
                {user.is_verified && (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                    <BadgeCheck className="w-3.5 h-3.5" />
                    Verified
                  </span>
                )}
              </div>
              <p className="text-sm text-muted-foreground truncate">
                @{user.username}
                {canViewPii && user.email && ` · ${user.email}`}
              </p>
            </div>
          </div>
        </div>

        {/* Quick stats */}
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-2 mt-4">
          <StatChip
            icon={CreditCard}
            label="Balance"
            value={(creditSummary?.balance ?? user.nuke_balance).toLocaleString()}
            sub="NUKE"
          />
          <StatChip
            icon={Wallet}
            label="Allowance"
            value={(creditSummary?.daily_allowance ?? user.daily_allowance ?? 0).toLocaleString()}
            sub="/ day"
          />
          <StatChip
            icon={Server}
            label="Servers"
            value={`${runningCount} / ${allServers.length}`}
            sub="running"
          />
          <StatChip icon={HardDrive} label="Volumes" value={String(allVolumes.length)} />
          <StatChip
            icon={Clock}
            label="Last login"
            value={user.last_login ? parseUtcDate(user.last_login).toLocaleDateString() : '—'}
          />
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Profile */}
        <Section title="Profile" icon={ShieldCheck} iconColor="text-primary" delay={0.05}>
          <div className="divide-y divide-border/50">
            {canViewPii && (
              <InfoRow label="Email">
                <span className="inline-flex items-center gap-1.5">
                  <Mail className="w-3.5 h-3.5 text-muted-foreground" />
                  {user.email || '—'}
                </span>
              </InfoRow>
            )}
            {canViewPii && user.oauth_provider && (
              <InfoRow label="OAuth provider">{user.oauth_provider}</InfoRow>
            )}
            <InfoRow label="Created">
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays className="w-3.5 h-3.5 text-muted-foreground" />
                {fmtDate(user.created_at)}
              </span>
            </InfoRow>
            <InfoRow label="Last login">{fmtDate(user.last_login)}</InfoRow>
            {canViewPii && (
              <InfoRow label="Login count">
                <span className="inline-flex items-center gap-1.5">
                  <LogIn className="w-3.5 h-3.5 text-muted-foreground" />
                  {user.login_count ?? 0}
                </span>
              </InfoRow>
            )}
            <InfoRow label="Profile visibility">{user.profile_visibility || 'private'}</InfoRow>
          </div>
        </Section>

        {/* Credits */}
        <Section
          title="Credits"
          icon={CreditCard}
          iconBg="bg-emerald-500/10"
          iconColor="text-emerald-400"
          delay={0.1}
          action={
            transactionsTotal > 0 ? (
              <button
                onClick={() => setHistoryOpen(true)}
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <History className="w-3.5 h-3.5" />
                View all ({transactionsTotal})
              </button>
            ) : undefined
          }
        >
          {transactions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No transactions yet.</p>
          ) : (
            <div className="divide-y divide-border/50">
              {transactions.map((tx) => (
                <div key={tx.id} className="flex items-center justify-between gap-3 py-1.5">
                  <div className="min-w-0">
                    <p className="text-sm truncate">{tx.description || tx.type}</p>
                    <p className="text-[11px] text-muted-foreground">{fmtDate(tx.created_at)}</p>
                  </div>
                  <span
                    className={cn(
                      'font-mono text-sm shrink-0',
                      tx.amount >= 0 ? 'text-emerald-400' : 'text-destructive'
                    )}
                  >
                    {tx.amount >= 0 ? '+' : ''}
                    {tx.amount.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Servers */}
        <Section
          title="Servers"
          icon={Server}
          iconBg="bg-blue-500/10"
          iconColor="text-blue-400"
          count={allServers.length}
          delay={0.15}
        >
          {allServers.length === 0 ? (
            <p className="text-sm text-muted-foreground">No servers.</p>
          ) : (
            <div className="max-h-64 overflow-y-auto pr-1 divide-y divide-border/50">
              {allServers.slice(0, SERVERS_VISIBLE).map((s) => (
                <Link
                  key={s.id}
                  to="/servers/$serverId"
                  params={{ serverId: s.id }}
                  className="flex items-center justify-between gap-3 py-2 px-2 rounded-lg hover:bg-accent/50 transition-colors"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{s.name}</p>
                    <p className="text-[11px] text-muted-foreground">{fmtDate(s.created_at)}</p>
                  </div>
                  <span
                    className={cn(
                      'text-xs px-2 py-0.5 rounded-full shrink-0',
                      s.status === 'running'
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : 'bg-muted text-muted-foreground'
                    )}
                  >
                    {s.status}
                  </span>
                </Link>
              ))}
              {allServers.length > SERVERS_VISIBLE && (
                <p className="text-xs text-muted-foreground pt-2">
                  + {allServers.length - SERVERS_VISIBLE} more (scroll)
                </p>
              )}
            </div>
          )}
        </Section>

        {/* Volumes & Quota */}
        <Section
          title="Volumes & Quota"
          icon={HardDrive}
          iconBg="bg-violet-500/10"
          iconColor="text-violet-400"
          count={allVolumes.length}
          delay={0.2}
        >
          {quotaError && (
            <p className="text-xs text-muted-foreground italic">
              Quota usage requires elevated permission.
            </p>
          )}
          {quotaRows.length > 0 && (
            <div className="space-y-2.5">
              {quotaRows.map((row) => {
                const hasLimit = !!row.limit && row.limit > 0
                const pct = hasLimit ? Math.min(100, (row.usage / row.limit!) * 100) : null
                return (
                  <div key={row.label} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                        <row.icon className="w-3.5 h-3.5" />
                        {row.label}
                      </span>
                      <span className="font-mono">
                        {row.format(row.usage)}
                        {hasLimit ? (
                          <span className="text-muted-foreground"> / {row.format(row.limit!)}</span>
                        ) : (
                          <span className="text-muted-foreground"> · unlimited</span>
                        )}
                      </span>
                    </div>
                    {pct !== null && (
                      <div className="h-1.5 rounded-full bg-muted/50 overflow-hidden">
                        <div
                          className={cn(
                            'h-full rounded-full',
                            pct >= 90
                              ? 'bg-destructive'
                              : pct >= 70
                                ? 'bg-amber-400'
                                : 'bg-emerald-400'
                          )}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {allVolumes.length > 0 && (
            <div className="max-h-56 overflow-y-auto pr-1 divide-y divide-border/50">
              {allVolumes.slice(0, VOLUMES_VISIBLE).map((v) => (
                <div key={v.id} className="flex items-center justify-between gap-3 py-1.5">
                  <div className="min-w-0">
                    <p className="text-sm truncate">{v.display_name || v.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {v.server_count} server{v.server_count === 1 ? '' : 's'}
                    </p>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground shrink-0">
                    {formatBytes(v.size_bytes)}
                  </span>
                </div>
              ))}
              {allVolumes.length > VOLUMES_VISIBLE && (
                <p className="text-xs text-muted-foreground pt-2">
                  + {allVolumes.length - VOLUMES_VISIBLE} more (scroll)
                </p>
              )}
            </div>
          )}
          {allVolumes.length === 0 && !quotaError && quotaRows.length === 0 && (
            <p className="text-sm text-muted-foreground">No volumes.</p>
          )}
        </Section>
      </div>

      {/* Activity — admin only (PII-adjacent) */}
      {canViewAudit && (
        <Section
          title="Recent Activity"
          icon={Activity}
          iconBg="bg-amber-500/10"
          iconColor="text-amber-400"
          count={activityData?.pagination?.total}
          delay={0.25}
        >
          {activityLogs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No recorded activity.</p>
          ) : (
            <div className="max-h-72 overflow-y-auto pr-1 divide-y divide-border/50">
              {activityLogs.map((log) => (
                <div key={log.id} className="flex items-center justify-between gap-3 py-1.5">
                  <p className="text-sm truncate">
                    <span className="font-mono text-xs bg-muted/50 rounded px-1.5 py-0.5 mr-2">
                      {log.action}
                    </span>
                    {log.target_type}
                  </p>
                  <span className="text-[11px] text-muted-foreground shrink-0 inline-flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {fmtDate(log.created_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      <CreditHistoryDialog user={user} open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </div>
  )
}
