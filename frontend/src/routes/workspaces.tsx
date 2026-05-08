import { createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  FolderOpen,
  Users,
  HardDrive,
  Plus,
  Trash2,
  Pencil,
  ExternalLink,
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
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../components/ui/dialog';
import { Link } from '@tanstack/react-router';

export const Route = createFileRoute('/workspaces')({
  component: WorkspacesPage,
});

function WorkspacesPage() {
  const { data: workspaces = [], isLoading } = useWorkspaces();
  const { data: volumes = [] } = useVolumes();
  const createWorkspace = useCreateWorkspace();
  const deleteWorkspace = useDeleteWorkspace();

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newWorkspace, setNewWorkspace] = useState({
    name: '',
    description: '',
    volume_name: '',
  });

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
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col md:flex-row md:items-center md:justify-between gap-4"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <FolderOpen className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Shared Workspaces</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Collaborative workspaces with shared volumes
            </p>
          </div>
        </div>

        <Button onClick={() => setShowCreateDialog(true)} className="gap-2">
          <Plus className="w-4 h-4" />
          New Workspace
        </Button>
      </motion.div>

      {/* Workspaces Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bubble p-5 animate-pulse">
              <div className="h-6 bg-muted rounded w-3/4 mb-3"></div>
              <div className="h-4 bg-muted rounded w-full mb-2"></div>
              <div className="h-4 bg-muted rounded w-1/2"></div>
            </div>
          ))}
        </div>
      ) : workspaces.length === 0 ? (
        <motion.div
          className="bubble p-10 text-center"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
        >
          <FolderOpen className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
          <h3 className="text-lg font-semibold mb-2">No Workspaces</h3>
          <p className="text-muted-foreground mb-4">Create a workspace to share volumes with your team.</p>
          <Button onClick={() => setShowCreateDialog(true)}>Create Workspace</Button>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {workspaces.map((workspace, index) => (
            <motion.div
              key={workspace.id}
              className="bubble p-5 hover-lift group"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-primary/10">
                    <FolderOpen className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-semibold">{workspace.name}</h3>
                    <p className="text-xs text-muted-foreground">{workspace.volume_name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Link
                    to="/workspaces/$workspaceId"
                    params={{ workspaceId: workspace.id }}
                    className="p-1.5 rounded hover:bg-primary/10 text-primary transition-colors"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </Link>
                  <button
                    onClick={() => {
                      if (confirm('Delete this workspace?')) {
                        deleteWorkspace.mutate(workspace.id);
                      }
                    }}
                    className="p-1.5 rounded hover:bg-destructive/10 text-destructive transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {workspace.description && (
                <p className="text-sm text-muted-foreground mb-3 line-clamp-2">{workspace.description}</p>
              )}

              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Users className="w-3.5 h-3.5" />
                  {workspace.member_count} members
                </span>
                <span className="flex items-center gap-1">
                  <HardDrive className="w-3.5 h-3.5" />
                  {workspace.volume_name}
                </span>
              </div>

              <Link
                to="/workspaces/$workspaceId"
                params={{ workspaceId: workspace.id }}
                className="mt-3 inline-flex items-center gap-1 text-sm text-primary hover:underline"
              >
                Manage
                <ExternalLink className="w-3 h-3" />
              </Link>
            </motion.div>
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Workspace</DialogTitle>
            <DialogDescription>
              Create a new shared workspace with a volume.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4 mt-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Name</label>
              <Input
                value={newWorkspace.name}
                onChange={(e) => setNewWorkspace({ ...newWorkspace, name: e.target.value })}
                placeholder="My Team Workspace"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Input
                value={newWorkspace.description}
                onChange={(e) => setNewWorkspace({ ...newWorkspace, description: e.target.value })}
                placeholder="Optional description"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Volume</label>
              <select
                value={newWorkspace.volume_name}
                onChange={(e) => setNewWorkspace({ ...newWorkspace, volume_name: e.target.value })}
                className="w-full h-9 px-3 rounded-lg border border-input bg-background text-sm"
                required
              >
                <option value="">Select a volume...</option>
                {volumes.map((vol: any) => (
                  <option key={vol.name} value={vol.name}>{vol.name}</option>
                ))}
              </select>
            </div>
            <DialogFooter>
              <Button variant="outline" type="button" onClick={() => setShowCreateDialog(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={createWorkspace.isPending}>Create</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
