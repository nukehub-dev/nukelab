import { createFileRoute } from '@tanstack/react-router'
import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  FolderOpen,
  Users,
  HardDrive,
  Plus,
  Trash2,
  Search,
  Activity,
  SlidersHorizontal,
  Crown,
  UserCheck,
  Clock,
  LayoutGrid,
  List,
  Pin,
} from 'lucide-react'
import {
  useWorkspaces,
  useCreateWorkspace,
  useDeleteWorkspace,
  type Workspace,
} from '../hooks/use-workspaces'
import { springs } from '../lib/animations'
import { cn } from '../lib/utils'
import { useAuthStore } from '../stores/auth-store'
import { useThemeStore } from '../stores/theme-store'
import { useWorkspacePins } from '../hooks/use-workspace-pins'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Select, SelectItem } from '../components/ui/select'
import { Textarea } from '../components/ui/textarea'
import { Card, CardContent } from '../components/ui/card'
import { SkeletonCard } from '../components/feedback/skeleton'
import { EmptyState } from '../components/feedback/empty-state'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../components/ui/dialog'
import { useConfirmDialog } from '../components/ui/confirm-dialog'
import { Tooltip } from '../components/ui/tooltip'
import { Link } from '@tanstack/react-router'

export const Route = createFileRoute('/workspaces/')({
  component: WorkspacesListPage,
})

function formatDate(dateString?: string) {
  if (!dateString) return ''
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

// Workspace Card Component
function WorkspaceCard({
  workspace,
  index,
  onDelete,
  isPinned,
  onTogglePin,
}: {
  workspace: Workspace
  index: number
  onDelete?: () => void
  isPinned?: boolean
  onTogglePin?: () => void
}) {
  const { density } = useThemeStore()
  const compact = density === 'compact'
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, ...springs.gentle }}
    >
      <Link to="/workspaces/$workspaceId" params={{ workspaceId: workspace.id }}>
        <Card
          variant="bubble"
          interactive
          className={cn('overflow-hidden group', isPinned && 'ring-1 ring-primary/30')}
        >
          <CardContent className={compact ? 'p-3' : 'p-5'}>
            {/* Header */}
            <div className="flex items-start justify-between mb-4 gap-2">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="p-2 rounded-xl bg-primary/10 shrink-0">
                  <FolderOpen className="w-4 h-4 text-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-sm truncate">{workspace.name}</h3>
                    {!workspace.is_active && (
                      <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-muted text-muted-foreground">
                        Inactive
                      </span>
                    )}
                    {workspace.has_pending_invitation && (
                      <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/20">
                        Pending
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 truncate">
                    {workspace.description || (
                      <span className="italic opacity-60">No description</span>
                    )}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-1 shrink-0">
                {onTogglePin && (
                  <Tooltip content={isPinned ? 'Unpin workspace' : 'Pin workspace'}>
                    <button
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        onTogglePin()
                      }}
                      className={cn(
                        'p-1.5 rounded-lg transition-colors',
                        isPinned
                          ? 'text-primary hover:text-primary/80'
                          : 'text-muted-foreground hover:text-primary'
                      )}
                    >
                      <Pin className={cn('w-3.5 h-3.5', isPinned && 'fill-primary')} />
                    </button>
                  </Tooltip>
                )}
                {onDelete && (
                  <Tooltip content="Delete workspace">
                    <button
                      onClick={(e) => {
                        e.preventDefault()
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

            {/* Stats */}
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <div className="flex items-center gap-1.5">
                <Users className="w-3 h-3 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">
                  {workspace.member_count || 0} members
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <HardDrive className="w-3 h-3 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">
                  {workspace.volume_count || 0} volumes
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">
                  {formatDate(workspace.created_at)}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </Link>
    </motion.div>
  )
}

// Workspace List Row Component
function WorkspaceListRow({
  workspace,
  index,
  onDelete,
  isPinned,
  onTogglePin,
}: {
  workspace: Workspace
  index: number
  onDelete?: () => void
  isPinned?: boolean
  onTogglePin?: () => void
}) {
  const { density } = useThemeStore()
  const compact = density === 'compact'
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.03, ...springs.gentle }}
    >
      <Link to="/workspaces/$workspaceId" params={{ workspaceId: workspace.id }}>
        <Card
          variant="bubble"
          interactive
          className={cn('overflow-hidden group', isPinned && 'ring-1 ring-primary/30')}
        >
          <CardContent className={compact ? 'p-2.5' : 'p-4'}>
            <div className="flex items-center gap-4">
              <div className="p-2 rounded-xl bg-primary/10 shrink-0">
                <FolderOpen className="w-4 h-4 text-primary" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-sm truncate">{workspace.name}</h3>
                  {!workspace.is_active && (
                    <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-muted text-muted-foreground">
                      Inactive
                    </span>
                  )}
                  {workspace.has_pending_invitation && (
                    <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      Pending
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 truncate">
                  {workspace.description || (
                    <span className="italic opacity-60">No description</span>
                  )}
                </p>
              </div>
              <div className="hidden sm:flex items-center gap-4 text-xs text-muted-foreground shrink-0">
                <div className="flex items-center gap-1">
                  <Users className="w-3 h-3" />
                  {workspace.member_count || 0}
                </div>
                <div className="flex items-center gap-1">
                  <HardDrive className="w-3 h-3" />
                  {workspace.volume_count || 0}
                </div>
                <span>{formatDate(workspace.created_at)}</span>
              </div>
              {onTogglePin && (
                <Tooltip content={isPinned ? 'Unpin workspace' : 'Pin workspace'}>
                  <button
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      onTogglePin()
                    }}
                    className={cn(
                      'p-1.5 rounded-lg transition-colors shrink-0',
                      isPinned
                        ? 'text-primary hover:text-primary/80'
                        : 'text-muted-foreground hover:text-primary'
                    )}
                  >
                    <Pin className={cn('w-3.5 h-3.5', isPinned && 'fill-primary')} />
                  </button>
                </Tooltip>
              )}
              {onDelete && (
                <Tooltip content="Delete workspace">
                  <button
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      onDelete()
                    }}
                    className="p-1.5 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </Tooltip>
              )}
            </div>
          </CardContent>
        </Card>
      </Link>
    </motion.div>
  )
}

