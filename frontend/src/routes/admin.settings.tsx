import { createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import {
  Mail,
  Server,
  Network,
  User,
  Lock,
  Shield,
  Send,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ExternalLink,
  Bug,
  Wrench,
  Database,
  Save,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { PageHeader } from '../components/layout/page-header';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Tooltip } from '../components/ui/tooltip';
import { useToast } from '../stores/toast-store';
import {
  useEmailConfig,
  useEmailStatus,
  useEmailTest,
} from '../hooks/use-email-settings';
import {
  useSystemConfig,
  useUpdateSystemConfig,
} from '../hooks/use-system-config';
import {
  useRetentionPolicy,
  useUpdateRetentionPolicy,
  type RetentionPolicy,
} from '../hooks/use-retention';
import { cn } from '../lib/utils';
import { springs } from '../lib/animations';
import { usePageGuard } from '../hooks/use-page-guard';
import { PERMISSIONS } from '../stores/auth-store';
import { Switch } from '../components/ui/switch';

export const Route = createFileRoute('/admin/settings')({
  component: AdminSettingsPage,
});

function AdminSettingsPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ADMIN_ACCESS });
  if (!allowed) return null;

  const {
    data: config,
    isLoading: configLoading,
    isError: configError,
    error: configErrorObj,
    refetch: refetchConfig,
  } = useEmailConfig();
  const {
    data: status,
    isLoading: statusLoading,
    isError: statusError,
    refetch: refetchStatus,
  } = useEmailStatus();
  const emailTest = useEmailTest();
  const { success, error } = useToast();
  const [testEmail, setTestEmail] = useState('');
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  // Maintenance mode state
  const {
    data: sysConfig,
    isLoading: sysLoading,
    refetch: refetchSysConfig,
  } = useSystemConfig();
  const updateSysConfig = useUpdateSystemConfig();

  const handleMaintenanceToggle = (checked: boolean) => {
    updateSysConfig.mutate(
      {
        maintenance_mode: checked,
        maintenance_message: sysConfig?.maintenance_message || 'System under maintenance',
      },
      {
        onSuccess: () => {
          success(
            checked ? 'Maintenance mode enabled' : 'Maintenance mode disabled',
            checked
              ? 'Non-admin users will see a maintenance banner.'
              : 'The platform is now fully accessible.'
          );
        },
        onError: (err: any) => {
          error(
            'Failed to update maintenance mode',
            err?.response?.data?.detail || err.message
          );
        },
      }
    );
  };

  const handleMaintenanceMessageChange = (value: string) => {
    updateSysConfig.mutate(
      { maintenance_message: value },
      {
        onSuccess: () => success('Message updated', 'Maintenance message saved.'),
        onError: (err: any) => {
          error('Failed to update message', err?.response?.data?.detail || err.message);
        },
      }
    );
  };

  const handleTestEmail = () => {
    emailTest.mutate(testEmail || undefined, {
      onSuccess: (data) => {
        success('Test email sent', data.message);
      },
      onError: (err: any) => {
        error(
          'Failed to send test email',
          err?.response?.data?.detail || err.message
        );
      },
    });
  };

  // Retention policy state
  const {
    data: retentionPolicy,
    isLoading: retentionLoading,
    refetch: refetchRetention,
  } = useRetentionPolicy();
  const updateRetention = useUpdateRetentionPolicy();

  const [retentionEdits, setRetentionEdits] = useState<Partial<RetentionPolicy>>({});

  const handleRetentionChange = (key: keyof RetentionPolicy, value: number | boolean) => {
    setRetentionEdits((prev) => ({ ...prev, [key]: value }));
  };

  const handleSaveRetention = () => {
    if (Object.keys(retentionEdits).length === 0) return;
    updateRetention.mutate(retentionEdits, {
      onSuccess: () => {
        success('Retention policy updated', 'Data lifecycle settings saved.');
        setRetentionEdits({});
      },
      onError: (err: any) => {
        error('Failed to update retention policy', err?.response?.data?.detail || err.message);
      },
    });
  };

  const retentionGroups = [
    {
      title: 'Real-Time Metrics',
      description: 'High-resolution data collected every few minutes. Large volume, short retention.',
      fields: [
        { key: 'metrics_retention_days' as const, label: 'Server Metrics', desc: 'Per-server CPU, memory, network, disk stats', min: 7, max: 365 },
        { key: 'system_metrics_retention_days' as const, label: 'System Metrics', desc: 'Platform-wide resource usage', min: 7, max: 730 },
        { key: 'health_check_retention_days' as const, label: 'Health Checks', desc: 'Service health probe results', min: 7, max: 365 },
      ],
    },
    {
      title: 'Event History',
      description: 'User actions, system events, and alerts. Medium volume.',
      fields: [
        { key: 'alert_history_retention_days' as const, label: 'Alert History', desc: 'Triggered alerts and their status', min: 7, max: 730 },
        { key: 'activity_log_retention_days' as const, label: 'Activity Logs', desc: 'User actions (create, delete, update)', min: 30, max: 1825 },
        { key: 'notification_retention_days' as const, label: 'Notifications', desc: 'In-app and email notifications sent', min: 7, max: 365 },
      ],
    },
    {
      title: 'Aggregated Analytics',
      description: 'Daily summaries used for long-term trend analysis. Small volume, keep longer.',
      fields: [
        { key: 'daily_rollup_retention_days' as const, label: 'Daily Rollups', desc: 'Pre-aggregated daily stats for fast queries', min: 30, max: 1825 },
      ],
    },
  ];

  const isLoading = configLoading || statusLoading;
  const hasError = configError || statusError;

  const statusConfig = {
    connected: {
      icon: CheckCircle2,
      color: 'text-emerald-400',
      bg: 'bg-emerald-500/10',
      border: 'border-emerald-500/20',
      label: 'Connected',
    },
    error: {
      icon: AlertCircle,
      color: 'text-red-400',
      bg: 'bg-red-500/10',
      border: 'border-red-500/20',
      label: 'Connection Error',
    },
    disabled: {
      icon: AlertCircle,
      color: 'text-amber-400',
      bg: 'bg-amber-500/10',
      border: 'border-amber-500/20',
      label: 'Not Configured',
    },
  };

  const currentStatus = statusConfig[status?.status || 'disabled'];
  const StatusIcon = currentStatus.icon;

  const configFields = [
    { label: 'SMTP Host', value: config?.smtp_host || '—', icon: Server },
    { label: 'SMTP Port', value: config?.smtp_port?.toString() || '—', icon: Network },
    { label: 'Username', value: config?.smtp_user || '—', icon: User },
    { label: 'Password', value: config?.password_configured ? 'Configured' : 'Not set', icon: Lock },
    { label: 'From Address', value: config?.smtp_from || '—', icon: Mail },
    { label: 'From Name', value: config?.smtp_from_name || '—', icon: Mail },
    { label: 'TLS', value: config?.smtp_tls ? 'Enabled' : 'Disabled', icon: Shield },
    {
      label: 'Cert Verify',
      value: config?.smtp_verify_certs ? 'Enabled' : 'Disabled (dev mode)',
      icon: Shield,
    },
  ];

  return (
    <div className="min-h-screen space-y-6">
      <PageHeader
        title="System Settings"
        subtitle="Configure platform-wide settings and integrations"
        icon={Server}
        backTo="/admin"
      />

      <div className="px-6 lg:px-10 pb-10 space-y-6">
        {/* Maintenance Mode Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...springs.gentle, delay: 0.05 }}
          className="bubble space-y-5 p-6"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center">
                <Wrench className="w-5 h-5 text-amber-400" />
              </div>
              <div>
                <h3 className="font-semibold text-base">Maintenance Mode</h3>
                <p className="text-xs text-muted-foreground">
                  Control platform availability and display a message to users
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {!sysLoading && sysConfig && (
                <div
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
                    sysConfig.maintenance_mode
                      ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                      : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  )}
                >
                  {sysConfig.maintenance_mode ? (
                    <AlertCircle className="w-3.5 h-3.5" />
                  ) : (
                    <CheckCircle2 className="w-3.5 h-3.5" />
                  )}
                  {sysConfig.maintenance_mode ? 'Active' : 'Inactive'}
                </div>
              )}
              <Tooltip content="Refresh status">
                <button
                  onClick={() => refetchSysConfig()}
                  className="p-1.5 rounded-lg hover:bg-accent transition-colors"
                >
                  <RefreshCw className={cn('w-4 h-4 text-muted-foreground', sysLoading && 'animate-spin')} />
                </button>
              </Tooltip>
            </div>
          </div>

          {sysLoading ? (
            <div className="h-24 bg-muted/50 rounded-xl animate-pulse" />
          ) : (
            <div className="space-y-5">
              {/* Toggle */}
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <p className="text-sm font-medium">Enable Maintenance Mode</p>
                  <p className="text-xs text-muted-foreground">
                    When active, non-admin users will see a maintenance banner
                  </p>
                </div>
                <Switch
                  checked={sysConfig?.maintenance_mode || false}
                  onCheckedChange={handleMaintenanceToggle}
                  disabled={updateSysConfig.isPending}
                />
              </div>

              {/* Message input */}
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">
                  Maintenance message
                </label>
                <Input
                  value={sysConfig?.maintenance_message || ''}
                  onChange={(e) => handleMaintenanceMessageChange(e.target.value)}
                  placeholder="System under maintenance"
                  disabled={updateSysConfig.isPending}
                  className="h-9"
                />
              </div>

              <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/20 p-3 rounded-xl">
                <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>
                  Admin users can still access the platform during maintenance mode.
                  Use this to perform upgrades or critical maintenance without kicking admins out.
                </span>
              </div>
            </div>
          )}
        </motion.div>

      {/* Email Configuration Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="bubble space-y-5 p-6"
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Mail className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="font-semibold text-base">Email / SMTP</h3>
              <p className="text-xs text-muted-foreground">
                Configure email delivery for notifications and alerts
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!isLoading && (
              <div
                className={cn(
                  'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
                  currentStatus.bg,
                  currentStatus.color,
                  currentStatus.border
                )}
              >
                <StatusIcon className="w-3.5 h-3.5" />
                {currentStatus.label}
              </div>
            )}
            <Tooltip content="Refresh config & status">
              <button
                onClick={() => { refetchConfig(); refetchStatus(); }}
                className="p-1.5 rounded-lg hover:bg-accent transition-colors"
              >
                <RefreshCw className={cn('w-4 h-4 text-muted-foreground', isLoading && 'animate-spin')} />
              </button>
            </Tooltip>
          </div>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {configFields.map((_, i) => (
              <div key={i} className="h-16 bg-muted/50 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : hasError ? (
          <div className="p-4 rounded-xl bg-red-500/5 border border-red-500/10 text-red-400">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-sm">Failed to load email settings</p>
                <p className="text-xs mt-1 opacity-80">
                  {configError
                    ? `Config endpoint error: ${(configErrorObj as any)?.message || 'Unknown error'}`
                    : 'Status endpoint error'}
                </p>
                <button
                  onClick={() => { refetchConfig(); refetchStatus(); }}
                  className="text-xs mt-2 underline underline-offset-2 hover:opacity-80"
                >
                  Retry
                </button>
              </div>
            </div>
          </div>
        ) : (
          <>
            {/* Config Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {configFields.map((field) => (
                <div
                  key={field.label}
                  className="flex items-center gap-3 p-3 rounded-xl bg-muted/30 border border-border/30"
                >
                  <field.icon className="w-4 h-4 text-muted-foreground shrink-0" />
                  <div className="min-w-0">
                    <p className="text-[11px] text-muted-foreground uppercase tracking-wide">
                      {field.label}
                    </p>
                    <p className="text-sm font-medium truncate">{field.value}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* Status Message */}
            {status?.message && (
              <div
                className={cn(
                  'flex items-start gap-2.5 p-3 rounded-xl text-sm border',
                  status?.status === 'connected'
                    ? 'bg-emerald-500/5 border-emerald-500/10 text-emerald-400'
                    : status?.status === 'error'
                      ? 'bg-red-500/5 border-red-500/10 text-red-400'
                      : 'bg-amber-500/5 border-amber-500/10 text-amber-400'
                )}
              >
                <StatusIcon className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{status.message}</span>
              </div>
            )}

            {/* Test Email Section */}
            <div className="pt-2 border-t border-border/30">
              <div className="flex flex-col sm:flex-row items-start sm:items-end gap-3">
                <div className="flex-1 w-full">
                  <label className="text-xs text-muted-foreground mb-1.5 block">
                    Send test email to
                  </label>
                  <Input
                    type="email"
                    placeholder="Enter email address (defaults to your email)"
                    value={testEmail}
                    onChange={(e) => setTestEmail(e.target.value)}
                    className="h-9"
                  />
                </div>
                <Button
                  onClick={handleTestEmail}
                  disabled={emailTest.isPending || !config?.enabled}
                  className="h-9 shrink-0"
                >
                  {emailTest.isPending ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  <span className="ml-2">Send Test</span>
                </Button>
              </div>
              {!config?.enabled && status?.status !== 'connected' && (
                <p className="text-xs text-amber-400 mt-2">
                  SMTP is not configured. Set SMTP_HOST and other variables in your environment to enable email.
                </p>
              )}
            </div>

            {/* Environment Note */}
            <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/20 p-3 rounded-xl">
              <ExternalLink className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>
                Email settings are configured via environment variables (SMTP_HOST, SMTP_PORT, etc.).
                Changes require a container restart to take effect.
              </span>
            </div>

            {/* Diagnostics Toggle */}
            <button
              onClick={() => setShowDiagnostics(!showDiagnostics)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <Bug className="w-3.5 h-3.5" />
              {showDiagnostics ? 'Hide' : 'Show'} diagnostics
            </button>

            {showDiagnostics && (
              <div className="p-3 rounded-xl bg-muted/20 border border-border/30 font-mono text-xs space-y-1 overflow-auto">
                <p><span className="text-muted-foreground">Config endpoint:</span> {configError ? 'ERROR' : 'OK'}</p>
                <p><span className="text-muted-foreground">Status endpoint:</span> {statusError ? 'ERROR' : 'OK'}</p>
                <p><span className="text-muted-foreground">Raw enabled:</span> {config?.enabled?.toString()}</p>
                <p><span className="text-muted-foreground">Raw host:</span> {config?.smtp_host ? `"${config.smtp_host}"` : 'null/empty'}</p>
                <p><span className="text-muted-foreground">Raw port:</span> {config?.smtp_port}</p>
                <p><span className="text-muted-foreground">Raw user:</span> {config?.smtp_user ? `"${config.smtp_user}"` : 'null/empty'}</p>
                <p><span className="text-muted-foreground">Raw verify_certs:</span> {config?.smtp_verify_certs?.toString()}</p>
                <p><span className="text-muted-foreground">Status:</span> {status?.status || 'N/A'}</p>
                <p><span className="text-muted-foreground">Status message:</span> {status?.message || 'N/A'}</p>
              </div>
            )}
          </>
        )}
      </motion.div>

      {/* Data Lifecycle Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...springs.gentle, delay: 0.1 }}
        className="bubble space-y-5 p-6"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Database className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="font-semibold text-base">Data Lifecycle</h3>
              <p className="text-xs text-muted-foreground">
                Configure how long analytics and system data is retained
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!retentionLoading && retentionPolicy && (
              <div
                className={cn(
                  'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
                  retentionPolicy.cleanup_enabled
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                )}
              >
                {retentionPolicy.cleanup_enabled ? (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5" />
                )}
                Cleanup {retentionPolicy.cleanup_enabled ? 'Enabled' : 'Disabled'}
              </div>
            )}
            <Tooltip content="Refresh policy">
              <button
                onClick={() => refetchRetention()}
                className="p-1.5 rounded-lg hover:bg-accent transition-colors"
              >
                <RefreshCw className={cn('w-4 h-4 text-muted-foreground', retentionLoading && 'animate-spin')} />
              </button>
            </Tooltip>
          </div>
        </div>

        {retentionLoading ? (
          <div className="space-y-4">
            <div className="h-20 bg-muted/50 rounded-xl animate-pulse" />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {Array.from({ length: 7 }).map((_, i) => (
                <div key={i} className="h-16 bg-muted/50 rounded-xl animate-pulse" />
              ))}
            </div>
          </div>
        ) : !retentionPolicy ? (
          <div className="text-center py-8 text-muted-foreground">
            <p className="text-sm">Failed to load retention policy</p>
          </div>
        ) : (
          <div className="space-y-5">
            {/* How it works explainer */}
            <div className="p-4 rounded-xl bg-muted/20 border border-border/30 space-y-2">
              <p className="text-sm font-medium">How data flows through the system</p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="px-2 py-1 rounded-md bg-background border border-border/40">Raw metrics collected every 1–5 min</span>
                <span className="text-muted-foreground/50">→</span>
                <span className="px-2 py-1 rounded-md bg-background border border-border/40">Daily rollups generated at 3 AM</span>
                <span className="text-muted-foreground/50">→</span>
                <span className="px-2 py-1 rounded-md bg-background border border-border/40">Expired data deleted at cleanup hour</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Analytics dashboards use <strong>raw metrics</strong> for the last 7 days and <strong>daily rollups</strong> for older periods.
                Reducing retention deletes data permanently — the analytics heatmap and charts will show gaps.
              </p>
            </div>

            {/* Retention days — grouped */}
            <div className="space-y-5">
              {retentionGroups.map((group) => (
                <div key={group.title} className="space-y-2">
                  <div>
                    <p className="text-sm font-medium">{group.title}</p>
                    <p className="text-xs text-muted-foreground">{group.description}</p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {group.fields.map((field) => {
                      const currentValue = retentionEdits[field.key] ?? retentionPolicy[field.key];
                      return (
                        <div
                          key={field.key}
                          className="flex items-center justify-between p-3 rounded-xl bg-muted/30 border border-border/30"
                        >
                          <div className="min-w-0 pr-3">
                            <p className="text-sm font-medium">{field.label}</p>
                            <p className="text-[11px] text-muted-foreground">{field.desc}</p>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <input
                              type="number"
                              min={field.min}
                              max={field.max}
                              value={currentValue}
                              onChange={(e) => handleRetentionChange(field.key, parseInt(e.target.value, 10) || field.min)}
                              className="w-16 h-8 px-1 text-sm font-medium text-right bg-background border border-border/50 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                            />
                            <span className="text-xs text-muted-foreground">d</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>

            {/* Cleanup toggle + hour */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 pt-2 border-t border-border/30">
              <div className="flex items-center justify-between flex-1 w-full">
                <div className="space-y-1">
                  <p className="text-sm font-medium">Auto Cleanup</p>
                  <p className="text-xs text-muted-foreground">
                    Automatically purge expired data daily
                  </p>
                </div>
                <Switch
                  checked={(retentionEdits.cleanup_enabled ?? retentionPolicy.cleanup_enabled) as boolean}
                  onCheckedChange={(v) => handleRetentionChange('cleanup_enabled', v)}
                  disabled={updateRetention.isPending}
                />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Run at</span>
                <input
                  type="number"
                  min={0}
                  max={23}
                  value={retentionEdits.cleanup_run_hour ?? retentionPolicy.cleanup_run_hour}
                  onChange={(e) => handleRetentionChange('cleanup_run_hour', parseInt(e.target.value, 10) || 0)}
                  className="w-16 h-8 px-2 text-sm font-medium text-center bg-background border border-border/50 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <span className="text-sm text-muted-foreground">:00 UTC</span>
              </div>
            </div>

            {/* Save button */}
            <div className="flex items-center justify-end gap-3">
              {Object.keys(retentionEdits).length > 0 && (
                <button
                  onClick={() => setRetentionEdits({})}
                  className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Reset
                </button>
              )}
              <Button
                onClick={handleSaveRetention}
                disabled={updateRetention.isPending || Object.keys(retentionEdits).length === 0}
                className="h-9"
              >
                {updateRetention.isPending ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                <span className="ml-2">Save Changes</span>
              </Button>
            </div>

            {/* Impact warning */}
            <div className="flex items-start gap-2.5 text-xs bg-amber-100 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/20 text-amber-800 dark:text-amber-400 p-3 rounded-xl">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-semibold">Reducing retention permanently deletes data</p>
                <p className="text-amber-700 dark:text-amber-400/90">
                  If you change Server Metrics from 30 → 7 days, all metrics older than 7 days are gone forever.
                  The analytics page will show empty charts for that period. Daily rollups are not affected.
                </p>
              </div>
            </div>
          </div>
        )}
      </motion.div>
      </div>
    </div>
  );
}
