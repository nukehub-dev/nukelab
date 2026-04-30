import { createFileRoute } from '@tanstack/react-router';
import { HardDrive, Database, Layers, Zap } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/volumes')({
  component: VolumesPage,
});

function VolumesPage() {
  return (
    <PlaceholderPage
      title="Volumes"
      subtitle="Manage storage volumes"
      icon={HardDrive}
      description="Persistent storage management, volume snapshots, and backup configuration."
      stats={[
        { title: 'Volumes', value: 32, icon: HardDrive, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Used Space', value: '456 GB', icon: Database, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Snapshots', value: 18, icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
        { title: 'IOPS', value: '2.4K', icon: Zap, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
      ]}
    />
  );
}
