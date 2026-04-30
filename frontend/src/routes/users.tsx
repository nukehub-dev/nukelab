import { createFileRoute } from '@tanstack/react-router';
import { Users } from 'lucide-react';
import { PageHeader } from '../components/layout/page-header';

export const Route = createFileRoute('/users')({
  component: UsersPage,
});

function UsersPage() {
  return (
    <div className="min-h-screen">
      <PageHeader title="Users" subtitle="Manage platform users" icon={Users} />
      <div className="p-6 lg:p-10">
        <div className="bubble p-8 text-center">
          <Users className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Users</h2>
          <p className="text-muted-foreground">User management coming in Phase 2</p>
        </div>
      </div>
    </div>
  );
}