type FilterTab = 'all' | 'owned' | 'member' | 'pending'
type SortOption = 'name_asc' | 'name_desc' | 'newest' | 'oldest' | 'members'

function WorkspacesListPage() {
  const currentUser = useAuthStore((state) => state.user)
  const { data: workspaces = [], isLoading } = useWorkspaces()
  const createWorkspace = useCreateWorkspace()
  const deleteWorkspace = useDeleteWorkspace()
  const { confirm, dialog } = useConfirmDialog()
  const { isPinned, togglePin } = useWorkspacePins()

  const [searchQuery, setSearchQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState<FilterTab>('all')
  const [sortBy, setSortBy] = useState<SortOption>('newest')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newWorkspace, setNewWorkspace] = useState({
    name: '',
    description: '',
  })

  const filteredWorkspaces = useMemo(() => {
    let result = workspaces

    // Search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      result = result.filter(
        (w) => w.name.toLowerCase().includes(query) || w.description?.toLowerCase().includes(query)
      )
    }

    // Category filter
    if (activeFilter === 'owned') {
      result = result.filter((w) => w.owner_id === currentUser?.id)
    } else if (activeFilter === 'member') {
      result = result.filter((w) => w.owner_id !== currentUser?.id && !w.has_pending_invitation)
    } else if (activeFilter === 'pending') {
      result = result.filter((w) => w.has_pending_invitation)
    }

    // Sort by user selection, then pin status
    result = [...result].sort((a, b) => {
      // Pin status always takes priority
      const aPinned = isPinned(a.id) ? 1 : 0
      const bPinned = isPinned(b.id) ? 1 : 0
      if (aPinned !== bPinned) return bPinned - aPinned

      switch (sortBy) {
        case 'name_asc':
          return a.name.localeCompare(b.name)
        case 'name_desc':
          return b.name.localeCompare(a.name)
        case 'newest':
          return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
        case 'oldest':
          return new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime()
        case 'members':
          return (b.member_count || 0) - (a.member_count || 0)
        default:
          return 0
      }
    })

    return result
  }, [workspaces, searchQuery, activeFilter, sortBy, isPinned, currentUser?.id])

  const filterCounts = useMemo(
    () => ({
      all: workspaces.length,
      owned: workspaces.filter((w) => w.owner_id === currentUser?.id).length,
      member: workspaces.filter((w) => w.owner_id !== currentUser?.id && !w.has_pending_invitation)
        .length,
      pending: workspaces.filter((w) => w.has_pending_invitation).length,
    }),
    [workspaces, currentUser?.id]
  )

  const stats = useMemo(() => {
    const totalWorkspaces = workspaces.length
    const activeWorkspaces = workspaces.filter((w) => w.is_active).length
    const totalMembers = workspaces.reduce((acc, w) => acc + (w.member_count || 0), 0)
    const totalVolumes = workspaces.reduce((acc, w) => acc + (w.volume_count || 0), 0)

    return { totalWorkspaces, activeWorkspaces, totalMembers, totalVolumes }
  }, [workspaces])

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    createWorkspace.mutate(newWorkspace, {
      onSuccess: () => {
        setShowCreateDialog(false)
        setNewWorkspace({ name: '', description: '' })
      },
    })
  }

  const handleDelete = async (workspace: Workspace) => {
    const confirmed = await confirm({
      title: 'Delete Workspace',
      description: `Are you sure you want to delete "${workspace.name}"? This action cannot be undone.`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
      variant: 'danger',
    })
    if (confirmed) {
      deleteWorkspace.mutate(workspace.id)
    }
  }

  const statCards = isLoading
    ? [
        {
          title: 'Total Workspaces',
          value: '...',
          icon: FolderOpen,
          iconColor: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
        },
        {
          title: 'Active',
          value: '...',
          icon: Activity,
          iconColor: 'text-emerald-400',
          bgColor: 'bg-emerald-500/10',
        },
        {
          title: 'Total Members',
          value: '...',
          icon: Users,
          iconColor: 'text-violet-400',
          bgColor: 'bg-violet-500/10',
        },
        {
          title: 'Total Volumes',
          value: '...',
          icon: HardDrive,
          iconColor: 'text-amber-400',
          bgColor: 'bg-amber-500/10',
        },
      ]
    : [
        {
          title: 'Total Workspaces',
          value: stats.totalWorkspaces,
          icon: FolderOpen,
          iconColor: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
        },
        {
          title: 'Active',
          value: stats.activeWorkspaces,
          icon: Activity,
          iconColor: 'text-emerald-400',
          bgColor: 'bg-emerald-500/10',
        },
        {
          title: 'Total Members',
          value: stats.totalMembers,
          icon: Users,
          iconColor: 'text-violet-400',
          bgColor: 'bg-violet-500/10',
        },
        {
          title: 'Total Volumes',
          value: stats.totalVolumes,
          icon: HardDrive,
          iconColor: 'text-amber-400',
          bgColor: 'bg-amber-500/10',
        },
      ]

  return (
    <>
      <ResourcePageLayout
        title="Workspaces"
        subtitle="Manage collaborative environments and shared volumes"
        icon={FolderOpen}
        stats={statCards}
        actions={[
          {
            action: 'create',
            onClick: () => setShowCreateDialog(true),
            loading: createWorkspace.isPending,
          },
        ]}
      >
        {/* Filter & Search Toolbar */}
        {!isLoading && workspaces.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springs.gentle}
            className="flex flex-col gap-4"
          >
            {/* Search + Sort Row */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none z-10" />
                <Input
                  placeholder="Search workspaces..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 bg-muted/50 rounded-lg p-1">
                  <button
                    onClick={() => setViewMode('grid')}
                    className={cn(
                      'p-1.5 rounded-md transition-colors',
                      viewMode === 'grid'
                        ? 'bg-surface shadow-sm text-foreground'
                        : 'text-muted-foreground hover:text-foreground'
                    )}
                  >
                    <LayoutGrid className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setViewMode('list')}
                    className={cn(
                      'p-1.5 rounded-md transition-colors',
                      viewMode === 'list'
                        ? 'bg-surface shadow-sm text-foreground'
                        : 'text-muted-foreground hover:text-foreground'
                    )}
                  >
                    <List className="w-4 h-4" />
                  </button>
                </div>
                <div className="w-40">
                  <Select
                    value={sortBy}
                    onChange={(value) => setSortBy(value as SortOption)}
                    placeholder="Sort by..."
                  >
                    <SelectItem value="newest">Newest First</SelectItem>
                    <SelectItem value="oldest">Oldest First</SelectItem>
                    <SelectItem value="name_asc">Name A-Z</SelectItem>
                    <SelectItem value="name_desc">Name Z-A</SelectItem>
                    <SelectItem value="members">Most Members</SelectItem>
                  </Select>
                </div>
              </div>
            </div>

            {/* Filter Tabs */}
            <div className="flex items-center gap-2 flex-wrap">
              {[
                {
                  key: 'all' as FilterTab,
                  label: 'All',
                  icon: SlidersHorizontal,
                  count: filterCounts.all,
                },
                {
                  key: 'owned' as FilterTab,
                  label: 'Owned',
                  icon: Crown,
                  count: filterCounts.owned,
                },
                {
                  key: 'member' as FilterTab,
                  label: 'Member',
                  icon: UserCheck,
                  count: filterCounts.member,
                },
                {
                  key: 'pending' as FilterTab,
                  label: 'Pending',
                  icon: Clock,
                  count: filterCounts.pending,
                },
              ].map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveFilter(tab.key)}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors border',
                    activeFilter === tab.key
                      ? 'bg-primary/10 border-primary/30 text-primary'
                      : 'bg-muted/50 border-border/50 text-muted-foreground hover:text-foreground hover:bg-muted'
                  )}
                >
                  <tab.icon className="w-3.5 h-3.5" />
                  {tab.label}
                  <span
                    className={cn(
                      'ml-0.5 px-1.5 py-0.5 rounded-full text-[10px]',
                      activeFilter === tab.key ? 'bg-primary/20' : 'bg-muted'
                    )}
                  >
                    {tab.count}
                  </span>
                </button>
              ))}
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
        ) : workspaces.length === 0 ? (
          <EmptyState
            icon={FolderOpen}
            title="No Workspaces"
            description="Create your first workspace to start collaborating with your team on shared volumes."
            action={{
              label: 'Create Workspace',
              onClick: () => setShowCreateDialog(true),
              icon: Plus,
            }}
          />
        ) : filteredWorkspaces.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-12"
          >
            <p className="text-muted-foreground">
              {activeFilter !== 'all'
                ? `No ${activeFilter} workspaces.`
                : searchQuery.trim()
                  ? 'No workspaces match your search.'
                  : 'No workspaces found.'}
            </p>
            <div className="flex items-center justify-center gap-2 mt-2">
              {searchQuery.trim() && (
                <Button variant="outline" size="sm" onClick={() => setSearchQuery('')}>
                  Clear Search
                </Button>
              )}
              {activeFilter !== 'all' && (
                <Button variant="outline" size="sm" onClick={() => setActiveFilter('all')}>
                  Clear Filter
                </Button>
              )}
            </div>
          </motion.div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
            <AnimatePresence mode="popLayout">
              {filteredWorkspaces.map((workspace, index) => (
                <WorkspaceCard
                  key={workspace.id}
                  workspace={workspace}
                  index={index}
                  onDelete={() => handleDelete(workspace)}
                  isPinned={isPinned(workspace.id)}
                  onTogglePin={() => togglePin(workspace.id)}
                />
              ))}
            </AnimatePresence>
          </div>
        ) : (
          <div className="space-y-2">
            <AnimatePresence mode="popLayout">
              {filteredWorkspaces.map((workspace, index) => (
                <WorkspaceListRow
                  key={workspace.id}
                  workspace={workspace}
                  index={index}
                  onDelete={() => handleDelete(workspace)}
                  isPinned={isPinned(workspace.id)}
                  onTogglePin={() => togglePin(workspace.id)}
                />
              ))}
            </AnimatePresence>
          </div>
        )}
      </ResourcePageLayout>

      {/* Create Dialog */}
      {showCreateDialog && (
        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Workspace</DialogTitle>
              <DialogDescription>
                Create a new workspace for collaborative development.
              </DialogDescription>
            </DialogHeader>

            <form onSubmit={handleCreate} className="space-y-4 mt-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Name</label>
                <Input
                  value={newWorkspace.name}
                  onChange={(e) => setNewWorkspace({ ...newWorkspace, name: e.target.value })}
                  placeholder="My Workspace"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Textarea
                  value={newWorkspace.description}
                  onChange={(e) =>
                    setNewWorkspace({ ...newWorkspace, description: e.target.value })
                  }
                  placeholder="Optional description"
                  rows={3}
                />
              </div>

              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setShowCreateDialog(false)}>
                  Cancel
                </Button>
                <Button type="submit" loading={createWorkspace.isPending}>
                  Create Workspace
                </Button>
              </DialogFooter>
            </form>
            <DialogClose onClick={() => setShowCreateDialog(false)} />
          </DialogContent>
        </Dialog>
      )}

      {dialog}
    </>
  )
}
