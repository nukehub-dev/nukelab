import { createFileRoute } from '@tanstack/react-router';
import { FileText } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/audit-logs')({
  component: AuditLogsPage,
});

function AuditLogsPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Audit Logs" subtitle="System audit trail" icon={FileText} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <FileText className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Audit Logs</h2>
          <p className="text-muted-foreground">Audit log management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
