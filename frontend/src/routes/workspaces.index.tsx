import { createFileRoute } from '@tanstack/react-router';
import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FolderOpen,
  Users,
  HardDrive,
  Plus,
  Trash2,
  Search,
  Activity,
} from 'lucide-react';
import {
  useWorkspaces,
  useCreateWorkspace,
  useDeleteWorkspace,
} from '../hooks/use-workspaces';
import { springs } from '../lib/animations';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Card, CardContent } from '../components/ui/card';
import { SkeletonCard } from '../components/feedback/skeleton';
import { EmptyState } from '../components/feedback/empty-state';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../components/ui/dialog';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { Tooltip } from '../components/ui/tooltip';
import { Link } from '@tanstack/react-router';

export const Route = createFileRoute('/workspaces/')({
  component: WorkspacesListPage,
});

function formatDate(dateString?: string) {
  if (!dateString) return '';
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', { 
    month: 'short', 
    day: 'numeric', 
    year: 'numeric' 
  });
}

// Workspace Card Component
function WorkspaceCard({ 
  workspace, 
  index, 
  onDelete 
}: { 
  workspace: any; 
  index: number; 
  onDelete?: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, ...springs.gentle }}
    >
      <Link
        to="/workspaces/$workspaceId"
        params={{ workspaceId: workspace.id }}
      >
        <Card variant="bubble" interactive className="overflow-hidden group">
          <CardContent className="p-5">
            {/* Header */}
            <div className="flex items-start justify-between mb-4 gap-2">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="p-2 rounded-xl bg-primary/10 shrink-0">
                  <FolderOpen className="w-4 h-4 text-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-sm truncate">
                      {workspace.name}
                    </h3>
                    {!workspace.is_active && (
                      <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-muted text-muted-foreground">
                        Inactive
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 truncate">
                    {workspace.description || <span className="italic opacity-60">No description</span>}
                  </p>
                </div>
              </div>
              
              <div className="flex items-center gap-1 shrink-0">
                {onDelete && (
                  <Tooltip content="Delete workspace">
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        onDelete();
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
            <div className="grid grid-cols-3 gap-2">
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
              <div className="flex items-center gap-1.5 justify-end">
                <span className="text-xs text-muted-foreground">
                  {formatDate(workspace.created_at)}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </Link>
    </motion.div>
  );
}

function WorkspacesListPage() {
  const { data: workspaces = [], isLoading } = useWorkspaces();
  const createWorkspace = useCreateWorkspace();
  const deleteWorkspace = useDeleteWorkspace();
  const { confirm, dialog } = useConfirmDialog();

  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newWorkspace, setNewWorkspace] = useState({
    name: '',
    description: '',
  });

  const filteredWorkspaces = useMemo(() => {
    if (!searchQuery.trim()) return workspaces;
    const query = searchQuery.toLowerCase();
    return workspaces.filter(
      (w) =>
        w.name.toLowerCase().includes(query) ||
        w.description?.toLowerCase().includes(query)
    );
  }, [workspaces, searchQuery]);

  const stats = useMemo(() => {
    const totalWorkspaces = workspaces.length;
    const activeWorkspaces = workspaces.filter((w) => w.is_active).length;
    const totalMembers = workspaces.reduce((acc, w) => acc + (w.member_count || 0), 0);
    const totalVolumes = workspaces.reduce((acc, w) => acc + (w.volume_count || 0), 0);

    return { totalWorkspaces, activeWorkspaces, totalMembers, totalVolumes };
  }, [workspaces]);

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    createWorkspace.mutate(newWorkspace, {
      onSuccess: () => {
        setShowCreateDialog(false);
        setNewWorkspace({ name: '', description: '' });
      },
    });
  };

  const handleDelete = async (workspace: any) => {
    const confirmed = await confirm({
      title: 'Delete Workspace',
      description: `Are you sure you want to delete "${workspace.name}"? This action cannot be undone.`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
      variant: 'danger',
    });
    if (confirmed) {
      deleteWorkspace.mutate(workspace.id);
    }
  };

  const statCards = isLoading ? [
    { title: 'Total Workspaces', value: '...', icon: FolderOpen, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: '...', icon: Activity, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Total Members', value: '...', icon: Users, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Total Volumes', value: '...', icon: HardDrive, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ] : [
    { title: 'Total Workspaces', value: stats.totalWorkspaces, icon: FolderOpen, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: stats.activeWorkspaces, icon: Activity, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Total Members', value: stats.totalMembers, icon: Users, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Total Volumes', value: stats.totalVolumes, icon: HardDrive, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

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
        {/* Search Toolbar */}
        {!isLoading && workspaces.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springs.gentle}
            className="flex flex-col sm:flex-row items-start sm:items-center gap-3"
          >
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none z-10" />
              <Input
                placeholder="Search workspaces..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
          </motion.div>
        )}

        {/* Content */}
        {isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
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
            <p className="text-muted-foreground">No workspaces match your search.</p>
            <Button variant="outline" size="sm" onClick={() => setSearchQuery('')} className="mt-2">
              Clear Search
            </Button>
          </motion.div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            <AnimatePresence mode="popLayout">
              {filteredWorkspaces.map((workspace, index) => (
                <WorkspaceCard
                  key={workspace.id}
                  workspace={workspace}
                  index={index}
                  onDelete={() => handleDelete(workspace)}
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
                  required
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Description</label>
                <Textarea
                  value={newWorkspace.description}
                  onChange={(e) => setNewWorkspace({ ...newWorkspace, description: e.target.value })}
                  placeholder="Optional description"
                  rows={3}
                />
              </div>
              
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowCreateDialog(false)}
                >
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
  );
}
