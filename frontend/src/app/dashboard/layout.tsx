'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuthStore } from '@/stores/authStore';
import { 
  LayoutDashboard, 
  Users, 
  Server, 
  CreditCard, 
  Settings, 
  Shield,
  LogOut,
  User,
  Key
} from 'lucide-react';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { user, isAuthenticated, logout, isAdmin } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, router]);

  const handleLogout = () => {
    logout();
    router.push('/login');
  };

  if (!isAuthenticated) {
    return null;
  }

  const navigation = [
    { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
    { name: 'Profile', href: '/dashboard/profile', icon: User },
    { name: 'Servers', href: '/dashboard/servers', icon: Server },
    { name: 'Credits', href: '/dashboard/credits', icon: CreditCard },
    { name: 'API Tokens', href: '/dashboard/tokens', icon: Key },
  ];

  const adminNavigation = [
    { name: 'Admin', href: '/dashboard/admin', icon: Shield },
    { name: 'Users', href: '/dashboard/admin/users', icon: Users },
    { name: 'Environments', href: '/dashboard/admin/environments', icon: Server },
    { name: 'Plans', href: '/dashboard/admin/plans', icon: CreditCard },
    { name: 'Settings', href: '/dashboard/settings', icon: Settings },
  ];

  return (
    <div className="min-h-screen bg-gray-100">
      <div className="flex">
        {/* Sidebar */}
        <div className="w-64 bg-white shadow-md min-h-screen">
          <div className="p-4 border-b">
            <h1 className="text-xl font-bold text-gray-900">NukeLab</h1>
            <p className="text-sm text-gray-500">v2.0</p>
          </div>
          
          <nav className="mt-4">
            <div className="px-4 py-2">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                Main
              </p>
            </div>
            {navigation.map((item) => (
              <Link
                key={item.name}
                href={item.href}
                className="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-50 hover:text-blue-600 transition-colors"
              >
                <item.icon className="w-5 h-5 mr-3" />
                {item.name}
              </Link>
            ))}
            
            {isAdmin() && (
              <>
                <div className="px-4 py-2 mt-4">
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    Admin
                  </p>
                </div>
                {adminNavigation.map((item) => (
                  <Link
                    key={item.name}
                    href={item.href}
                    className="flex items-center px-4 py-2 text-gray-700 hover:bg-gray-50 hover:text-blue-600 transition-colors"
                  >
                    <item.icon className="w-5 h-5 mr-3" />
                    {item.name}
                  </Link>
                ))}
              </>
            )}
          </nav>
          
          <div className="absolute bottom-0 w-64 p-4 border-t bg-white">
            <div className="flex items-center mb-3">
              <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold">
                {user?.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="ml-3">
                <p className="text-sm font-medium text-gray-900">{user?.username}</p>
                <p className="text-xs text-gray-500">{user?.role}</p>
              </div>
            </div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-gray-600">Credits:</span>
              <span className="text-sm font-bold text-green-600">{user?.credit_balance}</span>
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center w-full px-4 py-2 text-sm text-red-600 hover:bg-red-50 rounded-md transition-colors"
            >
              <LogOut className="w-4 h-4 mr-2" />
              Logout
            </button>
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 p-8">
          {children}
        </div>
      </div>
    </div>
  );
}
