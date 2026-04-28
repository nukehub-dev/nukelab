'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuthStore } from '@/stores/authStore';
import { adminApi, serversApi, creditsApi } from '@/lib/api';
import { 
  Users, 
  Server, 
  CreditCard, 
  Activity,
  ArrowRight
} from 'lucide-react';

export default function DashboardPage() {
  const { user, isAdmin } = useAuthStore();
  const [stats, setStats] = useState<any>(null);
  const [servers, setServers] = useState<any[]>([]);
  const [credits, setCredits] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Fetch servers
        const serversData = await serversApi.list();
        setServers(serversData.servers || []);
        
        // Fetch credits
        const creditsData = await creditsApi.getMyCredits();
        setCredits(creditsData);
        
        // Fetch admin stats if admin
        if (isAdmin()) {
          const statsData = await adminApi.getStats();
          setStats(statsData);
        }
      } catch (error) {
        console.error('Error fetching dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [isAdmin]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  const statCards = [
    {
      name: 'My Servers',
      value: servers.length,
      icon: Server,
      href: '/dashboard/servers',
      color: 'bg-blue-500'
    },
    {
      name: 'Credit Balance',
      value: credits?.balance || 0,
      icon: CreditCard,
      href: '/dashboard/credits',
      color: 'bg-green-500'
    },
    {
      name: 'Daily Allowance',
      value: credits?.daily_allowance || 0,
      icon: Activity,
      href: '/dashboard/credits',
      color: 'bg-purple-500'
    }
  ];

  if (isAdmin() && stats) {
    statCards.push(
      {
        name: 'Total Users',
        value: stats.users?.total || 0,
        icon: Users,
        href: '/dashboard/admin/users',
        color: 'bg-orange-500'
      },
      {
        name: 'Running Servers',
        value: stats.servers?.running || 0,
        icon: Server,
        href: '/dashboard/admin',
        color: 'bg-red-500'
      }
    );
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">
          Welcome, {user?.username}!
        </h1>
        <p className="mt-2 text-gray-600">
          Here's what's happening with your account
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {statCards.map((card) => (
          <Link
            key={card.name}
            href={card.href}
            className="bg-white rounded-lg shadow p-6 hover:shadow-md transition-shadow"
          >
            <div className="flex items-center">
              <div className={`${card.color} rounded-lg p-3`}>
                <card.icon className="w-6 h-6 text-white" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{card.name}</p>
                <p className="text-2xl font-bold text-gray-900">{card.value}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="bg-white rounded-lg shadow p-6 mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link
            href="/dashboard/servers"
            className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center">
              <Server className="w-5 h-5 text-blue-600 mr-3" />
              <span className="font-medium">Manage Servers</span>
            </div>
            <ArrowRight className="w-5 h-5 text-gray-400" />
          </Link>
          
          <Link
            href="/dashboard/profile"
            className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center">
              <Users className="w-5 h-5 text-green-600 mr-3" />
              <span className="font-medium">Edit Profile</span>
            </div>
            <ArrowRight className="w-5 h-5 text-gray-400" />
          </Link>
          
          {isAdmin() && (
            <Link
              href="/dashboard/admin"
              className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center">
                <Activity className="w-5 h-5 text-purple-600 mr-3" />
                <span className="font-medium">Admin Dashboard</span>
              </div>
              <ArrowRight className="w-5 h-5 text-gray-400" />
            </Link>
          )}
        </div>
      </div>

      {/* Recent Servers */}
      {servers.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">My Servers</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {servers.slice(0, 5).map((server: any) => (
                  <tr key={server.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {server.name}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                        server.status === 'running' 
                          ? 'bg-green-100 text-green-800' 
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {server.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(server.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
