import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/admin/credits')({
  component: () => (
    <div className="flex items-center justify-center h-64">
      <p className="text-muted-foreground">Credit management will be added here.</p>
    </div>
  ),
});
