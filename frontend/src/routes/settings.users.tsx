import { createFileRoute, Navigate } from '@tanstack/react-router';

export const Route = createFileRoute('/settings/users')({
  component: () => <Navigate to="/admin/users" replace />,
});
