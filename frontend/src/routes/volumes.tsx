import { createFileRoute } from '@tanstack/react-router';
import { HardDrive, Database, Layers, Zap, Construction } from 'lucide-react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';

export const Route = createFileRoute('/volumes')({
  component: VolumesPage,
});

function VolumesPage() {
  return (
    <ResourcePageLayout
      title="Volumes"
      subtitle="Manage storage volumes"
      icon={HardDrive}
      stats={[
        { title: 'Volumes', value: 0, icon: HardDrive, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Used Space', value: '0 GB', icon: Database, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Snapshots', value: 0, icon: Layers, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
        { title: 'IOPS', value: '0', icon: Zap, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
      ]}
    >
      <div className="bubble p-12 text-center">
        <Construction className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
        <h2 className="text-lg font-semibold mb-2">Coming Soon</h2>
        <p className="text-muted-foreground">
          Volume management is under development. Check back soon for updates.
        </p>
      </div>
    </ResourcePageLayout>
  );
}
