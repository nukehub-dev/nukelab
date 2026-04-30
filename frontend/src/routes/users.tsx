import { createFileRoute } from '@tanstack/react-router';
import { Users, Shield, UserCheck, UserX } from 'lucide-react';
import { PlaceholderPage } from '../components/layout/placeholder-page';

export const Route = createFileRoute('/users')({
  component: UsersPage,
});

function UsersPage() {
  return (
    <PlaceholderPage
      title="Users"
      subtitle="Manage platform users"
      icon={Users}
      description="User management with role-based access control and activity tracking."
      stats={[
        { title: 'Total Users', value: 48, icon: Users, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
        { title: 'Active', value: 42, icon: UserCheck, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
        { title: 'Admins', value: 3, icon: Shield, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
        { title: 'Inactive', value: 6, icon: UserX, iconColor: 'text-gray-400', bgColor: 'bg-gray-500/10' },
      ]}
    />
  );
}
