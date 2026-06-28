import { createFileRoute } from '@tanstack/react-router'
import {
  HardDrive,
  Database,
  Layers,
  Zap,
  Server,
  Trash2,
  Plus,
  FolderOpen,
  Search,
  Pencil,
  User,
  Users,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useState, useMemo } from 'react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { useVolumes, useCreateVolume, useDeleteVolume, useUpdateVolume } from '../hooks/use-volumes'
import { useCurrentUser } from '../hooks/use-current-user'
import { useThemeStore } from '../stores/theme-store'
import { FileBrowser } from '../components/volume-file-browser'
import { SkeletonCard } from '../components/feedback/skeleton'
import { EmptyState } from '../components/feedback/empty-state'
import { Card, CardContent } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { Select, SelectItem } from '../components/ui/select'
import { Textarea } from '../components/ui/textarea'
import { Slider } from '../components/ui/slider'
import { Button } from '../components/ui/button'
import { Tooltip } from '../components/ui/tooltip'
import { useConfirmDialog } from '../components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../components/ui/dialog'
import { formatBytes } from '../lib/utils'
import { springs } from '../lib/animations'
import { cn } from '../lib/utils'
import type { Volume } from '../hooks/use-volumes'

export const Route = createFileRoute('/volumes')({
  component: VolumesPage,
})

