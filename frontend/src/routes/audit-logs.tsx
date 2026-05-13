import { createFileRoute, Navigate } from '@tanstack/react-router';

export const Route = createFileRoute('/audit-logs')({
  component: () => <Navigate to="/admin/audit-logs" replace />,
});
