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
  Clock,
  ArrowUpRight,
  Activity,
} from 'lucide-react';
import {
  useWorkspaces,
  useCreateWorkspace,
  useDeleteWorkspace,
} from '../hooks/use-workspaces';
import { useVolumes } from '../hooks/use-volumes';
import { springs } from '../lib/animations';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../components/ui/dialog';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { Tooltip } from '../components/ui/tooltip';
import { Combobox } from '../components/ui/combobox';
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

function WorkspacesListPage() {
  const { data: workspaces = [], isLoading } = useWorkspaces();
  const { data: volumesData } = useVolumes();
  const createWorkspace = useCreateWorkspace();
  const deleteWorkspace = useDeleteWorkspace();
  const { confirm, dialog } = useConfirmDialog();

  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newWorkspace, setNewWorkspace] = useState({
    name: '',
    description: '',
    volume_name: '',
  });

  const volumes = volumesData || [];
  const volumeOptions = volumes.map((vol: any) => ({
    value: vol.name,
    label: vol.name,
  }));

  const filteredWorkspaces = useMemo(() => {
    if (!searchQuery.trim()) return workspaces;
    const query = searchQuery.toLowerCase();
    return workspaces.filter(
      (w) =>
        w.name.toLowerCase().includes(query) ||
        w.description?.toLowerCase().includes(query) ||
        w.volume_name.toLowerCase().includes(query)
    );
  }, [workspaces, searchQuery]);

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    createWorkspace.mutate(newWorkspace, {
      onSuccess: () => {
        setShowCreateDialog(false);
        setNewWorkspace({ name: '', description: '', volume_name: '' });
      },
    });
  };

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="space-y-6"
      >
        {/* Title Row */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-primary/10 border border-primary/20">
                <FolderOpen className="w-6 h-6 text-primary" />
              </div>
              <div>
                <h1 className="text-3xl font-bold tracking-tight">Workspaces</h1>
                <p className="text-sm text-muted-foreground">
                  Manage collaborative environments and shared volumes
                </p>
              </div>
            </div>
          </div>
          <Button 
            onClick={() => setShowCreateDialog(true)} 
            className="gap-2 shadow-lg shadow-primary/20"
            size="lg"
          >
            <Plus className="w-4 h-4" />
            New Workspace
          </Button>
        </div>

        {/* Stats Bar */}
        {!isLoading && workspaces.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, ...springs.gentle }}
            className="flex flex-wrap items-center gap-4"
          >
            <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card border border-border/50">
              <FolderOpen className="w-4 h-4 text-primary" />
              <span className="text-sm font-medium">{workspaces.length}</span>
              <span className="text-sm text-muted-foreground">total</span>
            </div>
            <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card border border-border/50">
              <Activity className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-medium">
                {workspaces.filter((w) => w.is_active).length}
              </span>
              <span className="text-sm text-muted-foreground">active</span>
            </div>
            <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-card border border-border/50">
              <Users className="w-4 h-4 text-chart-2" />
              <span className="text-sm font-medium">
                {workspaces.reduce((acc, w) => acc + (w.member_count || 0), 0)}
              </span>
              <span className="text-sm text-muted-foreground">members</span>
            </div>
          </motion.div>
        )}

        {/* Search */}
        {workspaces.length > 0 && (
          <div className="relative max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search workspaces..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 h-11"
            />
          </div>
        )}
      </motion.div>

      {/* Content */}
      {isLoading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="h-40 animate-pulse bg-muted/50" />
          ))}
        </div>
      ) : workspaces.length === 0 ? (
        <motion.div
          className="flex flex-col items-center justify-center py-20 px-4"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
        >
          <div className="w-20 h-20 rounded-2xl bg-primary/5 border border-primary/10 flex items-center justify-center mb-6">
            <FolderOpen className="w-10 h-10 text-primary/40" />
          </div>
          <h3 className="text-xl font-semibold mb-2">No Workspaces Yet</h3>
          <p className="text-muted-foreground text-center max-w-sm mb-6">
            Create your first workspace to start collaborating with your team on shared volumes.
          </p>
          <Button onClick={() => setShowCreateDialog(true)} className="gap-2">
            <Plus className="w-4 h-4" />
            Create Workspace
          </Button>
        </motion.div>
      ) : filteredWorkspaces.length === 0 ? (
        <motion.div
          className="flex flex-col items-center justify-center py-16"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <Search className="w-12 h-12 text-muted-foreground/50 mb-4" />
          <h3 className="text-lg font-semibold mb-1">No results found</h3>
          <p className="text-muted-foreground">Try adjusting your search query</p>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <AnimatePresence mode="popLayout">
            {filteredWorkspaces.map((workspace, index) => (
              <Link
                key={workspace.id}
                to="/workspaces/$workspaceId"
                params={{ workspaceId: workspace.id }}
              >
                <motion.div
                  layout
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ delay: index * 0.05, ...springs.gentle }}
                >
                  <Card 
                    interactive 
                    className="group overflow-hidden border-border/50 cursor-pointer"
                  >
                    <CardContent className="p-0">
                      {/* Top Section with Color Accent */}
                      <div className="relative">
                        <div className="absolute top-0 left-0 right-0 h-1 bg-primary/80" />
                        <div className="p-6 pb-4">
                          <div className="flex items-start justify-between">
                            <div className="flex items-center gap-4 min-w-0">
                              <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0">
                                <FolderOpen className="w-6 h-6 text-primary" />
                              </div>
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <h3 className="text-lg font-semibold truncate">
                                    {workspace.name}
                                  </h3>
                                  {workspace.is_active ? (
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                                      Active
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground border border-border">
                                      Inactive
                                    </span>
                                  )}
                                </div>
                                {workspace.description ? (
                                  <p className="text-sm text-muted-foreground mt-1 line-clamp-1">
                                    {workspace.description}
                                  </p>
                                ) : (
                                  <p className="text-sm text-muted-foreground/60 mt-1 italic">
                                    No description
                                  </p>
                                )}
                              </div>
                            </div>
                            
                            {/* Delete Action */}
                            <Tooltip content="Delete workspace">
                              <button
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  confirm({
                                    title: 'Delete Workspace',
                                    description: `Are you sure you want to delete "${workspace.name}"? This action cannot be undone.`,
                                    confirmLabel: 'Delete',
                                    cancelLabel: 'Cancel',
                                    variant: 'danger',
                                  }).then((confirmed) => {
                                    if (confirmed) {
                                      deleteWorkspace.mutate(workspace.id);
                                    }
                                  });
                                }}
                                className="p-2 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all hover:scale-110"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </Tooltip>
                          </div>
                        </div>
                      </div>

                      {/* Divider */}
                      <div className="mx-6 border-t border-border/50" />

                      {/* Bottom Section - Metadata */}
                      <div className="p-6 pt-4">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-4 flex-wrap">
                            <Tooltip content={`${workspace.member_count} member${workspace.member_count !== 1 ? 's' : ''}`}>
                              <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                                <Users className="w-4 h-4" />
                                <span>{workspace.member_count}</span>
                              </div>
                            </Tooltip>
                            
                            <Tooltip content={workspace.volume_name}>
                              <div className="flex items-center gap-1.5 text-sm text-muted-foreground max-w-[200px]">
                                <HardDrive className="w-4 h-4 flex-shrink-0" />
                                <span className="truncate">{workspace.volume_name}</span>
                              </div>
                            </Tooltip>

                            {workspace.created_at && (
                              <Tooltip content={`Created on ${formatDate(workspace.created_at)}`}>
                                <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                                  <Clock className="w-4 h-4" />
                                  <span>{formatDate(workspace.created_at)}</span>
                                </div>
                              </Tooltip>
                            )}
                          </div>

                          <ArrowUpRight className="w-5 h-5 text-muted-foreground/40 group-hover:text-primary transition-colors" />
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              </Link>
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-primary/10">
                <Plus className="w-4 h-4 text-primary" />
              </div>
              Create Workspace
            </DialogTitle>
            <DialogDescription>
              Create a new shared workspace with a volume for your team.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-5 mt-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Name</label>
              <Input
                value={newWorkspace.name}
                onChange={(e) => setNewWorkspace({ ...newWorkspace, name: e.target.value })}
                placeholder="My Team Workspace"
                required
                className="h-11"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Input
                value={newWorkspace.description}
                onChange={(e) => setNewWorkspace({ ...newWorkspace, description: e.target.value })}
                placeholder="Optional description"
                className="h-11"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Volume</label>
              <Combobox
                value={newWorkspace.volume_name}
                onChange={(value) => setNewWorkspace({ ...newWorkspace, volume_name: value })}
                options={volumeOptions}
                placeholder="Select a volume..."
                searchPlaceholder="Search volumes..."
              />
            </div>
            <DialogFooter className="gap-2">
              <Button variant="outline" type="button" onClick={() => setShowCreateDialog(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={createWorkspace.isPending}>
                Create Workspace
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmation Dialog */}
      {dialog}
    </div>
  );
}
