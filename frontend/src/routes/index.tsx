import { createFileRoute } from '@tanstack/react-router';
import { motion } from 'framer-motion';
import {
  LayoutDashboard,
  Server,
  Boxes,
  Activity,
  Cpu,
  MemoryStick,
  Network,
} from 'lucide-react';
import { staggerContainerVariants, staggerItemVariants } from '../lib/animations';
import { PageHeader } from '../components/layout/page-header';
import { StatCard } from '../components/data/stat-card';

export const Route = createFileRoute('/')({
  component: DashboardPage,
});

function DashboardPage() {
  const stats = [
    { title: 'Active Servers', value: 12, subtitle: '3 pending', icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Containers', value: 48, subtitle: '2 unhealthy', icon: Boxes, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'CPU Usage', value: '67%', subtitle: '8 cores active', icon: Cpu, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
    { title: 'Memory', value: '42.3 GB', subtitle: 'of 64 GB', icon: MemoryStick, iconColor: 'text-rose-400', bgColor: 'bg-rose-500/10' },
  ];

  return (
    <div className="min-h-screen">
      <PageHeader
        title="Dashboard"
        subtitle="Overview of your nuclear engineering simulation infrastructure"
        icon={LayoutDashboard}
      />

      <div className="p-6 lg:p-10 space-y-8">
        {/* Ambient background blobs */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10">
          <div className="absolute top-20 right-20 w-[400px] h-[400px] rounded-full bg-primary/10 blur-[80px] blob-float" />
          <div className="absolute bottom-20 left-40 w-[300px] h-[300px] rounded-full bg-chart-2/10 blur-[80px] blob-float" style={{ animationDelay: '-5s' }} />
        </div>

        {/* Stats Grid */}
        <motion.div
          variants={staggerContainerVariants}
          initial="hidden"
          animate="visible"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
        >
          {stats.map((stat) => (
            <motion.div key={stat.title} variants={staggerItemVariants}>
              <StatCard {...stat} />
            </motion.div>
          ))}
        </motion.div>

        {/* Quick Actions */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="bubble p-6"
        >
          <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Deploy Server', icon: Server, color: 'bg-primary/10 text-primary' },
              { label: 'New Environment', icon: Boxes, color: 'bg-chart-2/10 text-chart-2' },
              { label: 'View Logs', icon: Activity, color: 'bg-chart-3/10 text-chart-3' },
              { label: 'Manage Network', icon: Network, color: 'bg-chart-4/10 text-chart-4' },
            ].map((action) => (
              <button
                key={action.label}
                className="flex flex-col items-center gap-3 p-4 rounded-xl border border-border/50 hover:border-primary/50 hover:bg-primary/5 transition-all duration-200 group"
              >
                <div className={cn("p-3 rounded-lg", action.color)}>
                  <action.icon className="w-5 h-5" />
                </div>
                <span className="text-sm font-medium">{action.label}</span>
              </button>
            ))}
          </div>
        </motion.div>

        {/* Recent Activity Placeholder */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="bubble p-6"
        >
          <h2 className="text-lg font-semibold mb-4">Recent Activity</h2>
          <div className="space-y-3">
            {[
              { action: 'Server deployed', target: 'sim-reactor-01', time: '2 min ago', status: 'success' },
              { action: 'Container stopped', target: 'nginx-proxy', time: '15 min ago', status: 'warning' },
              { action: 'Environment created', target: 'prod-cluster', time: '1 hour ago', status: 'success' },
              { action: 'Volume mounted', target: 'data-vol-3', time: '2 hours ago', status: 'info' },
            ].map((item, i) => (
              <div key={i} className="flex items-center gap-4 p-3 rounded-lg hover:bg-accent/50 transition-colors">
                <div className={cn(
                  "w-2 h-2 rounded-full",
                  item.status === 'success' && "bg-emerald-400",
                  item.status === 'warning' && "bg-amber-400",
                  item.status === 'info' && "bg-blue-400"
                )} />
                <div className="flex-1">
                  <span className="font-medium">{item.action}</span>
                  <span className="text-muted-foreground mx-2">on</span>
                  <span className="font-mono text-sm">{item.target}</span>
                </div>
                <span className="text-sm text-muted-foreground">{item.time}</span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}

function cn(...inputs: (string | undefined | false | null)[]) {
  return inputs.filter(Boolean).join(' ');
}