// Volume Card Component
function VolumeCard({
  volume,
  index,
  onDelete,
  onBrowse,
  onEdit,
  isOwner,
}: {
  volume: Volume
  index: number
  onDelete?: () => void
  onBrowse?: () => void
  onEdit?: () => void
  isOwner: boolean
}) {
  const { density } = useThemeStore()
  const compact = density === 'compact'
  const sizePercent =
    volume.size_bytes > 0 && volume.max_size_bytes && volume.max_size_bytes > 0
      ? (volume.size_bytes / volume.max_size_bytes) * 100
      : 0
  const isLarge = sizePercent > 80
  const isOverLimit = volume.status === 'over_limit'

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, ...springs.gentle }}
    >
      <Card variant="bubble" interactive className="overflow-hidden">
        <CardContent className={compact ? 'p-3' : 'p-5'}>
          {/* Header */}
          <div className="flex items-start justify-between mb-4 gap-2">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <div
                className={cn(
                  'p-2 rounded-xl shrink-0',
                  isOverLimit ? 'bg-red-500/10' : isLarge ? 'bg-amber-500/10' : 'bg-primary/10'
                )}
              >
                <HardDrive
                  className={cn(
                    'w-4 h-4',
                    isOverLimit ? 'text-red-400' : isLarge ? 'text-amber-400' : 'text-primary'
                  )}
                />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-sm truncate">{volume.display_name}</h3>
                <span className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                  <Server className="w-3 h-3" />
                  {volume.server_count} {volume.server_count === 1 ? 'server' : 'servers'}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {isOwner ? (
                <span className="shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-primary/10 text-primary">
                  <User className="w-3 h-3" />
                  Owner
                </span>
              ) : (
                <span className="shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-muted/50 text-muted-foreground">
                  <Users className="w-3 h-3" />
                  Shared
                </span>
              )}
              {volume.visibility !== 'private' && (
                <span
                  className={cn(
                    'shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider',
                    volume.visibility === 'public'
                      ? 'bg-emerald-500/10 text-emerald-400'
                      : 'bg-muted/50 text-muted-foreground'
                  )}
                >
                  {volume.visibility}
                </span>
              )}
              {onBrowse && (
                <Tooltip content="Browse files">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onBrowse()
                    }}
                    className="p-1.5 rounded-lg hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                  >
                    <FolderOpen className="w-3.5 h-3.5" />
                  </button>
                </Tooltip>
              )}
              {onEdit && isOwner && (
                <Tooltip content="Edit volume">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onEdit()
                    }}
                    className="p-1.5 rounded-lg hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                </Tooltip>
              )}
              {onDelete && isOwner && volume.server_count === 0 && (
                <Tooltip content="Delete volume">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete()
                    }}
                    className="p-1.5 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </Tooltip>
              )}
            </div>
          </div>

          {/* Size visualization */}
          {volume.size_bytes > 0 ? (
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-muted-foreground">Storage Used</span>
                <span
                  className={cn(
                    'text-xs font-medium',
                    isOverLimit ? 'text-red-400' : isLarge ? 'text-amber-400' : 'text-emerald-400'
                  )}
                >
                  {formatBytes(volume.size_bytes)}
                  {volume.max_size_bytes && (
                    <span className="text-muted-foreground ml-1">
                      / {formatBytes(volume.max_size_bytes)}
                    </span>
                  )}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <motion.div
                  className={cn(
                    'h-full rounded-full',
                    isOverLimit ? 'bg-red-500' : isLarge ? 'bg-amber-500' : 'bg-emerald-500'
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(sizePercent, 100)}%` }}
                  transition={{ duration: 1, ease: 'easeOut', delay: index * 0.05 }}
                />
              </div>
            </div>
          ) : (
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-muted-foreground">Storage Used</span>
                <span className="text-xs text-muted-foreground">0 B</span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div className="h-full rounded-full bg-muted w-0" />
              </div>
            </div>
          )}

          {/* ID, Status & Date */}
          <div className="flex items-center justify-between text-xs gap-2">
            <div className="flex items-center gap-2 min-w-0">
              {volume.status !== 'active' && (
                <span
                  className={cn(
                    'px-2 py-0.5 rounded-full shrink-0',
                    volume.status === 'over_limit'
                      ? 'bg-red-500/10 text-red-400'
                      : volume.status === 'archived'
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'bg-muted/50 text-muted-foreground'
                  )}
                >
                  {volume.status}
                </span>
              )}
              <code className="text-[10px] text-muted-foreground truncate">{volume.id}</code>
            </div>
            {volume.created_at && (
              <span className="text-muted-foreground shrink-0">
                {new Date(volume.created_at).toLocaleDateString(undefined, {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })}
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  )
}

type OwnershipFilter = 'all' | 'mine' | 'shared'
type SortOption = 'name' | 'size' | 'created' | 'updated'

function VolumesPage() {
  const { data: volumes = [], isLoading } = useVolumes()
  const { data: currentUser } = useCurrentUser()
  const createVolume = useCreateVolume()
  const deleteVolume = useDeleteVolume()
  const updateVolume = useUpdateVolume()
  const { confirm, dialog } = useConfirmDialog()
  const [searchQuery, setSearchQuery] = useState('')
  const [ownershipFilter, setOwnershipFilter] = useState<OwnershipFilter>('all')
  const [sortBy, setSortBy] = useState<SortOption>('created')
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [createForm, setCreateForm] = useState({
    display_name: '',
    description: '',
    max_size_gb: 10,
  })
  const [editForm, setEditForm] = useState({
    id: '',
    display_name: '',
    description: '',
    max_size_gb: 10,
    current_size_bytes: 0,
  })
  const [createError, setCreateError] = useState<string | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [browsingVolume, setBrowsingVolume] = useState<{ id: string; name: string } | null>(null)

  // Calculate stats
  const stats = useMemo(() => {
    const totalSize = volumes.reduce((acc, v) => acc + (v.size_bytes || 0), 0)
    const avgSize = volumes.length > 0 ? totalSize / volumes.length : 0
    const largestVolume = volumes.reduce(
      (max, v) => ((v.size_bytes || 0) > (max?.size_bytes || 0) ? v : max),
      volumes[0]
    )

    return {
      totalVolumes: volumes.length,
      totalSize,
      avgSize,
      largestVolume: largestVolume?.size_bytes || 0,
    }
  }, [volumes])

  // Filter & sort volumes
  const filteredVolumes = useMemo(() => {
    let result = [...volumes]

    // Ownership filter
    if (ownershipFilter !== 'all' && currentUser) {
      const userId = currentUser.id
      result = result.filter((v) =>
        ownershipFilter === 'mine' ? v.owner_id === userId : v.owner_id !== userId
      )
    }

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      result = result.filter(
        (v) =>
          v.display_name.toLowerCase().includes(query) ||
          v.name.toLowerCase().includes(query) ||
          v.status.toLowerCase().includes(query)
      )
    }

    // Sort
    result.sort((a, b) => {
      switch (sortBy) {
        case 'name':
          return a.display_name.localeCompare(b.display_name)
        case 'size':
          return (b.size_bytes || 0) - (a.size_bytes || 0)
        case 'created':
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        case 'updated':
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        default:
          return 0
      }
    })

    return result
  }, [volumes, searchQuery, ownershipFilter, sortBy, currentUser])

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    setCreateError(null)
    if (!createForm.display_name.trim()) return

    const max_size_bytes = createForm.max_size_gb * 1024 * 1024 * 1024

    createVolume.mutate(
      {
        display_name: createForm.display_name,
        description: createForm.description || undefined,
        max_size_bytes: max_size_bytes > 0 ? max_size_bytes : undefined,
      },
      {
        onSuccess: () => {
          setShowCreateDialog(false)
          setCreateForm({ display_name: '', description: '', max_size_gb: 10 })
        },
      }
    )
  }

  const handleEdit = (volume: Volume) => {
    setEditForm({
      id: volume.id,
      display_name: volume.display_name,
      description: volume.description || '',
      max_size_gb: volume.max_size_bytes
        ? Math.round(volume.max_size_bytes / (1024 * 1024 * 1024))
        : 10,
      current_size_bytes: volume.size_bytes || 0,
    })
    setEditError(null)
    setShowEditDialog(true)
  }

  const handleUpdate = (e: React.FormEvent) => {
    e.preventDefault()
    setEditError(null)
    if (!editForm.display_name.trim()) return

    const max_size_bytes = editForm.max_size_gb * 1024 * 1024 * 1024

    // Validate: cannot set limit below current size
    if (max_size_bytes > 0 && max_size_bytes < editForm.current_size_bytes) {
      setEditError(
        `Cannot set limit below current volume size (${formatBytes(editForm.current_size_bytes)}).`
      )
      return
    }

    updateVolume.mutate(
      {
        volumeId: editForm.id,
        data: {
          display_name: editForm.display_name,
          description: editForm.description || undefined,
          max_size_bytes: max_size_bytes > 0 ? max_size_bytes : undefined,
        },
      },
      {
        onSuccess: () => {
          setShowEditDialog(false)
          setEditForm({
            id: '',
            display_name: '',
            description: '',
            max_size_gb: 10,
            current_size_bytes: 0,
          })
        },
      }
    )
  }

  const handleDelete = async (volume: Volume) => {
    const confirmed = await confirm({
      title: 'Delete Volume',
      description: `Are you sure you want to delete "${volume.display_name}"? This action cannot be undone.`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
      variant: 'danger',
    })
    if (confirmed) {
      deleteVolume.mutate(volume.id)
    }
  }

  const statCards = isLoading
    ? [
        {
          title: 'Total Volumes',
          value: '...',
          icon: HardDrive,
          iconColor: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
        },
        {
          title: 'Total Size',
          value: '...',
          icon: Database,
          iconColor: 'text-amber-400',
          bgColor: 'bg-amber-500/10',
        },
        {
          title: 'Average Size',
          value: '...',
          icon: Layers,
          iconColor: 'text-violet-400',
          bgColor: 'bg-violet-500/10',
        },
        {
          title: 'Largest Volume',
          value: '...',
          icon: Zap,
          iconColor: 'text-emerald-400',
          bgColor: 'bg-emerald-500/10',
        },
      ]
    : [
        {
          title: 'Total Volumes',
          value: stats.totalVolumes,
          icon: HardDrive,
          iconColor: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
        },
        {
          title: 'Total Size',
          value: formatBytes(stats.totalSize),
          icon: Database,
          iconColor: 'text-amber-400',
          bgColor: 'bg-amber-500/10',
        },
        {
          title: 'Average Size',
          value: formatBytes(stats.avgSize),
          icon: Layers,
          iconColor: 'text-violet-400',
          bgColor: 'bg-violet-500/10',
        },
        {
          title: 'Largest Volume',
          value: formatBytes(stats.largestVolume),
          icon: Zap,
          iconColor: 'text-emerald-400',
          bgColor: 'bg-emerald-500/10',
        },
      ]

  return (
    <>
      <ResourcePageLayout
        title="Volumes"
        subtitle="Manage storage volumes"
        icon={HardDrive}
        stats={statCards}
        actions={[
          {
            action: 'create',
            onClick: () => setShowCreateDialog(true),
            loading: createVolume.isPending,
          },
        ]}
      >
        {/* Toolbar: Search + Filters + Sort */}
        {!isLoading && volumes.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springs.gentle}
            className="flex flex-col lg:flex-row items-start lg:items-center gap-3"
          >
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none z-10" />
              <Input
                placeholder="Search volumes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {/* Ownership filter pills */}
              <div className="flex items-center bg-input/80 border border-input/50 rounded-lg p-0.5">
                {(['all', 'mine', 'shared'] as OwnershipFilter[]).map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setOwnershipFilter(filter)}
                    className={cn(
                      'px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                      ownershipFilter === filter
                        ? 'bg-background text-foreground shadow-sm'
                        : 'text-muted-foreground hover:text-foreground'
                    )}
                  >
                    {filter === 'all' && `All (${volumes.length})`}
                    {filter === 'mine' &&
                      `Mine (${volumes.filter((v) => v.owner_id === currentUser?.id).length})`}
                    {filter === 'shared' &&
                      `Shared (${volumes.filter((v) => v.owner_id !== currentUser?.id).length})`}
                  </button>
                ))}
              </div>

              {/* Sort dropdown */}
              <Select
                value={sortBy}
                onChange={(value) => setSortBy(value as SortOption)}
                className="w-36"
              >
                <SelectItem value="created">Newest</SelectItem>
                <SelectItem value="updated">Recently Updated</SelectItem>
                <SelectItem value="name">Name</SelectItem>
                <SelectItem value="size">Size</SelectItem>
              </Select>
            </div>
          </motion.div>
        )}

        {/* Content */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} rows={4} />
            ))}
          </div>
        ) : volumes.length === 0 ? (
          <EmptyState
            icon={HardDrive}
            title="No Volumes"
            description="No volumes found. Create one to get started."
            action={{
              label: 'Create Volume',
              onClick: () => setShowCreateDialog(true),
              icon: Plus,
            }}
          />
        ) : filteredVolumes.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-12"
          >
            <p className="text-muted-foreground">
              {searchQuery || ownershipFilter !== 'all'
                ? 'No volumes match your filters.'
                : 'No volumes found.'}
            </p>
            {(searchQuery || ownershipFilter !== 'all') && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setSearchQuery('')
                  setOwnershipFilter('all')
                }}
                className="mt-2"
              >
                Clear Filters
              </Button>
            )}
          </motion.div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
            <AnimatePresence mode="popLayout">
              {filteredVolumes.map((volume, index) => (
                <VolumeCard
                  key={volume.id}
                  volume={volume}
                  index={index}
                  isOwner={volume.owner_id === currentUser?.id}
                  onDelete={() => handleDelete(volume)}
                  onBrowse={() => setBrowsingVolume({ id: volume.id, name: volume.display_name })}
                  onEdit={() => handleEdit(volume)}
                />
              ))}
            </AnimatePresence>
          </div>
        )}

        {/* File Browser Dialog */}
        <FileBrowser
          open={!!browsingVolume}
          volumeId={browsingVolume?.id || ''}
          volumeName={browsingVolume?.name || ''}
          onClose={() => setBrowsingVolume(null)}
        />
      </ResourcePageLayout>

      {/* Create Volume Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Volume</DialogTitle>
            <DialogDescription>Create a new storage volume.</DialogDescription>
          </DialogHeader>
          <form id="create-volume-form" onSubmit={handleCreate} className="space-y-4 mt-4">
            {createError && (
              <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-sm text-destructive">
                {createError}
              </div>
            )}
            <div className="space-y-2">
              <Label>Display Name *</Label>
              <Input
                value={createForm.display_name}
                onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
                placeholder="My Project Data"
              />
            </div>
            <div className="space-y-3">
              <Label>Size Limit</Label>
              <div className="flex items-center gap-3">
                <Slider
                  min={1}
                  max={500}
                  step={1}
                  value={createForm.max_size_gb}
                  onChange={(value) => setCreateForm({ ...createForm, max_size_gb: value })}
                />
                <Input
                  type="number"
                  min={1}
                  max={500}
                  value={createForm.max_size_gb}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10)
                    setCreateForm({
                      ...createForm,
                      max_size_gb: isNaN(val) ? 1 : Math.max(1, Math.min(500, val)),
                    })
                  }}
                  className="w-20 text-center"
                />
                <span className="text-sm text-muted-foreground w-8">GB</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Maximum capacity for this volume. You can change this later.
              </p>
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                value={createForm.description}
                onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                placeholder="Optional description"
                rows={3}
              />
            </div>
          </form>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => setShowCreateDialog(false)}>
              Cancel
            </Button>
            <Button type="submit" form="create-volume-form" loading={createVolume.isPending}>
              Create
            </Button>
          </DialogFooter>
          <DialogClose onClick={() => setShowCreateDialog(false)} />
        </DialogContent>
      </Dialog>

      {/* Edit Volume Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Volume</DialogTitle>
            <DialogDescription>Update volume details.</DialogDescription>
          </DialogHeader>
          <form id="edit-volume-form" onSubmit={handleUpdate} className="space-y-4 mt-4">
            {editError && (
              <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-sm text-destructive">
                {editError}
              </div>
            )}
            <div className="space-y-2">
              <Label>Display Name *</Label>
              <Input
                value={editForm.display_name}
                onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })}
                placeholder="My Project Data"
              />
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label>Size Limit</Label>
                <span className="text-xs text-muted-foreground">
                  Current: {formatBytes(editForm.current_size_bytes)}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Slider
                  min={Math.max(1, Math.ceil(editForm.current_size_bytes / (1024 * 1024 * 1024)))}
                  max={500}
                  step={1}
                  value={Math.max(1, editForm.max_size_gb)}
                  onChange={(value) => setEditForm({ ...editForm, max_size_gb: value })}
                />
                <Input
                  type="number"
                  min={Math.max(1, Math.ceil(editForm.current_size_bytes / (1024 * 1024 * 1024)))}
                  max={500}
                  value={editForm.max_size_gb}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10)
                    setEditForm({
                      ...editForm,
                      max_size_gb: isNaN(val) ? 1 : Math.max(1, Math.min(500, val)),
                    })
                  }}
                  className="w-20 text-center"
                />
                <span className="text-sm text-muted-foreground w-8">GB</span>
              </div>
              {editForm.current_size_bytes > 0 && (
                <p className="text-xs text-muted-foreground">
                  Cannot set limit below current volume size (
                  {formatBytes(editForm.current_size_bytes)}).
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                placeholder="Optional description"
                rows={3}
              />
            </div>
          </form>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => setShowEditDialog(false)}>
              Cancel
            </Button>
            <Button type="submit" form="edit-volume-form" loading={updateVolume.isPending}>
              Save Changes
            </Button>
          </DialogFooter>
          <DialogClose onClick={() => setShowEditDialog(false)} />
        </DialogContent>
      </Dialog>

      {/* Confirmation Dialog */}
      {dialog}
    </>
  )
}
