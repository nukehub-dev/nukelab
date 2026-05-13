import { createFileRoute, Navigate } from '@tanstack/react-router';

export const Route = createFileRoute('/settings/authentication')({
  component: () => <Navigate to="/admin/settings" replace />,
});
