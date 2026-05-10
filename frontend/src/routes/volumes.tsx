import { createFileRoute } from '@tanstack/react-router';
import {
  HardDrive,
  Database,
  Layers,
  Zap,
  FolderOpen,
  Calendar,
  Tag,
  ArrowUpDown,
  Search,
  Server,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useState, useMemo } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { useVolumes } from '../hooks/use-volumes';
import { SkeletonCard } from '../components/feedback/skeleton';
import { EmptyState } from '../components/feedback/empty-state';
import { Card, CardContent } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { Tooltip } from '../components/ui/tooltip';
import { formatBytes } from '../lib/utils';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import type { Volume } from '../hooks/use-volumes';

export const Route = createFileRoute('/volumes')({
  component: VolumesPage,
});

// Extract server name from volume name pattern: nukelab-server-{user}-{server}-data
function extractServerName(volumeName: string): string {
  const parts = volumeName.split('-');
  // Remove prefix "nukelab-server-{user}-" and suffix "-data"
  if (parts.length > 3 && parts[0] === 'nukelab' && parts[1] === 'server') {
    const serverParts = parts.slice(3, -1);
    return serverParts.join('-') || volumeName;
  }
  return volumeName;
}

// Extract username from volume name
function extractUsername(volumeName: string): string | null {
  const parts = volumeName.split('-');
  if (parts.length > 3 && parts[0] === 'nukelab' && parts[1] === 'server') {
    return parts[2] || null;
  }
  return null;
}

// Volume Card Component
function VolumeCard({ volume, index, maxSize }: { volume: Volume; index: number; maxSize: number }) {
  const serverName = extractServerName(volume.name);
  const username = extractUsername(volume.name);
  const sizePercent = volume.size && maxSize > 0 ? (volume.size / maxSize) * 100 : 0;
  const isLarge = sizePercent > 80;
  const isMedium = sizePercent > 50;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, ...springs.gentle }}
    >
      <Card variant="bubble" interactive className="overflow-hidden">
        <CardContent className="p-5">
          {/* Header */}
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className={cn(
                "p-2.5 rounded-xl shrink-0",
                isLarge ? "bg-red-500/10" : isMedium ? "bg-amber-500/10" : "bg-primary/10"
              )}>
                <HardDrive className={cn(
                  "w-5 h-5",
                  isLarge ? "text-red-400" : isMedium ? "text-amber-400" : "text-primary"
                )} />
              </div>
              <div className="min-w-0">
                <h3 className="font-semibold text-sm truncate" title={volume.name}>
                  {serverName}
                </h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-muted-foreground flex items-center gap-1">
                    <Server className="w-3 h-3" />
                    {username || 'unknown'}
                  </span>
                </div>
              </div>
            </div>
            <Tooltip content={`Driver: ${volume.driver}`}>
              <span className="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-muted/50 text-xs text-muted-foreground">
                <Tag className="w-3 h-3" />
                {volume.driver}
              </span>
            </Tooltip>
          </div>

          {/* Size visualization */}
          {volume.size != null ? (
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-muted-foreground">Storage Used</span>
                <span className={cn(
                  "text-xs font-medium",
                  isLarge ? "text-red-400" : isMedium ? "text-amber-400" : "text-emerald-400"
                )}>
                  {formatBytes(volume.size)}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <motion.div
                  className={cn(
                    "h-full rounded-full",
                    isLarge ? "bg-red-500" : isMedium ? "bg-amber-500" : "bg-emerald-500"
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(sizePercent, 100)}%` }}
                  transition={{ duration: 1, ease: "easeOut", delay: index * 0.05 }}
                />
              </div>
            </div>
          ) : (
            <div className="mb-4 p-3 rounded-lg bg-muted/30 text-center">
              <span className="text-xs text-muted-foreground">Size unknown</span>
            </div>
          )}

          {/* Metadata */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <FolderOpen className="w-3.5 h-3.5" />
                Mount
              </span>
              <Tooltip content={volume.mountpoint}>
                <code className="font-mono text-[10px] bg-muted/50 px-1.5 py-0.5 rounded truncate max-w-[200px]">
                  {volume.mountpoint}
                </code>
              </Tooltip>
            </div>
            {volume.created_at && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <Calendar className="w-3.5 h-3.5" />
                  Created
                </span>
                <span className="text-muted-foreground">
                  {new Date(volume.created_at).toLocaleDateString(undefined, {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function VolumesPage() {
  const { data: volumes = [], isLoading } = useVolumes();
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'size' | 'date'>('name');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

  // Calculate stats
  const stats = useMemo(() => {
    const totalSize = volumes.reduce((acc, v) => acc + (v.size || 0), 0);
    const avgSize = volumes.length > 0 ? totalSize / volumes.length : 0;
    const largestVolume = volumes.reduce((max, v) => (v.size || 0) > (max?.size || 0) ? v : max, volumes[0]);
    
    return {
      totalVolumes: volumes.length,
      totalSize,
      avgSize,
      largestVolume: largestVolume?.size || 0,
    };
  }, [volumes]);

  // Filter and sort volumes
  const filteredVolumes = useMemo(() => {
    let result = [...volumes];

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(v =>
        v.name.toLowerCase().includes(query) ||
        v.driver.toLowerCase().includes(query) ||
        v.mountpoint.toLowerCase().includes(query) ||
        (extractUsername(v.name)?.toLowerCase().includes(query))
      );
    }

    // Sort
    result.sort((a, b) => {
      let comparison = 0;
      switch (sortBy) {
        case 'name':
          comparison = a.name.localeCompare(b.name);
          break;
        case 'size':
          comparison = (a.size || 0) - (b.size || 0);
          break;
        case 'date':
          comparison = new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
          break;
      }
      return sortOrder === 'asc' ? comparison : -comparison;
    });

    return result;
  }, [volumes, searchQuery, sortBy, sortOrder]);

  const maxSize = useMemo(() => {
    return Math.max(...volumes.map(v => v.size || 0), 1);
  }, [volumes]);

  const handleSort = (field: 'name' | 'size' | 'date') => {
    if (sortBy === field) {
      setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(field);
      setSortOrder('asc');
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
    <ResourcePageLayout
      title="Volumes"
      subtitle="Manage storage volumes"
      icon={HardDrive}
      stats={statCards}
    >
      {/* Search and Sort Toolbar */}
      {!isLoading && volumes.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
          className="flex flex-col sm:flex-row items-start sm:items-center gap-3"
        >
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search volumes..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground mr-1">Sort by:</span>
            {([
              { field: 'name' as const, label: 'Name' },
              { field: 'size' as const, label: 'Size' },
              { field: 'date' as const, label: 'Date' },
            ]).map(({ field, label }) => (
              <Button
                key={field}
                variant={sortBy === field ? 'default' : 'outline'}
                size="sm"
                onClick={() => handleSort(field)}
                className="gap-1 text-xs"
              >
                {label}
                {sortBy === field && (
                  <ArrowUpDown className={cn("w-3 h-3", sortOrder === 'desc' && "rotate-180")} />
                )}
              </Button>
            ))}
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
          description="No volumes found. Volumes are created automatically when you spawn servers."
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <AnimatePresence mode="popLayout">
            {filteredVolumes.map((volume, index) => (
              <VolumeCard
                key={volume.name}
                volume={volume}
                index={index}
                maxSize={maxSize}
              />
            ))}
          </AnimatePresence>
        </div>
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
  );
}
