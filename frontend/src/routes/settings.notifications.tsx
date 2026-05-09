import { createFileRoute } from '@tanstack/react-router';
import { Bell, Save, RotateCcw, Server, CreditCard, AlertTriangle, Calendar, Users, Check } from 'lucide-react';
import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';
import { useCurrentUser } from '../hooks/use-current-user';
import { api } from '../lib/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Checkbox } from '../components/ui/checkbox';

export const Route = createFileRoute('/settings/notifications')({
  component: NotificationsSettingsPage,
});

interface EventPreference {
  event: string;
  label: string;
  description: string;
  icon: React.ElementType;
  channels: Record<string, boolean>;
}

const defaultEvents: EventPreference[] = [
  { event: 'server_start', label: 'Server Started', description: 'When a server is started', icon: Server, channels: { email: false, webhook: false, in_app: true } },
  { event: 'server_stop', label: 'Server Stopped', description: 'When a server is stopped', icon: Server, channels: { email: false, webhook: false, in_app: true } },
  { event: 'server_ready', label: 'Server Ready', description: 'When a server is ready to use', icon: Server, channels: { email: true, webhook: false, in_app: true } },
  { event: 'credit_low', label: 'Low Credits', description: 'When your credit balance is low', icon: CreditCard, channels: { email: true, webhook: true, in_app: true } },
  { event: 'credit_granted', label: 'Credits Granted', description: 'When credits are added to your account', icon: CreditCard, channels: { email: true, webhook: false, in_app: true } },
  { event: 'queue_position', label: 'Queue Position', description: 'Updates on your queue position', icon: Users, channels: { email: false, webhook: false, in_app: true } },
  { event: 'schedule_run', label: 'Schedule Executed', description: 'When a scheduled task runs', icon: Calendar, channels: { email: false, webhook: false, in_app: true } },
  { event: 'alert_fired', label: 'Alert Fired', description: 'When a system alert is triggered', icon: AlertTriangle, channels: { email: true, webhook: true, in_app: true } },
  { event: 'maintenance', label: 'Maintenance Mode', description: 'System maintenance notifications', icon: AlertTriangle, channels: { email: true, webhook: true, in_app: true } },
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

  // Calculate summary stats
  const totalEnabled = preferences.reduce((acc, pref) => 
    acc + Object.values(pref.channels).filter(Boolean).length, 0
  );

  return (
    <div className="space-y-10 pb-10">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
            <Bell className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h2 className="text-2xl font-bold">Notifications</h2>
            <p className="text-muted-foreground">Configure notification preferences</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold">{totalEnabled}</p>
          <p className="text-xs text-muted-foreground">Active notifications</p>
        </div>
      </motion.div>

      <div className="space-y-8">
        {/* Webhook URL */}
        <SettingsSection title="Webhook URL" description="Configure a webhook endpoint to receive notifications.">
          <div className="flex items-start gap-4">
            <div className="flex-1">
              <Input
                value={webhookUrl}
                onChange={(e) => { setWebhookUrl(e.target.value); setSaved(false); }}
                placeholder="https://hooks.example.com/nukelab"
              />
              <p className="text-xs text-muted-foreground mt-2">
                Notifications will be sent as POST requests with HMAC-SHA256 signatures.
              </p>
            </div>
          </div>
        </SettingsSection>

        {/* Event Preferences */}
        <SettingsSection 
          title="Event Preferences" 
          description="Choose how you want to receive notifications for each event."
        >
          <div className="rounded-xl border border-border/50 overflow-hidden">
            {/* Table Header */}
            <div className="grid grid-cols-[1fr_80px_80px_80px] gap-2 px-4 py-3 bg-muted/30 border-b border-border/50 text-sm font-medium text-muted-foreground">
              <span>Event</span>
              <span className="text-center">Email</span>
              <span className="text-center">Webhook</span>
              <span className="text-center">In-App</span>
            </div>

            {/* Event Rows */}
            <div className="divide-y divide-border/30">
              {preferences.map((pref, index) => {
                const Icon = pref.icon;
                return (
                  <div
                    key={pref.event}
                    className="grid grid-cols-[1fr_80px_80px_80px] gap-2 px-4 py-4 items-center hover:bg-accent/10 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                        <Icon className="w-4 h-4 text-muted-foreground" />
                      </div>
                      <div>
                        <p className="text-sm font-medium">{pref.label}</p>
                        <p className="text-xs text-muted-foreground">{pref.description}</p>
                      </div>
                    </div>
                    
                    <div className="flex justify-center">
                      <Checkbox
                        checked={pref.channels.email}
                        onChange={() => toggleChannel(index, 'email')}
                      />
                    </div>
                    <div className="flex justify-center">
                      <Checkbox
                        checked={pref.channels.webhook}
                        onChange={() => toggleChannel(index, 'webhook')}
                      />
                    </div>
                    <div className="flex justify-center">
                      <Checkbox
                        checked={pref.channels.in_app}
                        onChange={() => toggleChannel(index, 'in_app')}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </SettingsSection>

        {/* Quick Actions */}
        <SettingsSection title="Quick Actions" description="Enable or disable all notifications at once.">
          <div className="flex gap-4">
            <Button 
              variant="outline" 
              onClick={() => {
                setPreferences(prev => prev.map(p => ({
                  ...p,
                  channels: { email: true, webhook: true, in_app: true }
                })));
                setSaved(false);
              }}
              className="gap-2"
            >
              <Check className="w-4 h-4" />
              Enable All
            </Button>
            <Button 
              variant="outline" 
              onClick={() => {
                setPreferences(prev => prev.map(p => ({
                  ...p,
                  channels: { email: false, webhook: false, in_app: false }
                })));
                setSaved(false);
              }}
              className="gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              Disable All
            </Button>
          </div>
        </SettingsSection>

        {/* Actions */}
        <motion.div
          className="flex items-center gap-3 pt-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
        >
          <Button onClick={handleSave} loading={saving} className="gap-2">
            <Save className="w-4 h-4" />
            Save Preferences
          </Button>
          <Button variant="ghost" onClick={handleReset} className="gap-2">
            Reset to Defaults
          </Button>
          {saved && (
            <motion.span
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="text-sm text-emerald-400 font-medium flex items-center gap-1"
            >
              <Check className="w-4 h-4" />
              Saved successfully!
            </motion.span>
          )}
        </motion.div>
      </div>
    </div>
  );
}

function SettingsSection({ 
  title, 
  description, 
  children 
}: { 
  title?: string; 
  description?: string; 
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      {(title || description) && (
        <div className="mb-4">
          {title && <h3 className="text-lg font-semibold">{title}</h3>}
          {description && (
            <p className="text-sm text-muted-foreground mt-1">{description}</p>
          )}
        </div>
      )}
      <div>{children}</div>
    </motion.div>
  );
}
