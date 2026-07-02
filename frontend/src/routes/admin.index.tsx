// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import {
  Users,
  Server,
  BarChart3,
  FileText,
  CreditCard,
  Boxes,
  Shield,
  Settings,
  ChevronRight,
  LayoutDashboard,
  Gauge,
  FolderOpen,
  HardDrive,
  HeartPulse,
  GlobeLock,
  Wrench,
  Monitor,
  Flame,
  Bell,
  ExternalLink,
  Activity,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { cn } from '../lib/utils'
import { refreshAccessToken } from '../lib/api'

function getMonitoringUrl(redirect = '/grafana', token?: string | null): string {
  const accessToken =
    token ?? (typeof window !== 'undefined' ? localStorage.getItem('nukelab-token') : null)
  const base = import.meta.env.VITE_MONITORING_BASE_URL || import.meta.env.VITE_API_URL || '/api'
  return `${base.replace(/\/$/, '')}/auth/monitoring?redirect=${encodeURIComponent(redirect)}&token=${encodeURIComponent(accessToken || '')}`
}

async function openMonitoringTool(redirect: string) {
  const refreshed = await refreshAccessToken()
  if (!refreshed) {
    window.location.href = '/login'
    return
  }
  const token = localStorage.getItem('nukelab-token')
  const url = getMonitoringUrl(redirect, token)
  const a = document.createElement('a')
  a.href = url
  a.target = '_blank'
  a.rel = 'noopener noreferrer'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

interface AdminCategory {
  label: string
  description: string
  icon: React.ElementType
  href: string
  requiredPermission?: string
  color: string
  external?: boolean
}

const categories: AdminCategory[] = [
  {
    label: 'Users',
    description: 'Manage user accounts, roles, and access',
    icon: Users,
    href: '/admin/users',
    requiredPermission: PERMISSIONS.USERS_READ,
    color: 'bg-blue-500/10 text-blue-400',
  },
  {
    label: 'Servers',
    description: 'View and manage all platform servers',
    icon: Server,
    href: '/admin/servers',
    requiredPermission: PERMISSIONS.SERVERS_READ_ALL,
    color: 'bg-emerald-500/10 text-emerald-400',
  },
  {
    label: 'Health',
    description: 'System services and container health monitoring',
    icon: HeartPulse,
    href: '/admin/health',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-rose-500/10 text-rose-400',
  },
  {
    label: 'Analytics',
    description: 'Platform-wide usage statistics and trends',
    icon: BarChart3,
    href: '/admin/analytics',
    requiredPermission: PERMISSIONS.ANALYTICS_READ,
    color: 'bg-violet-500/10 text-violet-400',
  },
  {
    label: 'Audit Logs',
    description: 'Review system activity and changes',
    icon: FileText,
    href: '/admin/audit-logs',
    requiredPermission: PERMISSIONS.AUDIT_READ,
    color: 'bg-amber-500/10 text-amber-400',
  },
  {
    label: 'Credits',
    description: 'Manage user credits and balances',
    icon: CreditCard,
    href: '/admin/credits',
    requiredPermission: PERMISSIONS.CREDITS_READ_ALL,
    color: 'bg-rose-500/10 text-rose-400',
  },
  {
    label: 'Environments',
    description: 'Configure deployment environments',
    icon: Boxes,
    href: '/admin/environments',
    requiredPermission: PERMISSIONS.ENVIRONMENT_CREATE,
    color: 'bg-cyan-500/10 text-cyan-400',
  },
  {
    label: 'Plans',
    description: 'Manage server plans and pricing',
    icon: CreditCard,
    href: '/admin/plans',
    requiredPermission: PERMISSIONS.PLAN_CREATE,
    color: 'bg-orange-500/10 text-orange-400',
  },
  {
    label: 'Quotas',
    description: 'Manage per-user resource limits',
    icon: Gauge,
    href: '/admin/quotas',
    requiredPermission: PERMISSIONS.QUOTA_READ,
    color: 'bg-teal-500/10 text-teal-400',
  },
  {
    label: 'Workspaces',
    description: 'Manage all platform workspaces',
    icon: FolderOpen,
    href: '/admin/workspaces',
    requiredPermission: PERMISSIONS.WORKSPACES_READ_ALL,
    color: 'bg-indigo-500/10 text-indigo-400',
  },
  {
    label: 'Volumes',
    description: 'Manage all platform storage volumes',
    icon: HardDrive,
    href: '/admin/volumes',
    requiredPermission: PERMISSIONS.VOLUMES_READ_ALL,
    color: 'bg-pink-500/10 text-pink-400',
  },
  {
    label: 'Permissions',
    description: 'Configure roles and access control',
    icon: Shield,
    href: '/admin/permissions',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-purple-500/10 text-purple-400',
  },
  {
    label: 'IP Restrictions',
    description: 'Manage IP-based access restrictions',
    icon: GlobeLock,
    href: '/admin/ip-restrictions',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-red-500/10 text-red-400',
  },
  {
    label: 'Maintenance Windows',
    description: 'Schedule platform maintenance with auto enable/disable',
    icon: Wrench,
    href: '/admin/maintenance-windows',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-orange-500/10 text-orange-400',
  },
  {
    label: 'Settings',
    description: 'Platform-wide system settings',
    icon: Settings,
    href: '/admin/settings',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-primary/10 text-primary',
  },
  {
    label: 'Grafana',
    description: 'Metrics dashboards and visualizations',
    icon: Monitor,
    href: '/grafana',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-orange-500/10 text-orange-400',
    external: true,
  },
  {
    label: 'Prometheus',
    description: 'Time-series metrics and query explorer',
    icon: Flame,
    href: '/prometheus',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-yellow-500/10 text-yellow-400',
    external: true,
  },
  {
    label: 'Alertmanager',
    description: 'Alert routing, silences, and notifications',
    icon: Bell,
    href: '/alertmanager',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-red-500/10 text-red-400',
    external: true,
  },
  {
    label: 'Jaeger',
    description: 'Distributed trace search and visualization',
    icon: Activity,
    href: '/jaeger',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-purple-500/10 text-purple-400',
    external: true,
  },
]

export const Route = createFileRoute('/admin/')({
  component: AdminIndexPage,
})

function AdminIndexPage() {
  const hasPermission = useAuthStore((state) => state.hasPermission)

  const visibleCategories = categories.filter(
    (c) => !c.requiredPermission || hasPermission(c.requiredPermission)
  )

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <div className="p-2 rounded-xl bg-primary/10">
          <LayoutDashboard className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Administration</h1>
          <p className="text-sm text-muted-foreground">Platform management and configuration</p>
        </div>
      </motion.div>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {visibleCategories.map((category, i) => (
          <AdminCard key={category.label} category={category} index={i} />
        ))}
      </div>
    </div>
  )
}

