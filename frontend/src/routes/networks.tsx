import { createFileRoute } from '@tanstack/react-router';
import { Network, Globe, Shield, Activity } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/networks')({
  component: NetworksPage,
});

function NetworksPage() {
  return (
    <PlaceholderPage
      title="Networks"
      subtitle="Manage container networks"
      icon={Network}
      description="Network configuration, ingress rules, and service mesh management."
      stats={[
        { title: 'Networks', value: 8, icon: Network, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Subnets', value: 12, icon: Globe, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
        { title: 'Ingress Rules', value: 24, icon: Shield, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Traffic', value: '1.2Gbps', icon: Activity, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
      ]}
    />
  );
}
