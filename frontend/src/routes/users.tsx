import { createFileRoute, Navigate } from '@tanstack/react-router'

export const Route = createFileRoute('/users')({
  component: () => <Navigate to="/admin/users" replace />,
})
