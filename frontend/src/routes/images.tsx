import { createFileRoute } from '@tanstack/react-router';
import { Image } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/images')({
  component: ImagesPage,
});

function ImagesPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Images" subtitle="Manage container images" icon={Image} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <Image className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Images</h2>
          <p className="text-muted-foreground">Image management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
