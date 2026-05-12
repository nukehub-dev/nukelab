import { createFileRoute } from '@tanstack/react-router';
import {
  HardDrive,
  Database,
  Layers,
  Zap,
  Server,
  Trash2,
  Plus,
  X,
  FolderOpen,
  Search,
  Pencil,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useState, useMemo } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { useVolumes, useCreateVolume, useDeleteVolume, useUpdateVolume } from '../hooks/use-volumes';
import { FileBrowser } from '../components/volume-file-browser';
import { SkeletonCard } from '../components/feedback/skeleton';
import { EmptyState } from '../components/feedback/empty-state';
import { Card, CardContent } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Button } from '../components/ui/button';
import { Tooltip } from '../components/ui/tooltip';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { formatBytes } from '../lib/utils';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import type { Volume } from '../hooks/use-volumes';

export const Route = createFileRoute('/volumes')({
  component: VolumesPage,
});

// Volume Card Component
function VolumeCard({ 
  volume, 
  index, 
  onDelete, 
  onBrowse,
  onEdit
}: { 
  volume: Volume; 
  index: number; 
  onDelete?: () => void;
  onBrowse?: () => void;
  onEdit?: () => void;
}) {
  const sizePercent = volume.size_bytes > 0 && volume.max_size_bytes && volume.max_size_bytes > 0
    ? (volume.size_bytes / volume.max_size_bytes) * 100
    : 0;
  const isLarge = sizePercent > 80;
  const isOverLimit = volume.status === 'over_limit';

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, ...springs.gentle }}
    >
      <Card variant="bubble" interactive className="overflow-hidden">
        <CardContent className="p-5">
          {/* Header */}
          <div className="flex items-start justify-between mb-4 gap-2">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <div className={cn(
                "p-2 rounded-xl shrink-0",
                isOverLimit ? "bg-red-500/10" : isLarge ? "bg-amber-500/10" : "bg-primary/10"
              )}>
                <HardDrive className={cn(
                  "w-4 h-4",
                  isOverLimit ? "text-red-400" : isLarge ? "text-amber-400" : "text-primary"
                )} />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-sm truncate">
                  {volume.display_name}
                </h3>
                <span className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                  <Server className="w-3 h-3" />
                  {volume.server_count} {volume.server_count === 1 ? 'server' : 'servers'}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {volume.visibility !== 'private' && (
                <span className={cn(
                  "shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider",
                  volume.visibility === 'public' ? "bg-emerald-500/10 text-emerald-400" : "bg-muted/50 text-muted-foreground"
                )}>
                  {volume.visibility}
                </span>
              )}
              {onBrowse && (
                <Tooltip content="Browse files">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onBrowse();
                    }}
                    className="p-1.5 rounded-lg hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                  >
                    <FolderOpen className="w-3.5 h-3.5" />
                  </button>
                </Tooltip>
              )}
              {onEdit && (
                <Tooltip content="Edit volume">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onEdit();
                    }}
                    className="p-1.5 rounded-lg hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                </Tooltip>
              )}
              {onDelete && volume.server_count === 0 && (
                <Tooltip content="Delete volume">
                  <button
                    onClick={(e) => {
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

          {/* Size visualization */}
          {volume.size_bytes > 0 ? (
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-muted-foreground">Storage Used</span>
                <span className={cn(
                  "text-xs font-medium",
                  isOverLimit ? "text-red-400" : isLarge ? "text-amber-400" : "text-emerald-400"
                )}>
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
                    "h-full rounded-full",
                    isOverLimit ? "bg-red-500" : isLarge ? "bg-amber-500" : "bg-emerald-500"
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(sizePercent, 100)}%` }}
                  transition={{ duration: 1, ease: "easeOut", delay: index * 0.05 }}
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

          {/* Status & Date */}
          <div className="flex items-center justify-between text-xs">
            {volume.status !== 'active' && (
              <span className={cn(
                "px-2 py-0.5 rounded-full",
                volume.status === 'over_limit' ? "bg-red-500/10 text-red-400" :
                volume.status === 'archived' ? "bg-amber-500/10 text-amber-400" :
                "bg-muted/50 text-muted-foreground"
              )}>
                {volume.status}
              </span>
            )}
            {volume.created_at && (
              <span className={cn("text-muted-foreground", volume.status === 'active' && "ml-auto")}>
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
  );
}

function VolumesPage() {
  const { data: volumes = [], isLoading } = useVolumes();
  const createVolume = useCreateVolume();
  const deleteVolume = useDeleteVolume();
  const updateVolume = useUpdateVolume();
  const { confirm, dialog } = useConfirmDialog();
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [createForm, setCreateForm] = useState({
    display_name: '',
    description: '',
  });
  const [editForm, setEditForm] = useState({
    id: '',
    display_name: '',
    description: '',
  });
  const [browsingVolume, setBrowsingVolume] = useState<{ id: string; name: string } | null>(null);

  // Calculate stats
  const stats = useMemo(() => {
    const totalSize = volumes.reduce((acc, v) => acc + (v.size_bytes || 0), 0);
    const avgSize = volumes.length > 0 ? totalSize / volumes.length : 0;
    const largestVolume = volumes.reduce((max, v) => (v.size_bytes || 0) > (max?.size_bytes || 0) ? v : max, volumes[0]);
    
    return {
      totalVolumes: volumes.length,
      totalSize,
      avgSize,
      largestVolume: largestVolume?.size_bytes || 0,
    };
  }, [volumes]);

  // Filter volumes
  const filteredVolumes = useMemo(() => {
    let result = [...volumes];

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(v =>
        v.display_name.toLowerCase().includes(query) ||
        v.name.toLowerCase().includes(query) ||
        v.status.toLowerCase().includes(query)
      );
    }

    return result;
  }, [volumes, searchQuery]);

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!createForm.display_name.trim()) return;
    
    createVolume.mutate(
      { display_name: createForm.display_name, description: createForm.description || undefined },
      {
        onSuccess: () => {
          setShowCreateDialog(false);
          setCreateForm({ display_name: '', description: '' });
        },
      }
    );
  };

  const handleEdit = (volume: Volume) => {
    setEditForm({
      id: volume.id,
      display_name: volume.display_name,
      description: volume.description || '',
    });
    setShowEditDialog(true);
  };

  const handleUpdate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editForm.display_name.trim()) return;

    updateVolume.mutate(
      {
        volumeId: editForm.id,
        data: {
          display_name: editForm.display_name,
          description: editForm.description || undefined,
        },
      },
      {
        onSuccess: () => {
          setShowEditDialog(false);
          setEditForm({ id: '', display_name: '', description: '' });
        },
      }
    );
  };

  const handleDelete = async (volume: Volume) => {
    const confirmed = await confirm({
      title: 'Delete Volume',
      description: `Are you sure you want to delete "${volume.display_name}"? This action cannot be undone.`,
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
      variant: 'danger',
    });
    if (confirmed) {
      deleteVolume.mutate(volume.id);
    }
  };

  const statCards = isLoading ? [
    { title: 'Total Volumes', value: '...', icon: HardDrive, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Total Size', value: '...', icon: Database, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Average Size', value: '...', icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Largest Volume', value: '...', icon: Zap, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
  ] : [
    { title: 'Total Volumes', value: stats.totalVolumes, icon: HardDrive, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Total Size', value: formatBytes(stats.totalSize), icon: Database, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Average Size', value: formatBytes(stats.avgSize), icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Largest Volume', value: formatBytes(stats.largestVolume), icon: Zap, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
  ];

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
        {/* Search Toolbar */}
        {!isLoading && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springs.gentle}
            className="flex flex-col sm:flex-row items-start sm:items-center gap-3"
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
          </motion.div>
        )}

        {/* Content */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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
            <p className="text-muted-foreground">No volumes match your search.</p>
            <Button variant="outline" size="sm" onClick={() => setSearchQuery('')} className="mt-2">
              Clear Search
            </Button>
          </motion.div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            <AnimatePresence mode="popLayout">
              {filteredVolumes.map((volume, index) => (
                <VolumeCard
                  key={volume.id}
                  volume={volume}
                  index={index}
                  onDelete={() => handleDelete(volume)}
                  onBrowse={() => setBrowsingVolume({ id: volume.id, name: volume.display_name })}
                  onEdit={() => handleEdit(volume)}
                />
              ))}
            </AnimatePresence>
          </div>
        )}

        {/* File Browser Dialog */}
        {browsingVolume && (
          <FileBrowser
            volumeId={browsingVolume.id}
            volumeName={browsingVolume.name}
            onClose={() => setBrowsingVolume(null)}
          />
        )}

        {/* Footer Stats */}
        {!isLoading && volumes.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="text-center text-xs text-muted-foreground pt-4"
          >
            Showing {filteredVolumes.length} of {volumes.length} volumes
            {searchQuery && ` matching "${searchQuery}"`}
          </motion.div>
        )}
      </ResourcePageLayout>

      {/* Create Volume Dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          onClick={() => setShowCreateDialog(false)}
        >
          <motion.div
            className="w-full max-w-md rounded-2xl bg-card/95 backdrop-blur-xl border border-border/50 shadow-2xl overflow-hidden"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-1 bg-primary" />
            <div className="p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">Create Volume</h3>
                <button
                  onClick={() => setShowCreateDialog(false)}
                  className="p-1 rounded hover:bg-muted transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <form onSubmit={handleCreate} className="space-y-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">Display Name *</label>
                  <Input
                    value={createForm.display_name}
                    onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
                    placeholder="My Project Data"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">Description</label>
                  <Textarea
                    value={createForm.description}
                    onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                    placeholder="Optional description"
                    rows={3}
                  />
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" type="button" onClick={() => setShowCreateDialog(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" loading={createVolume.isPending}>
                    Create
                  </Button>
                </div>
              </form>
            </div>
          </motion.div>
        </div>
      )}

      {/* Edit Volume Dialog */}
      {showEditDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          onClick={() => setShowEditDialog(false)}
        >
          <motion.div
            className="w-full max-w-md rounded-2xl bg-card/95 backdrop-blur-xl border border-border/50 shadow-2xl overflow-hidden"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-1 bg-primary" />
            <div className="p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">Edit Volume</h3>
                <button
                  onClick={() => setShowEditDialog(false)}
                  className="p-1 rounded hover:bg-muted transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <form onSubmit={handleUpdate} className="space-y-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">Display Name *</label>
                  <Input
                    value={editForm.display_name}
                    onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })}
                    placeholder="My Project Data"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">Description</label>
                  <Textarea
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    placeholder="Optional description"
                    rows={3}
                  />
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" type="button" onClick={() => setShowEditDialog(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" loading={updateVolume.isPending}>
                    Save Changes
                  </Button>
                </div>
              </form>
            </div>
          </motion.div>
        </div>
      )}

      {/* Confirmation Dialog */}
      {dialog}
    </>
  );
}