function AdminCard({ category, index }: { category: AdminCategory; index: number }) {
  const content = (
    <>
      <div
        className={cn(
          'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
          category.color
        )}
      >
        <category.icon className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="font-semibold text-base group-hover:text-primary transition-colors">
          {category.label}
        </h3>
        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{category.description}</p>
      </div>
      {category.external ? (
        <ExternalLink className="w-5 h-5 text-muted-foreground/50 group-hover:text-muted-foreground transition-all shrink-0 mt-1" />
      ) : (
        <ChevronRight className="w-5 h-5 text-muted-foreground/50 group-hover:text-muted-foreground group-hover:translate-x-0.5 transition-all shrink-0 mt-1" />
      )}
    </>
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.4 }}
      className="h-full"
    >
      {category.external ? (
        <button
          onClick={() => openMonitoringTool(category.href)}
          className="group flex items-start gap-4 p-5 rounded-xl bg-card/50 border border-border/50 hover:border-primary/30 hover:bg-card/80 transition-all duration-200 h-full w-full text-left"
        >
          {content}
        </button>
      ) : (
        <Link
          to={category.href}
          className="group flex items-start gap-4 p-5 rounded-xl bg-card/50 border border-border/50 hover:border-primary/30 hover:bg-card/80 transition-all duration-200 h-full"
        >
          {content}
        </Link>
      )}
    </motion.div>
  )
}
