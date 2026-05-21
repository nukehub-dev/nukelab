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
      </div>
    </div>
  );
}
