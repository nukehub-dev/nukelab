import { createFileRoute } from '@tanstack/react-router';
import { FileText, Shield, AlertTriangle, Activity } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/audit-logs')({
  component: AuditLogsPage,
});

function AuditLogsPage() {
  return (
    <PlaceholderPage
      title="Audit Logs"
      subtitle="Platform activity monitoring"
      icon={FileText}
      description="Comprehensive audit trail for all platform activities and security events."
      stats={[
        { title: 'Total Events', value: '12.5K', icon: FileText, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Security', value: 48, icon: Shield, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
        { title: 'Warnings', value: 12, icon: AlertTriangle, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Today', value: 234, icon: Activity, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
      ]}
    />
  );
}
