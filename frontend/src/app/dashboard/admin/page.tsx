'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { adminApi } from '@/lib/api';
import { 
  Users, 
  Server, 
  CreditCard, 
  Activity,
  TrendingUp,
  AlertTriangle
} from 'lucide-react';

export default function AdminDashboardPage() {
  const { isAdmin } = useAuthStore();
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isAdmin()) return;

    const fetchStats = async () => {
      try {
        const data = await adminApi.getStats();
        setStats(data);
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Failed to load admin stats');
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, [isAdmin]);

  if (!isAdmin()) {
    return (
      <div className="text-center py-12">
        <AlertTriangle className="w-12 h-12 text-yellow-500 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-gray-900">Access Denied</h2>
        <p className="text-gray-600 mt-2">You don't have permission to access this page.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
        {error}
      </div>
    );
  }

  const statCards = [
    {
      name: 'Total Users',
      value: stats?.users?.total || 0,
      icon: Users,
      color: 'bg-blue-500',
      subtext: `${stats?.users?.active || 0} active`
    },
    {
      name: 'Total Servers',
      value: stats?.servers?.total || 0,
      icon: Server,
      color: 'bg-green-500',
      subtext: `${stats?.servers?.running || 0} running`
    },
    {
      name: 'Credits Granted Today',
      value: stats?.credits?.granted_today || 0,
      icon: TrendingUp,
      color: 'bg-purple-500',
      subtext: `${stats?.credits?.consumed_today || 0} consumed`
    },
    {
      name: 'Low Credit Users',
      value: stats?.credits?.low_credit_users || 0,
      icon: AlertTriangle,
      color: 'bg-yellow-500',
      subtext: 'Need attention'
    }
  ];

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Admin Dashboard</h1>
        <p className="mt-2 text-gray-600">Platform overview and management</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {statCards.map((card) => (
          <div
            key={card.name}
            className="bg-white rounded-lg shadow p-6"
          >
            <div className="flex items-center">
              <div className={`${card.color} rounded-lg p-3`}>
                <card.icon className="w-6 h-6 text-white" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{card.name}</p>
                <p className="text-2xl font-bold text-gray-900">{card.value}</p>
                <p className="text-xs text-gray-500">{card.subtext}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Users by Role */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Users by Role</h2>
          <div className="space-y-3">
            {stats?.users?.by_role && Object.entries(stats.users.by_role).map(([role, count]: [string, any]) => (
              <div key={role} className="flex items-center justify-between">
                <span className="capitalize text-gray-700">{role.replace('_', ' ')}</span>
                <div className="flex items-center">
                  <div className="w-32 bg-gray-200 rounded-full h-2 mr-3">
                    <div
                      className="bg-blue-600 h-2 rounded-full"
                      style={{
                        width: `${stats.users.total > 0 ? (count / stats.users.total) * 100 : 0}%`
                      }}
                    />
                  </div>
                  <span className="text-sm font-medium text-gray-900">{count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Credit Overview</h2>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-gray-600">Total Credits in System</span>
              <span className="font-bold text-gray-900">{stats?.credits?.granted_today || 0}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-600">Consumed Today</span>
              <span className="font-bold text-red-600">{stats?.credits?.consumed_today || 0}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-600">Low Credit Users</span>
              <span className="font-bold text-yellow-600">{stats?.credits?.low_credit_users || 0}</span>
            </div>
            <div className="border-t pt-4">
              <p className="text-sm text-gray-500">
                Credits are automatically granted daily based on user role allowances.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
