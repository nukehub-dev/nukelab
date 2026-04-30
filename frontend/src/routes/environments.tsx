import { createFileRoute } from '@tanstack/react-router';
import { Boxes, Layers, GitBranch, Container } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/environments')({
  component: EnvironmentsPage,
});

function EnvironmentsPage() {
  return (
    <PlaceholderPage
      title="Environments"
      subtitle="Manage deployment environments"
      icon={Boxes}
      description="Environment management for staging, production, and development clusters."
      stats={[
        { title: 'Environments', value: 5, icon: Boxes, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Production', value: 2, icon: Layers, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
        { title: 'Staging', value: 2, icon: GitBranch, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Containers', value: 24, icon: Container, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
      ]}
    />
  );
}
