// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import {
  Shield,
  Trash2,
  AlertTriangle,
  Info,
  Lock,
  Unlock,
  Globe,
  X,
  Copy,
  Check,
  Plus,
  ChevronDown,
} from 'lucide-react'
import { Tooltip } from '../components/ui/tooltip'
import { Label } from '../components/ui/label'
import { motion, AnimatePresence } from 'framer-motion'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { DataTable } from '../components/data/data-table'
import { useDataTable } from '../hooks/use-data-table'
import { PERMISSIONS } from '../stores/auth-store'
import { useThemeStore } from '../stores/theme-store'
import { usePageGuard } from '../hooks/use-page-guard'
import { useConfirmDialog } from '../components/ui/confirm-dialog'
import { useToast } from '../stores/toast-store'
import { formatDateOnly } from '../lib/utils'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '../components/ui/dialog'
import { Input } from '../components/ui/input'
import { Button } from '../components/ui/button'
import { api } from '../lib/api'
import type { ColumnDef } from '@tanstack/react-table'

export const Route = createFileRoute('/admin/ip-restrictions')({
  component: IPRestrictionsPage,
})

interface IPRestriction {
  id: string
  ip_range: string
  restriction_type: 'allow' | 'block'
  note: string | null
  is_active: boolean
  created_by_id: string | null
  created_at: string
}

interface MyIPResponse {
  ip: string
  note: string
}

interface CreatePayload {
  ip_range: string
  restriction_type: 'allow' | 'block'
  note?: string
}

type Mode = 'open' | 'blocklist' | 'allowlist'

function getActiveMode(items: IPRestriction[]): Mode {
  const active = items.filter((i) => i.is_active)
  if (active.some((i) => i.restriction_type === 'allow')) return 'allowlist'
  if (active.some((i) => i.restriction_type === 'block')) return 'blocklist'
  return 'open'
}

