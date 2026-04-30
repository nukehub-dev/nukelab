import { createFileRoute } from '@tanstack/react-router';
import { FileText, Shield, AlertTriangle, Activity, Construction } from 'lucide-react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';

export const Route = createFileRoute('/audit-logs')({
  component: AuditLogsPage,
});

function AuditLogsPage() {
  return (
    <ResourcePageLayout
      title="Audit Logs"
      subtitle="Platform activity monitoring"
      icon={FileText}
      stats={[
        { title: 'Total Events', value: '0', icon: FileText, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Security', value: 0, icon: Shield, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
        { title: 'Warnings', value: 0, icon: AlertTriangle, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Today', value: 0, icon: Activity, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
      ]}
    >
      <div className="bubble p-12 text-center">
        <Construction className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
        <h2 className="text-lg font-semibold mb-2">Coming Soon</h2>
        <p className="text-muted-foreground">
          Audit log management is under development. Check back soon for updates.
        </p>
      </div>
    </ResourcePageLayout>
  );
}
