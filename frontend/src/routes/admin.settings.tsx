import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/admin/settings')({
  component: () => (
    <div className="flex items-center justify-center h-64">
      <p className="text-muted-foreground">System settings will be migrated here in Phase 2.</p>
    </div>
  ),
});
