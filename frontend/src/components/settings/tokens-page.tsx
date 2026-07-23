// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Key,
  Plus,
  Copy,
  Check,
  RefreshCw,
  Trash2,
  Ban,
  Clock,
  Calendar,
  Activity,
  Shield,
  Eye,
  EyeOff,
  Terminal,
  ChevronDown,
  ChevronUp,
  Tag,
} from 'lucide-react'
import { useTokens, useTokenActions } from '../../hooks/use-tokens'
import { useToast } from '../../stores/toast-store'
import { useConfirmDialog } from '../ui/confirm-dialog'
import { Tooltip } from '../ui/tooltip'
import { cn, formatDate, formatRelativeTime } from '../../lib/utils'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../ui/dialog'
import { Input } from '../ui/input'
import { Button } from '../ui/button'
import { Select, SelectItem } from '../ui/select'
import { Checkbox } from '../ui/checkbox'
import { Label } from '../ui/label'
import { EmptyState } from '../feedback/empty-state'
import type { ApiToken, ApiTokenWithValue } from '../../types/api'

// Values must match VALID_TOKEN_SCOPES in backend/app/api/tokens.py.
const AVAILABLE_SCOPES = [
  // Servers
  {
    value: 'servers:read',
    label: 'Read Servers',
    description: 'View server details',
    category: 'Servers',
  },
  {
    value: 'servers:manage',
    label: 'Manage Servers',
    description: 'Create, start, stop, and delete servers',
    category: 'Servers',
  },
  // Volumes
  {
    value: 'volumes:read',
    label: 'Read Volumes',
    description: 'View volume details',
    category: 'Volumes',
  },
  {
    value: 'volumes:manage',
    label: 'Manage Volumes',
    description: 'Create and manage volumes',
    category: 'Volumes',
  },
  // Workspaces
  {
    value: 'workspaces:read',
    label: 'Read Workspaces',
    description: 'View workspace details',
    category: 'Workspaces',
  },
  {
    value: 'workspaces:manage',
    label: 'Manage Workspaces',
    description: 'Create and manage workspaces',
    category: 'Workspaces',
  },
  // User
  {
    value: 'user:read',
    label: 'Read User',
    description: 'View user profile information',
    category: 'User',
  },
  {
    value: 'user:update',
    label: 'Update User',
    description: 'Update user profile',
    category: 'User',
  },
  // Credits
  {
    value: 'credits:read',
    label: 'Read Credits',
    description: 'View credit balance and history',
    category: 'Credits',
  },
  // Notifications
  {
    value: 'notifications:read',
    label: 'Read Notifications',
    description: 'View notifications',
    category: 'Notifications',
  },
  {
    value: 'notifications:write',
    label: 'Manage Notifications',
    description: 'Mark notifications as read',
    category: 'Notifications',
  },
  // Preferences
  {
    value: 'preferences:read',
    label: 'Read Preferences',
    description: 'View user preferences',
    category: 'Preferences',
  },
  {
    value: 'preferences:write',
    label: 'Write Preferences',
    description: 'Update user preferences',
    category: 'Preferences',
  },
]

const EXPIRATION_OPTIONS = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '180', label: '6 months' },
  { value: '365', label: '1 year' },
]

