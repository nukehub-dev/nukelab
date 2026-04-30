import { createFileRoute } from '@tanstack/react-router';
import { Network } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/networks')({
  component: NetworksPage,
});

function NetworksPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Networks" subtitle="Manage container networks" icon={Network} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <Network className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Networks</h2>
          <p className="text-muted-foreground">Network management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