function ModeBanner({ mode }: { mode: Mode }) {
  if (mode === 'open') {
    return (
      <div className="flex items-start gap-3 p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
        <Unlock className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
        <div>
          <p className="font-medium text-emerald-400">Open Mode — All traffic allowed</p>
          <p className="text-sm text-emerald-400/70 mt-1">
            No active restrictions. The platform is accessible from any IP address.
          </p>
        </div>
      </div>
    )
  }

  if (mode === 'blocklist') {
    return (
      <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/20">
        <Lock className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <p className="font-medium text-amber-400">Blocklist Mode — Selective blocking</p>
          <p className="text-sm text-amber-400/70 mt-1">
            All traffic is allowed except IPs matching the blocklist entries below.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-3 p-4 rounded-xl bg-red-500/10 border border-red-500/20">
      <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
      <div>
        <p className="font-medium text-red-400">Allowlist Mode — Lockdown active</p>
        <p className="text-sm text-red-400/70 mt-1">
          Only IPs matching the allowlist below can access the platform.
          <span className="font-semibold text-red-400"> All other traffic is blocked.</span>
        </p>
      </div>
    </div>
  )
}

function GuideCard() {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-xl bg-card/50 border border-border/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full p-4 text-left hover:bg-card/80 transition-colors"
      >
        <Info className="w-4 h-4 text-primary" />
        <span className="font-medium text-sm">How IP restrictions work</span>
        <span className="ml-auto text-xs text-muted-foreground inline-flex items-center gap-1">
          {expanded ? 'Hide' : 'Show'}
          <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown className="w-3.5 h-3.5" />
          </motion.span>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-3 text-sm text-muted-foreground">
              <p>
                This page controls IP-based access to the platform. There are three possible states:
              </p>

              <div className="space-y-2">
                <div className="flex items-start gap-2">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 text-xs font-bold shrink-0 mt-0.5">
                    1
                  </span>
                  <div>
                    <span className="text-emerald-400 font-medium">Open Mode</span>
                    <span className="block">
                      {' '}
                      No restrictions. Anyone can access the platform. This is the default state.
                    </span>
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500/10 text-amber-400 text-xs font-bold shrink-0 mt-0.5">
                    2
                  </span>
                  <div>
                    <span className="text-amber-400 font-medium">Blocklist Mode</span>
                    <span className="block">
                      {' '}
                      You add specific IPs or ranges to block. Everything else is allowed. Use this
                      to ban known bad actors.
                    </span>
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-500/10 text-red-400 text-xs font-bold shrink-0 mt-0.5">
                    3
                  </span>
                  <div>
                    <span className="text-red-400 font-medium">Allowlist Mode</span>
                    <span className="block"> You add specific IPs or ranges to allow. </span>
                    <span className="font-semibold text-foreground">
                      Everything else is blocked.
                    </span>
                    <span>
                      {' '}
                      Use this for maximum security (e.g. restrict admin access to office VPNs
                      only).
                    </span>
                  </div>
                </div>
              </div>

              <div className="text-xs bg-amber-500/5 border border-amber-500/15 p-3 rounded-lg">
                <AlertTriangle className="w-3.5 h-3.5 inline mr-1.5 text-amber-400" />
                <span className="text-amber-400 font-medium">Warning:</span> Adding an allowlist
                entry immediately switches the platform into lockdown mode. Make sure your own IP is
                allowlisted first, or you will lock yourself out. Health checks, auth endpoints, and
                docs are always exempt from IP restrictions.
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function CurrentIPBadge({ onAdd }: { onAdd: (ip: string) => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['my-ip'],
    queryFn: async () => {
      const resp = await api.get<MyIPResponse>('/admin/ip-restrictions/my-ip')
      return resp
    },
    staleTime: 30000,
  })

  const [copied, setCopied] = useState(false)

  const ip = data?.ip ?? null

  const handleCopy = async () => {
    if (!ip) return
    try {
      await navigator.clipboard.writeText(ip)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback
    }
  }

  if (isLoading || !ip) {
    return (
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/50 text-muted-foreground text-sm">
        <Globe className="w-3.5 h-3.5 animate-pulse" />
        Detecting your IP...
      </div>
    )
  }

  return (
    <div className="inline-flex items-center gap-2 flex-wrap">
      <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary/10 border border-primary/20 text-primary text-sm font-mono">
        <Globe className="w-3.5 h-3.5" />
        {ip}
      </div>
      <button
        onClick={handleCopy}
        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
      >
        {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
        {copied ? 'Copied' : 'Copy'}
      </button>
      <button
        onClick={() => onAdd(ip)}
        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors"
      >
        <Plus className="w-3 h-3" />
        Add my IP
      </button>
    </div>
  )
}

function IPRestrictionsPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ADMIN_ACCESS })
  const density = useThemeStore((state) => state.density)
  const { confirm, dialog } = useConfirmDialog()
  const { success: showSuccess } = useToast()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [formData, setFormData] = useState<CreatePayload>({
    ip_range: '',
    restriction_type: 'block',
    note: '',
  })
  const [formError, setFormError] = useState('')

  const { state: tableState, setPage, setLimit, setSearch } = useDataTable({ defaultLimit: 20 })

  const { data, isLoading } = useQuery({
    queryKey: ['ip-restrictions', tableState.page, tableState.limit],
    queryFn: async () => {
      const resp = await api.get<IPRestriction[]>('/admin/ip-restrictions')
      return resp
    },
  })

  const items = data ?? []
  const total = items.length
  const mode = getActiveMode(items)
  const allowCount = items.filter((i) => i.restriction_type === 'allow' && i.is_active).length
  const blockCount = items.filter((i) => i.restriction_type === 'block' && i.is_active).length

  const createMutation = useMutation({
    mutationFn: (payload: CreatePayload) =>
      api.post<IPRestriction>('/admin/ip-restrictions', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ip-restrictions'] })
      setDialogOpen(false)
      setFormData({ ip_range: '', restriction_type: 'block', note: '' })
      setFormError('')
      showSuccess('Added', 'IP restriction created successfully')
    },
    onError: (err) => {
      setFormError(
        (err instanceof Error ? err.message : 'Failed to create restriction') ||
          'Failed to create restriction'
      )
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/admin/ip-restrictions/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ip-restrictions'] })
    },
  })

  const openCreateDialog = (prefill?: Partial<CreatePayload>) => {
    setFormData({
      ip_range: prefill?.ip_range ?? '',
      restriction_type: prefill?.restriction_type ?? 'block',
      note: prefill?.note ?? '',
    })
    setFormError('')
    setDialogOpen(true)
  }

  const mobileCardRenderer = (item: IPRestriction) => (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <code className="text-sm bg-muted px-2 py-0.5 rounded font-mono">{item.ip_range}</code>
        <span
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
            item.restriction_type === 'allow'
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
              : 'bg-red-500/10 text-red-400 border border-red-500/20'
          }`}
        >
          {item.restriction_type === 'allow' ? (
            <Unlock className="w-3 h-3" />
          ) : (
            <Lock className="w-3 h-3" />
          )}
          {item.restriction_type === 'allow' ? 'Allow' : 'Block'}
        </span>
      </div>
      {item.note && <div className="text-sm text-muted-foreground">{item.note}</div>}
      <div className="text-sm text-muted-foreground">
        Created: {formatDateOnly(item.created_at)}
      </div>
      <div className="flex items-center justify-end pt-1">
        <Tooltip content="Delete">
          <button
            onClick={async () => {
              const confirmed = await confirm({
                title: 'Delete Restriction',
                description: `Remove ${item.restriction_type === 'allow' ? 'allowlist' : 'blocklist'} entry for ${item.ip_range}?`,
                confirmLabel: 'Delete',
                cancelLabel: 'Cancel',
                variant: 'danger',
              })
              if (confirmed) {
                deleteMutation.mutate(item.id)
              }
            }}
            className="inline-flex p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </Tooltip>
      </div>
    </div>
  )

  const columns: ColumnDef<IPRestriction>[] = [
    {
      accessorKey: 'ip_range',
      header: 'IP Range',
      cell: ({ row }) => (
        <code className="text-sm bg-muted px-2 py-0.5 rounded font-mono">
          {row.original.ip_range}
        </code>
      ),
    },
    {
      accessorKey: 'restriction_type',
      header: 'Type',
      cell: ({ row }) => {
        const type = row.original.restriction_type
        return (
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
              type === 'allow'
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'bg-red-500/10 text-red-400 border border-red-500/20'
            }`}
          >
            {type === 'allow' ? <Unlock className="w-3 h-3" /> : <Lock className="w-3 h-3" />}
            {type === 'allow' ? 'Allow' : 'Block'}
          </span>
        )
      },
    },
    {
      accessorKey: 'note',
      header: 'Note',
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm">{row.original.note || '—'}</span>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm">
          {formatDateOnly(row.original.created_at)}
        </span>
      ),
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => {
        const item = row.original
        return (
          <div className="flex items-center gap-1">
            <button
              onClick={async () => {
                const confirmed = await confirm({
                  title: 'Delete Restriction',
                  description: `Remove ${item.restriction_type === 'allow' ? 'allowlist' : 'blocklist'} entry for ${item.ip_range}?`,
                  confirmLabel: 'Delete',
                  cancelLabel: 'Cancel',
                  variant: 'danger',
                })
                if (confirmed) {
                  deleteMutation.mutate(item.id)
                }
              }}
              className="inline-flex p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        )
      },
      enableSorting: false,
    },
  ]

  if (!allowed) return null

  return (
    <>
      <ResourcePageLayout
        title="IP Restrictions"
        subtitle="Manage IP-based access control"
        icon={Globe}
        backTo="/admin"
        stats={[
          {
            title: 'Allowlist',
            value: allowCount,
            icon: Shield,
            iconColor: 'text-emerald-400',
            bgColor: 'bg-emerald-500/10',
          },
          {
            title: 'Blocklist',
            value: blockCount,
            icon: Shield,
            iconColor: 'text-red-400',
            bgColor: 'bg-red-500/10',
          },
        ]}
        actions={[{ action: 'create', onClick: () => openCreateDialog() }]}
      >
        <div className="space-y-4 mb-6">
          <ModeBanner mode={mode} />
          <GuideCard />
        </div>

        <DataTable
          columns={columns}
          data={items}
          totalCount={total}
          pageCount={Math.ceil(total / tableState.limit) || 1}
          page={tableState.page}
          limit={tableState.limit}
          isLoading={isLoading}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onGlobalFilterChange={setSearch}
          globalFilter={tableState.search}
          onSortingChange={() => {}}
          onRowSelectionChange={() => {}}
          onColumnFiltersChange={() => {}}
          onColumnVisibilityChange={() => {}}
          sorting={[]}
          rowSelection={{}}
          columnFilters={[]}
          columnVisibility={{}}
          getRowId={(row) => row.id}
          enableRowSelection={false}
          density={density}
          mobileCardRenderer={mobileCardRenderer}
          searchable
          searchPlaceholder="Search IP ranges..."
        />
      </ResourcePageLayout>

      {/* Create Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader className="relative pr-8">
            <DialogTitle>Add IP Restriction</DialogTitle>
            <DialogDescription>Create a new allowlist or blocklist entry.</DialogDescription>
            <button
              onClick={() => setDialogOpen(false)}
              className="absolute right-0 top-0 p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </DialogHeader>

          <form
            className="space-y-4 mt-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (!formData.ip_range.trim()) {
                setFormError('IP range is required')
                return
              }
              createMutation.mutate(formData)
            }}
          >
            {/* Current IP */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Your Current IP
              </label>
              <CurrentIPBadge
                onAdd={(ip) =>
                  openCreateDialog({
                    ip_range: ip,
                    restriction_type: 'allow',
                    note: 'My IP',
                  })
                }
              />
            </div>

            <div className="space-y-2">
              <Label>Type</Label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={formData.restriction_type === 'block' ? 'default' : 'outline'}
                  onClick={() => setFormData({ ...formData, restriction_type: 'block' })}
                  className="flex-1 gap-2"
                >
                  <Lock className="w-4 h-4" />
                  Block
                </Button>
                <Button
                  type="button"
                  variant={formData.restriction_type === 'allow' ? 'default' : 'outline'}
                  onClick={() => setFormData({ ...formData, restriction_type: 'allow' })}
                  className="flex-1 gap-2"
                >
                  <Unlock className="w-4 h-4" />
                  Allow
                </Button>
              </div>
              {formData.restriction_type === 'allow' && (
                <div className="flex items-start gap-2 text-xs text-amber-400 bg-amber-500/10 p-3 rounded-lg border border-amber-500/20">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>
                    <strong>Lockdown Warning:</strong> Adding an allowlist entry will block ALL
                    traffic except allowlisted IPs. Make sure your own IP is included, or you will
                    lock yourself out.
                  </span>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>IP Range</Label>
              <Input
                value={formData.ip_range}
                onChange={(e) => setFormData({ ...formData, ip_range: e.target.value })}
                placeholder="192.168.1.1 or 10.0.0.0/24"
                autoFocus
              />
              <p className="text-xs text-muted-foreground">
                Enter a single IP or CIDR range (e.g. <code>10.0.0.0/8</code>).
              </p>
            </div>

            <div className="space-y-2">
              <Label>Note</Label>
              <Input
                value={formData.note}
                onChange={(e) => setFormData({ ...formData, note: e.target.value })}
                placeholder="Optional description..."
              />
            </div>

            {formError && (
              <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-lg">
                {formError}
              </div>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Adding...' : 'Add Restriction'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {dialog}
    </>
  )
}
