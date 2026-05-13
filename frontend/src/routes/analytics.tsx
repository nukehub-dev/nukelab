import { createFileRoute, Navigate } from '@tanstack/react-router';

export const Route = createFileRoute('/analytics')({
  component: () => <Navigate to="/admin/analytics" replace />,
});
