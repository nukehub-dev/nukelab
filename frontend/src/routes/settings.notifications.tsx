import { createFileRoute } from '@tanstack/react-router';
import { Bell } from 'lucide-react';
import { motion } from 'framer-motion';

export const Route = createFileRoute('/settings/notifications')({
  component: NotificationsSettingsPage,
});

function NotificationsSettingsPage() {
  return (
    <div className="space-y-8">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-4 p-6 rounded-2xl bg-card/60 border border-border/50 backdrop-blur-xl"
      >
        <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center">
          <Bell className="w-6 h-6 text-blue-400" />
        </div>
        <div>
          <h2 className="text-2xl font-bold">Notifications</h2>
          <p className="text-muted-foreground">Configure notification preferences</p>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="p-12 text-center rounded-2xl bg-card/40 border border-border/50"
      >
        <Bell className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
        <h3 className="text-lg font-semibold mb-2">Coming Soon</h3>
        <p className="text-muted-foreground">Notification settings will be available in a future update.</p>
      </motion.div>
    </div>
  );
}
