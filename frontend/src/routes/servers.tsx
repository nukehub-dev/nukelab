import { createFileRoute } from '@tanstack/react-router';
import { Server } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/servers')({
  component: ServersPage,
});

function ServersPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Servers" subtitle="Manage your simulation servers" icon={Server} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <Server className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Servers</h2>
          <p className="text-muted-foreground">Server management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
