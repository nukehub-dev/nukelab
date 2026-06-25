import { createFileRoute, Outlet } from '@tanstack/react-router'

export const Route = createFileRoute('/servers')({
  component: ServersLayout,
})

function ServersLayout() {
  return <Outlet />
}
