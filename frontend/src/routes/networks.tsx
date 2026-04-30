import { createFileRoute } from '@tanstack/react-router';
import { Network, Globe, Shield, Activity, Construction } from 'lucide-react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';

export const Route = createFileRoute('/networks')({
  component: NetworksPage,
});

function NetworksPage() {
  return (
    <ResourcePageLayout
      title="Networks"
      subtitle="Manage container networks"
      icon={Network}
      stats={[
        { title: 'Networks', value: 0, icon: Network, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Subnets', value: 0, icon: Globe, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
        { title: 'Ingress Rules', value: 0, icon: Shield, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Traffic', value: '0 Gbps', icon: Activity, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
      ]}
    >
      <div className="bubble p-12 text-center">
        <Construction className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
        <h2 className="text-lg font-semibold mb-2">Coming Soon</h2>
        <p className="text-muted-foreground">
          Network management is under development. Check back soon for updates.
        </p>
      </div>
    </ResourcePageLayout>
  );
}
