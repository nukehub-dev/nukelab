import { createFileRoute } from '@tanstack/react-router';
import { Bell, Mail, Globe, Smartphone, Save, RotateCcw } from 'lucide-react';
import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';
import { useCurrentUser } from '../hooks/use-current-user';
import { api } from '../lib/api';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';

export const Route = createFileRoute('/settings/notifications')({
  component: NotificationsSettingsPage,
});

interface NotificationChannel {
  id: string;
  label: string;
  icon: React.ElementType;
  description: string;
}

interface EventPreference {
  event: string;
  label: string;
  channels: Record<string, boolean>;
}

const channels: NotificationChannel[] = [
  { id: 'email', label: 'Email', icon: Mail, description: 'Receive email notifications' },
  { id: 'webhook', label: 'Webhook', icon: Globe, description: 'Send to webhook URL' },
  { id: 'in_app', label: 'In-App', icon: Smartphone, description: 'Show in notification center' },
];

const defaultEvents: EventPreference[] = [
  { event: 'server_start', label: 'Server Started', channels: { email: false, webhook: false, in_app: true } },
  { event: 'server_stop', label: 'Server Stopped', channels: { email: false, webhook: false, in_app: true } },
  { event: 'server_ready', label: 'Server Ready', channels: { email: true, webhook: false, in_app: true } },
  { event: 'credit_low', label: 'Low Credits', channels: { email: true, webhook: true, in_app: true } },
  { event: 'credit_granted', label: 'Credits Granted', channels: { email: true, webhook: false, in_app: true } },
  { event: 'queue_position', label: 'Queue Position', channels: { email: false, webhook: false, in_app: true } },
  { event: 'schedule_run', label: 'Schedule Executed', channels: { email: false, webhook: false, in_app: true } },
  { event: 'alert_fired', label: 'Alert Fired', channels: { email: true, webhook: true, in_app: true } },
  { event: 'maintenance', label: 'Maintenance Mode', channels: { email: true, webhook: true, in_app: true } },
];

function NotificationsSettingsPage() {
  const { data: user } = useCurrentUser();
  const [preferences, setPreferences] = useState<EventPreference[]>(defaultEvents);
  const [webhookUrl, setWebhookUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (user?.preferences?.notifications) {
      const saved = user.preferences.notifications;
      if (saved.events) {
        setPreferences(saved.events);
      }
      if (saved.webhook_url) {
        setWebhookUrl(saved.webhook_url);
      }
    }
  }, [user]);

  const toggleChannel = (eventIndex: number, channelId: string) => {
    setPreferences((prev) => {
      const updated = [...prev];
      updated[eventIndex] = {
        ...updated[eventIndex],
        channels: {
          ...updated[eventIndex].channels,
          [channelId]: !updated[eventIndex].channels[channelId],
        },
      };
      return updated;
    });
    setSaved(false);
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      await api.put('/users/me/preferences', {
        notifications: {
          events: preferences,
          webhook_url: webhookUrl,
        },
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (error) {
      console.error('Failed to save preferences:', error);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setPreferences(defaultEvents);
    setWebhookUrl('');
    setSaved(false);
  };

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

      <div className="space-y-6">
        {/* Webhook Configuration */}
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, ...springs.gentle }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Globe className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold">Webhook URL</h3>
          </div>
          <Input
            value={webhookUrl}
            onChange={(e) => { setWebhookUrl(e.target.value); setSaved(false); }}
            placeholder="https://hooks.example.com/nukelab"
            className="max-w-md"
          />
          <p className="text-xs text-muted-foreground mt-2">
            Webhook notifications will be sent as POST requests with HMAC-SHA256 signatures.
          </p>
        </motion.div>

        {/* Event Preferences */}
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, ...springs.gentle }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Bell className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold">Event Preferences</h3>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-2 px-3 text-sm font-medium text-muted-foreground">Event</th>
                  {channels.map((ch) => (
                    <th key={ch.id} className="text-center py-2 px-3 text-sm font-medium text-muted-foreground">
                      <div className="flex flex-col items-center gap-1">
                        <ch.icon className="w-4 h-4" />
                        <span>{ch.label}</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preferences.map((pref, eventIndex) => (
                  <tr key={pref.event} className="border-b border-border/50 last:border-0">
                    <td className="py-3 px-3 text-sm">{pref.label}</td>
                    {channels.map((ch) => (
                      <td key={ch.id} className="py-3 px-3 text-center">
                        <button
                          onClick={() => toggleChannel(eventIndex, ch.id)}
                          className={cn(
                            "w-5 h-5 rounded border transition-colors flex items-center justify-center",
                            pref.channels[ch.id]
                              ? "bg-primary border-primary text-primary-foreground"
                              : "border-border hover:border-primary/50"
                          )}
                        >
                          {pref.channels[ch.id] && (
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </button>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>

        {/* Actions */}
        <motion.div
          className="flex items-center gap-3"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, ...springs.gentle }}
        >
          <Button onClick={handleSave} loading={saving} className="gap-2">
            <Save className="w-4 h-4" />
            Save Preferences
          </Button>
          <Button variant="outline" onClick={handleReset} className="gap-2">
            <RotateCcw className="w-4 h-4" />
            Reset
          </Button>
          {saved && (
            <span className="text-sm text-emerald-400">Saved successfully!</span>
          )}
        </motion.div>
      </div>
    </div>
  );
}
