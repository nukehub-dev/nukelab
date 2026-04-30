import { createFileRoute } from '@tanstack/react-router';
import { Settings, Palette, Bell, Shield } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
});

function SettingsPage() {
  return (
    <PlaceholderPage
      title="Settings"
      subtitle="Platform configuration"
      icon={Settings}
      description="Configure platform settings, themes, notifications, and security policies."
      stats={[
        { title: 'Themes', value: 8, icon: Palette, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
        { title: 'Notifications', value: 'On', icon: Bell, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Security', value: 'High', icon: Shield, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
      ]}
      showTable={false}
    />
  );
}
