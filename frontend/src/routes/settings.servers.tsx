import { createFileRoute, Link } from '@tanstack/react-router';
import { motion } from 'framer-motion';
import { Server, ArrowLeft, Clock, Power, AlertTriangle } from 'lucide-react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCurrentUser } from '../hooks/use-current-user';
import { api } from '../lib/api';
import { useToast } from '../stores/toast-store';
import { cn } from '../lib/utils';
import { Switch } from '../components/ui/switch';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';

export const Route = createFileRoute('/settings/servers')({
  component: ServerBehaviorSettingsPage,
});

const TIMEOUT_OPTIONS = [
  { value: 15, label: '15 minutes' },
  { value: 30, label: '30 minutes' },
  { value: 60, label: '1 hour' },
  { value: 120, label: '2 hours' },
];

function ServerBehaviorSettingsPage() {
  const { data: user } = useCurrentUser();
  const queryClient = useQueryClient();
  const { error } = useToast();

  const [idleEnabled, setIdleEnabled] = useState(true);
  const [idleTimeout, setIdleTimeout] = useState(15);
  const [stopOnLogout, setStopOnLogout] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');

  // Load saved preferences
  useEffect(() => {
    if (user?.preferences) {
      const prefs = user.preferences;
      if (typeof prefs.idle_shutdown_enabled === 'boolean') {
        setIdleEnabled(prefs.idle_shutdown_enabled);
      }
      if (typeof prefs.idle_shutdown_timeout === 'number') {
        setIdleTimeout(prefs.idle_shutdown_timeout);
      }
      if (typeof prefs.stop_on_logout === 'boolean') {
        setStopOnLogout(prefs.stop_on_logout);
      }
    }
  }, [user]);

  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const saveMutation = useMutation({
    mutationFn: async (payload: { idle_shutdown_enabled: boolean; idle_shutdown_timeout: number; stop_on_logout: boolean }) => {
      return api.put('/preferences/', payload);
    },
    onSuccess: (_result, variables) => {
      setSaveStatus('saved');
      queryClient.setQueryData(['me'], (old: any) => {
        if (!old) return old;
        return {
          ...old,
          preferences: {
            ...(old.preferences || {}),
            ...variables,
          },
        };
      });
      setTimeout(() => setSaveStatus('idle'), 2000);
    },
    onError: (err: any) => {
      setSaveStatus('idle');
      error('Failed to save preferences', err?.message || 'Please try again');
    },
  });

  const triggerSave = useCallback(
    (updates: Partial<{ idle_shutdown_enabled: boolean; idle_shutdown_timeout: number; stop_on_logout: boolean }>) => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
      setSaveStatus('saving');
      saveTimeoutRef.current = setTimeout(() => {
        saveMutation.mutate({
          idle_shutdown_enabled: updates.idle_shutdown_enabled ?? idleEnabled,
          idle_shutdown_timeout: updates.idle_shutdown_timeout ?? idleTimeout,
          stop_on_logout: updates.stop_on_logout ?? stopOnLogout,
        });
      }, 400);
    },
    [idleEnabled, idleTimeout, stopOnLogout, saveMutation]
  );

  const handleIdleToggle = (checked: boolean) => {
    setIdleEnabled(checked);
    triggerSave({ idle_shutdown_enabled: checked });
  };

  const handleTimeoutChange = (value: number) => {
    setIdleTimeout(value);
    triggerSave({ idle_shutdown_timeout: value });
  };

  const handleLogoutToggle = (checked: boolean) => {
    setStopOnLogout(checked);
    triggerSave({ stop_on_logout: checked });
  };

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-10">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <Link
          to="/settings"
          className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="p-2 rounded-xl bg-primary/10">
          <Server className="w-5 h-5 text-primary" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold">Server Behavior</h1>
            {saveStatus !== 'idle' && (
              <span className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium transition-colors",
                saveStatus === 'saving'
                  ? "bg-muted text-muted-foreground"
                  : "bg-emerald-500/10 text-emerald-500"
              )}>
                {saveStatus === 'saving' ? 'Saving...' : 'Saved'}
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground">Configure automatic server management</p>
        </div>
      </motion.div>

      <div className="space-y-8">
        {/* Idle Shutdown */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <Card>
            <CardHeader>
              <CardTitle>Auto-Stop Idle Servers</CardTitle>
              <CardDescription>
                Automatically stop servers after a period of inactivity to save credits and free resources.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Toggle */}
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Clock className="w-4 h-4 text-muted-foreground" />
                    <h3 className="text-base font-semibold">Enable Idle Shutdown</h3>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Stop servers when no activity is detected
                  </p>
                </div>
                <Switch checked={idleEnabled} onCheckedChange={handleIdleToggle} />
              </div>

              {/* Timeout selector */}
              <motion.div
                animate={{ opacity: idleEnabled ? 1 : 0.5, pointerEvents: idleEnabled ? 'auto' : 'none' }}
                transition={{ duration: 0.2 }}
              >
                <div>
                  <label className="text-sm font-medium block mb-3">Shutdown after</label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {TIMEOUT_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        onClick={() => handleTimeoutChange(option.value)}
                        className={cn(
                          "px-4 py-3 rounded-xl text-sm font-medium transition-all border",
                          idleTimeout === option.value
                            ? "border-primary bg-primary/5 text-primary"
                            : "border-border/50 bg-card/30 text-muted-foreground hover:border-border hover:bg-card/50"
                        )}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>

              {/* Warning */}
              <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-500/5 border border-amber-500/10">
                <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                <p className="text-sm text-amber-500/80">
                  Unsaved work may be lost when servers auto-stop. Make sure to save your work regularly.
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Stop on Logout */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
        >
          <Card>
            <CardHeader>
              <CardTitle>Stop on Logout</CardTitle>
              <CardDescription>
                Automatically stop all running servers when you explicitly log out.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Power className="w-4 h-4 text-muted-foreground" />
                    <h3 className="text-base font-semibold">Stop All Servers on Logout</h3>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Ends all running sessions when you click Logout
                  </p>
                </div>
                <Switch checked={stopOnLogout} onCheckedChange={handleLogoutToggle} />
              </div>

              <div className="flex items-start gap-3 p-4 rounded-xl bg-rose-500/5 border border-rose-500/10">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <p className="text-sm text-rose-400/80">
                  This is an aggressive setting. Any background jobs or unsaved work will be lost when you log out.
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  );
}
