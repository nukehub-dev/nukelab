import { createFileRoute } from '@tanstack/react-router';
import { HardDrive } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/volumes')({
  component: VolumesPage,
});

function VolumesPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Volumes" subtitle="Manage storage volumes" icon={HardDrive} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <HardDrive className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Volumes</h2>
          <p className="text-muted-foreground">Volume management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
