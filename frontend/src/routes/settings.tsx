import { createFileRoute } from '@tanstack/react-router';
import { Settings } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
});

function SettingsPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Settings" subtitle="Platform configuration" icon={Settings} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <Settings className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Settings</h2>
          <p className="text-muted-foreground">Settings management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
