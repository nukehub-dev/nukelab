import { createFileRoute, Outlet, useNavigate } from '@tanstack/react-router';
import { useEffect } from 'react';
import { useAuthStore } from '../stores/auth-store';

export const Route = createFileRoute('/admin')({
  component: AdminLayout,
});

function AdminLayout() {
  const canAccessAdmin = useAuthStore((state) => state.canAccessAdmin);
  const navigate = useNavigate();

  useEffect(() => {
    if (!canAccessAdmin()) {
      navigate({ to: '/' });
    }
  }, [canAccessAdmin, navigate]);

  if (!canAccessAdmin()) {
    return null;
  }

  return <Outlet />;
}
