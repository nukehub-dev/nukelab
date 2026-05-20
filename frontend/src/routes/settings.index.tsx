import { createFileRoute, Link } from '@tanstack/react-router';
import { Palette, Bell, UserCircle, ChevronRight, KeyRound, Settings, Zap } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../lib/utils';

interface SettingsCategory {
  label: string;
  description: string;
  icon: React.ElementType;
  href: string;
  requiredPermission?: string;
  color: string;
}

const categories: SettingsCategory[] = [
  {
    label: 'Profile',
    description: 'Manage your account information and avatar',
    icon: UserCircle,
    href: '/settings/profile',
    color: 'bg-primary/10 text-primary',
  },
  {
    label: 'Appearance',
    description: 'Customize the look and feel of NukeLab',
    icon: Palette,
    href: '/settings/appearance',
    color: 'bg-violet-500/10 text-violet-400',
  },
  {
    label: 'Notifications',
    description: 'Configure notification preferences',
    icon: Bell,
    href: '/settings/notifications',
    color: 'bg-blue-500/10 text-blue-400',
  },
  {
    label: 'Credits',
    description: 'View your credit balance and transaction history',
    icon: Zap,
    href: '/settings/credits',
    color: 'bg-amber-500/10 text-amber-400',
  },
  {
    label: 'API Tokens',
    description: 'Manage personal access tokens for API and CLI access',
    icon: KeyRound,
    href: '/settings/tokens',
    color: 'bg-rose-500/10 text-rose-400',
  },
];

export const Route = createFileRoute('/settings/')({
  component: SettingsIndexPage,
});

function SettingsIndexPage() {
  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <div className="p-2 rounded-xl bg-primary/10">
          <Settings className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Settings</h1>
          <p className="text-sm text-muted-foreground">Manage your platform preferences and configuration</p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {categories.map((category, i) => (
          <motion.div
            key={category.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1, duration: 0.4 }}
            className="h-full"
          >
            <Link
              to={category.href}
              className="group flex items-start gap-4 p-5 rounded-xl bg-card/50 border border-border/50 hover:border-primary/30 hover:bg-card/80 transition-all duration-200 h-full"
            >
              <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center shrink-0", category.color)}>
                <category.icon className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-base group-hover:text-primary transition-colors">{category.label}</h3>
                  {category.requiredPermission && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">Admin</span>
                  )}
                </div>
                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{category.description}</p>
              </div>
              <ChevronRight className="w-5 h-5 text-muted-foreground/50 group-hover:text-muted-foreground group-hover:translate-x-0.5 transition-all shrink-0 mt-1" />
            </Link>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
