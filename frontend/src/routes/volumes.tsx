import { createFileRoute } from '@tanstack/react-router';
import { HardDrive, Database, Layers, Zap } from 'lucide-react';
import { motion } from 'framer-motion';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { useVolumes } from '../hooks/use-volumes';
import { SkeletonCard } from '../components/feedback/skeleton';
import { formatBytes } from '../lib/utils';
import { springs } from '../lib/animations';

export const Route = createFileRoute('/volumes')({
  component: VolumesPage,
});

function VolumesPage() {
  const { data: volumes = [], isLoading } = useVolumes();

  const totalSize = volumes.reduce((acc, v) => acc + (v.size || 0), 0);

  return (
    <ResourcePageLayout
      title="Volumes"
      subtitle="Manage storage volumes"
      icon={HardDrive}
      stats={isLoading ? [
        { title: 'Volumes', value: '...', icon: HardDrive, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Used Space', value: '...', icon: Database, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Snapshots', value: '...', icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
        { title: 'IOPS', value: '...', icon: Zap, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
      ] : [
        { title: 'Volumes', value: volumes.length, icon: HardDrive, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Used Space', value: formatBytes(totalSize), icon: Database, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Snapshots', value: 0, icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
        { title: 'IOPS', value: '0', icon: Zap, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
      ]}
    >
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonCard key={i} rows={2} />
          ))}
        </div>
      ) : volumes.length === 0 ? (
        <motion.div
          className="bubble p-12 text-center"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
        >
          <HardDrive className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-lg font-semibold mb-2">No Volumes</h2>
          <p className="text-muted-foreground">
            No volumes found. Volumes are created automatically when you spawn servers.
          </p>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {volumes.map((volume, index) => (
            <motion.div
              key={volume.name}
              className="bubble p-5 hover-lift"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-primary/10">
                    <HardDrive className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-sm">{volume.name}</h3>
                    <p className="text-xs text-muted-foreground">{volume.driver}</p>
                  </div>
                </div>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Size</span>
                  <span>{volume.size ? formatBytes(volume.size) : 'Unknown'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Mountpoint</span>
                  <span className="font-mono text-xs">{volume.mountpoint}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Created</span>
                  <span className="text-xs">{volume.created_at ? new Date(volume.created_at).toLocaleDateString() : 'Unknown'}</span>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </ResourcePageLayout>
  );
}
