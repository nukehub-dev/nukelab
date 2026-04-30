import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { Settings, Palette, Bell, Shield, Construction } from 'lucide-react';
import { useEffect } from 'react';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { useAuthStore } from '../stores/auth-store';

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
});

function SettingsPage() {
  const navigate = useNavigate();
  const isAdmin = useAuthStore((state) => state.isAdmin());

  useEffect(() => {
    if (!isAdmin) {
      navigate({ to: '/' });
    }
  }, [isAdmin, navigate]);

  if (!isAdmin) return null;

  return (
    <ResourcePageLayout
      title="Settings"
      subtitle="Platform configuration"
      icon={Settings}
      stats={[
        { title: 'Themes', value: 8, icon: Palette, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
        { title: 'Notifications', value: 'On', icon: Bell, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Security', value: 'High', icon: Shield, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
      ]}
    >
      <div className="bubble p-12 text-center">
        <Construction className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
        <h2 className="text-lg font-semibold mb-2">Coming Soon</h2>
        <p className="text-muted-foreground">
          Settings management is under development. Check back soon for updates.
        </p>
      </div>
    </ResourcePageLayout>
  );
}
