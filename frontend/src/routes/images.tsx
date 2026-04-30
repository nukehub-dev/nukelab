import { createFileRoute } from '@tanstack/react-router';
import { Image, Layers, HardDrive, Tag } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/images')({
  component: ImagesPage,
});

function ImagesPage() {
  return (
    <PlaceholderPage
      title="Images"
      subtitle="Manage container images"
      icon={Image}
      description="Container image registry management and version control."
      stats={[
        { title: 'Total Images', value: 156, icon: Image, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Layers', value: '2.4K', icon: Layers, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Storage', value: '12.5 GB', icon: HardDrive, iconColor: 'text-rose-400', bgColor: 'bg-rose-500/10' },
        { title: 'Versions', value: 48, icon: Tag, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
      ]}
    />
  );
}
