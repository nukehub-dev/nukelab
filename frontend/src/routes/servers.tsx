import { createFileRoute } from '@tanstack/react-router';
import { Server, Activity, Cpu, MemoryStick } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/servers')({
  component: ServersPage,
});

function ServersPage() {
  return (
    <PlaceholderPage
      title="Servers"
      subtitle="Manage your simulation servers"
      icon={Server}
      description="Server management interface with real-time status monitoring and deployment controls."
      stats={[
        { title: 'Active Servers', value: 12, icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
        { title: 'CPU Usage', value: '67%', icon: Cpu, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Memory', value: '42.3 GB', icon: MemoryStick, iconColor: 'text-rose-400', bgColor: 'bg-rose-500/10' },
        { title: 'Uptime', value: '99.9%', icon: Activity, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
      ]}
    />
  );
}
