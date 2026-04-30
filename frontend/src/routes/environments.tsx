import { createFileRoute } from '@tanstack/react-router';
import { Boxes } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/environments')({
  component: EnvironmentsPage,
});

function EnvironmentsPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Environments" subtitle="Manage deployment environments" icon={Boxes} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <Boxes className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Environments</h2>
          <p className="text-muted-foreground">Environment management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