export function TokensPage() {
  const { data: tokens, isLoading } = useTokens()
  const actions = useTokenActions()
  const { confirm, dialog } = useConfirmDialog()
  const { success: toastSuccess } = useToast()

  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newToken, setNewToken] = useState<ApiTokenWithValue | null>(null)
  const [expandedTokenId, setExpandedTokenId] = useState<string | null>(null)

  const handleCreateSuccess = useCallback((token: ApiTokenWithValue) => {
    setNewToken(token)
    setShowCreateDialog(false)
  }, [])

  const handleRegenerateSuccess = useCallback((token: ApiTokenWithValue) => {
    setNewToken(token)
  }, [])

  const handleCopyToken = async (token: string) => {
    await navigator.clipboard.writeText(token)
    toastSuccess('Copied', 'Token copied to clipboard')
  }

  const handleRevoke = async (token: ApiToken) => {
    const confirmed = await confirm({
      title: 'Revoke Token',
      description: `Are you sure you want to revoke "${token.name}"? This token will no longer work, but the record will be kept.`,
      variant: 'warning',
      confirmLabel: 'Revoke',
      cancelLabel: 'Cancel',
    })
    if (confirmed) {
      actions.revokeToken.mutate(token.id)
    }
  }

  const handleDelete = async (token: ApiToken) => {
    const confirmed = await confirm({
      title: 'Delete Token Permanently',
      description: `Are you sure you want to permanently delete "${token.name}"? This action cannot be undone.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    })
    if (confirmed) {
      actions.deleteToken.mutate(token.id)
    }
  }

  const handleRegenerate = async (token: ApiToken) => {
    const confirmed = await confirm({
      title: 'Regenerate Token',
      description: `This will revoke the current "${token.name}" token and create a new one with the same settings. The old token will stop working immediately.`,
      variant: 'info',
      confirmLabel: 'Regenerate',
      cancelLabel: 'Cancel',
    })
    if (confirmed) {
      actions.regenerateToken.mutate(token.id, {
        onSuccess: (data) => {
          handleRegenerateSuccess(data as unknown as ApiTokenWithValue)
        },
      })
    }
  }

  const activeTokens = tokens?.filter((t) => t.is_active) ?? []
  const revokedTokens = tokens?.filter((t) => !t.is_active) ?? []

  return (
    <>
      {dialog}

      {/* New Token Reveal Dialog */}
      <Dialog open={!!newToken} onOpenChange={(open) => !open && setNewToken(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Key className="w-5 h-5 text-primary" />
              API Token Created
            </DialogTitle>
            <DialogDescription>
              Copy your token now. For security reasons, it will not be shown again.
            </DialogDescription>
          </DialogHeader>

          {newToken && (
            <div className="mt-4 space-y-4">
              <div className="p-4 rounded-xl bg-primary/5 border border-primary/20">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-primary uppercase tracking-wider">
                    Token Value
                  </span>
                  <CopyButton
                    text={newToken.token}
                    onCopy={() => handleCopyToken(newToken.token)}
                  />
                </div>
                <TokenReveal value={newToken.token} />
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="p-3 rounded-lg bg-muted/50">
                  <span className="text-muted-foreground block text-xs mb-1">Name</span>
                  <span className="font-medium">{newToken.name}</span>
                </div>
                <div className="p-3 rounded-lg bg-muted/50">
                  <span className="text-muted-foreground block text-xs mb-1">Expires</span>
                  <span className="font-medium">
                    {newToken.expires_at ? formatDate(newToken.expires_at) : 'Never'}
                  </span>
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button onClick={() => setNewToken(null)}>Done</Button>
          </DialogFooter>
          <DialogClose onClick={() => setNewToken(null)} />
        </DialogContent>
      </Dialog>

      {/* Create Token Dialog */}
      <CreateTokenDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        onSuccess={handleCreateSuccess}
        isCreating={actions.createToken.isPending}
      />

      <div className="space-y-6">
        <div className="flex justify-end">
          <Button onClick={() => setShowCreateDialog(true)} className="gap-2">
            <Plus className="w-4 h-4" />
            Create Token
          </Button>
        </div>

        {isLoading ? (
          <TokenListSkeleton />
        ) : tokens && tokens.length > 0 ? (
          <div className="space-y-6">
            {/* Active Tokens */}
            {activeTokens.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                  Active Tokens ({activeTokens.length})
                </h3>
                <AnimatePresence mode="popLayout">
                  {activeTokens.map((token) => (
                    <TokenCard
                      key={token.id}
                      token={token}
                      isExpanded={expandedTokenId === token.id}
                      onToggleExpand={() =>
                        setExpandedTokenId(expandedTokenId === token.id ? null : token.id)
                      }
                      onRegenerate={() => handleRegenerate(token)}
                      onRevoke={() => handleRevoke(token)}
                      onDelete={() => handleDelete(token)}
                      isRegenerating={actions.regenerateToken.isPending}
                      isRevoking={actions.revokeToken.isPending}
                      isDeleting={actions.deleteToken.isPending}
                    />
                  ))}
                </AnimatePresence>
              </div>
            )}

            {/* Revoked Tokens */}
            {revokedTokens.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                  Revoked Tokens ({revokedTokens.length})
                </h3>
                <AnimatePresence mode="popLayout">
                  {revokedTokens.map((token) => (
                    <TokenCard
                      key={token.id}
                      token={token}
                      isExpanded={expandedTokenId === token.id}
                      onToggleExpand={() =>
                        setExpandedTokenId(expandedTokenId === token.id ? null : token.id)
                      }
                      onRegenerate={() => handleRegenerate(token)}
                      onRevoke={() => handleRevoke(token)}
                      onDelete={() => handleDelete(token)}
                      isRegenerating={actions.regenerateToken.isPending}
                      isRevoking={actions.revokeToken.isPending}
                      isDeleting={actions.deleteToken.isPending}
                    />
                  ))}
                </AnimatePresence>
              </div>
            )}
          </div>
        ) : (
          <EmptyState
            icon={Key}
            title="No API Tokens"
            description="Create a personal access token to authenticate with the NukeLab API from tools like VS Code, CLI, or CI/CD pipelines."
            action={{
              label: 'Create Token',
              onClick: () => setShowCreateDialog(true),
              icon: Plus,
            }}
          />
        )}
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Create Token Dialog                                                 */
/* ------------------------------------------------------------------ */

function CreateTokenDialog({
  open,
  onOpenChange,
  onSuccess,
  isCreating,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: (token: ApiTokenWithValue) => void
  isCreating: boolean
}) {
  const actions = useTokenActions()
  const [name, setName] = useState('')
  const [expiresDays, setExpiresDays] = useState('30')
  const [selectedScopes, setSelectedScopes] = useState<string[]>(['servers:read', 'servers:manage'])
  const [nameError, setNameError] = useState('')

  const toggleScope = (scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    )
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setNameError('Token name is required')
      return
    }
    if (selectedScopes.length === 0) {
      setNameError('Select at least one scope')
      return
    }
    setNameError('')

    actions.createToken.mutate(
      {
        name: name.trim(),
        scopes: selectedScopes,
        expires_days: parseInt(expiresDays, 10),
      },
      {
        onSuccess: (data) => {
          onSuccess(data as unknown as ApiTokenWithValue)
          setName('')
          setSelectedScopes(['servers:read', 'servers:manage'])
          setExpiresDays('30')
        },
      }
    )
  }

  const handleClose = () => {
    if (!isCreating) {
      setName('')
      setNameError('')
      setSelectedScopes(['servers:read', 'servers:manage'])
      setExpiresDays('30')
      onOpenChange(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plus className="w-5 h-5 text-primary" />
            Create API Token
          </DialogTitle>
          <DialogDescription>
            Create a new personal access token for programmatic access to NukeLab.
          </DialogDescription>
        </DialogHeader>

        <form id="create-token-form" onSubmit={handleSubmit} className="mt-4 space-y-5">
          {/* Name */}
          <div className="space-y-2">
            <Label>Token Name</Label>
            <Input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                if (nameError) setNameError('')
              }}
              placeholder="e.g., VS Code, GitHub Actions, CLI"
              disabled={isCreating}
            />
            {nameError && <p className="text-xs text-destructive">{nameError}</p>}
            <p className="text-xs text-muted-foreground">
              Give your token a descriptive name so you can identify it later.
            </p>
          </div>

          {/* Expiration */}
          <div className="space-y-2">
            <Label>Expiration</Label>
            <Select value={expiresDays} onChange={setExpiresDays} disabled={isCreating}>
              {EXPIRATION_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </Select>
          </div>

          {/* Scopes */}
          <div className="space-y-2">
            <Label>Scopes</Label>
            <p className="text-xs text-muted-foreground">
              Select the permissions this token will have.
            </p>
            <div className="space-y-4 mt-2 max-h-[400px] overflow-y-auto pr-1">
              {Array.from(new Set(AVAILABLE_SCOPES.map((s) => s.category))).map((category) => (
                <div key={category} className="space-y-2">
                  <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {category}
                  </h4>
                  <div className="space-y-1.5">
                    {AVAILABLE_SCOPES.filter((s) => s.category === category).map((scope) => (
                      <label
                        key={scope.value}
                        className={cn(
                          'flex items-start gap-3 p-2.5 rounded-lg border transition-all cursor-pointer',
                          selectedScopes.includes(scope.value)
                            ? 'border-primary/30 bg-primary/5'
                            : 'border-border/50 bg-card/30 hover:bg-card/50'
                        )}
                      >
                        <Checkbox
                          checked={selectedScopes.includes(scope.value)}
                          onChange={() => toggleScope(scope.value)}
                          disabled={isCreating}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{scope.label}</span>
                            <code className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                              {scope.value}
                            </code>
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {scope.description}
                          </p>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </form>

        <DialogFooter>
          <Button variant="outline" type="button" onClick={handleClose} disabled={isCreating}>
            Cancel
          </Button>
          <Button type="submit" form="create-token-form" loading={isCreating}>
            Create Token
          </Button>
        </DialogFooter>
        <DialogClose onClick={handleClose} />
      </DialogContent>
    </Dialog>
  )
}

/* ------------------------------------------------------------------ */
/* Token Card                                                          */
/* ------------------------------------------------------------------ */

function TokenCard({
  token,
  isExpanded,
  onToggleExpand,
  onRegenerate,
  onRevoke,
  onDelete,
  isRegenerating,
  isRevoking,
  isDeleting,
}: {
  token: ApiToken
  isExpanded: boolean
  onToggleExpand: () => void
  onRegenerate: () => void
  onRevoke: () => void
  onDelete: () => void
  isRegenerating: boolean
  isRevoking: boolean
  isDeleting: boolean
}) {
  const isBusy = isRegenerating || isRevoking || isDeleting

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 200, damping: 25 }}
      className={cn(
        'rounded-xl border overflow-hidden transition-colors',
        token.is_active
          ? 'bg-card/40 border-border/40 backdrop-blur-sm'
          : 'bg-muted/20 border-border/20 opacity-70'
      )}
    >
      {/* Card Header */}
      <div className="p-4 sm:p-5">
        <div className="flex items-start gap-4">
          {/* Icon */}
          <div
            className={cn(
              'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
              token.is_active ? 'bg-primary/10' : 'bg-muted'
            )}
          >
            <Key
              className={cn('w-5 h-5', token.is_active ? 'text-primary' : 'text-muted-foreground')}
            />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3
                className={cn(
                  'font-semibold',
                  !token.is_active && 'line-through text-muted-foreground'
                )}
              >
                {token.name}
              </h3>
              <TokenStatusBadge isActive={token.is_active} />
            </div>

            <div className="flex items-center gap-3 mt-1.5 flex-wrap text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <Activity className="w-3 h-3" />
                {token.usage_count} uses
              </span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {token.last_used_at
                  ? `Last used ${formatRelativeTime(token.last_used_at)}`
                  : 'Never used'}
              </span>
              <span className="flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                {token.expires_at
                  ? `Expires ${formatRelativeTime(token.expires_at)}`
                  : 'No expiration'}
              </span>
            </div>

            {/* Scopes */}
            <div className="flex items-center gap-1.5 mt-2.5 flex-wrap">
              {token.scopes.slice(0, 3).map((scope) => (
                <span
                  key={scope}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/60 text-[11px] font-medium text-muted-foreground"
                >
                  <Shield className="w-3 h-3" />
                  {scope}
                </span>
              ))}
              {token.scopes.length > 3 && (
                <span className="px-2 py-0.5 rounded-md bg-muted/60 text-[11px] font-medium text-muted-foreground">
                  +{token.scopes.length - 3} more
                </span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1 shrink-0">
            {token.is_active && (
              <Tooltip content="Regenerate">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onRegenerate}
                  disabled={isBusy}
                  className="w-8 h-8"
                >
                  <RefreshCw className={cn('w-4 h-4', isRegenerating && 'animate-spin')} />
                </Button>
              </Tooltip>
            )}
            {token.is_active ? (
              <Tooltip content="Revoke">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onRevoke}
                  disabled={isBusy}
                  className="w-8 h-8 text-amber-500 hover:text-amber-600 hover:bg-amber-500/10"
                >
                  <Ban className="w-4 h-4" />
                </Button>
              </Tooltip>
            ) : (
              <Tooltip content="Delete permanently">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onDelete}
                  disabled={isBusy}
                  className="w-8 h-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </Tooltip>
            )}
            <Tooltip content={isExpanded ? 'Collapse' : 'Expand'}>
              <Button variant="ghost" size="icon" onClick={onToggleExpand} className="w-8 h-8">
                {isExpanded ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </Button>
            </Tooltip>
          </div>
        </div>
      </div>

      {/* Expanded Details */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            className="overflow-hidden"
          >
            <div className="px-4 sm:px-5 pb-4 sm:pb-5 pt-0">
              <div className="border-t border-border/30 pt-4 space-y-3">
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Token Details
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                  <DetailItem icon={Tag} label="Token ID" value={token.id} />
                  <DetailItem
                    icon={Calendar}
                    label="Created"
                    value={formatDate(token.created_at)}
                  />
                  <DetailItem
                    icon={Clock}
                    label="Last Used"
                    value={token.last_used_at ? formatDate(token.last_used_at) : 'Never'}
                  />
                  <DetailItem
                    icon={Activity}
                    label="Usage Count"
                    value={`${token.usage_count} request${token.usage_count === 1 ? '' : 's'}`}
                  />
                </div>

                {/* All Scopes */}
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    All Scopes
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {token.scopes.map((scope) => (
                      <span
                        key={scope}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-primary/5 border border-primary/10 text-xs font-medium text-primary"
                      >
                        <Shield className="w-3 h-3" />
                        {scope}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Usage hint */}
                <div className="p-3 rounded-lg bg-muted/30 border border-border/20">
                  <div className="flex items-start gap-2">
                    <Terminal className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
                    <div className="text-xs text-muted-foreground space-y-1">
                      <p>Use this token with the Authorization header:</p>
                      <code className="block p-2 rounded bg-background/80 text-foreground font-mono text-[11px] break-all">
                        Authorization: Bearer {'<token>'}
                      </code>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

/* ------------------------------------------------------------------ */
/* Sub-components                                                      */
/* ------------------------------------------------------------------ */

function TokenStatusBadge({ isActive }: { isActive: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border',
        isActive
          ? 'bg-green-500/10 text-green-400 border-green-500/20'
          : 'bg-red-500/10 text-red-400 border-red-500/20'
      )}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full', isActive ? 'bg-green-400' : 'bg-red-400')} />
      {isActive ? 'Active' : 'Revoked'}
    </span>
  )
}

function DetailItem({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType
  label: string
  value: string
}) {
  return (
    <div className="flex items-start gap-2.5 p-3 rounded-lg bg-muted/30">
      <Icon className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
      <div className="min-w-0">
        <span className="text-xs text-muted-foreground block">{label}</span>
        <span className="text-sm font-medium break-all">{value}</span>
      </div>
    </div>
  )
}

function CopyButton({ text, onCopy }: { text: string; onCopy: () => void }) {
  const [copied, setCopied] = useState(false)

  const handleClick = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    onCopy()
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Button variant="ghost" size="sm" onClick={handleClick} className="h-7 px-2 gap-1 text-xs">
      {copied ? (
        <>
          <Check className="w-3.5 h-3.5 text-green-400" />
          Copied
        </>
      ) : (
        <>
          <Copy className="w-3.5 h-3.5" />
          Copy
        </>
      )}
    </Button>
  )
}

function TokenReveal({ value }: { value: string }) {
  const [revealed, setRevealed] = useState(false)

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <code
          className={cn(
            'flex-1 p-3 rounded-lg bg-background/80 border border-border/50 font-mono text-sm break-all transition-all',
            !revealed && 'blur-[4px] select-none'
          )}
        >
          {value}
        </code>
        <Tooltip content={revealed ? 'Hide' : 'Reveal'}>
          <Button
            variant="outline"
            size="icon"
            onClick={() => setRevealed(!revealed)}
            className="shrink-0"
          >
            {revealed ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </Button>
        </Tooltip>
      </div>
      {!revealed && (
        <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1">
          <Eye className="w-3 h-3" />
          Click the eye icon to reveal the token
        </p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Skeleton                                                            */
/* ------------------------------------------------------------------ */

function TokenListSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <div key={i} className="rounded-xl border border-border/40 bg-card/30 p-5 animate-pulse">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-xl bg-muted shrink-0" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-32 bg-muted rounded" />
              <div className="h-3 w-48 bg-muted rounded" />
              <div className="flex gap-2 mt-2">
                <div className="h-5 w-20 bg-muted rounded" />
                <div className="h-5 w-24 bg-muted rounded" />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
