import { createFileRoute, Link } from '@tanstack/react-router'
import {
  Bell,
  Server,
  CreditCard,
  AlertTriangle,
  Calendar,
  Users,
  Check,
  Loader2,
  ArrowLeft,
  HardDrive,
  FolderOpen,
  Key,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCurrentUser } from '../hooks/use-current-user'
import { api } from '../lib/api'
import { Input } from '../components/ui/input'
import { Checkbox } from '../components/ui/checkbox'
import { useToast } from '../stores/toast-store'

export const Route = createFileRoute('/settings/notifications')({
  component: NotificationsSettingsPage,
})

// Icon mapping — kept locally, never sent to API
const EVENT_ICONS: Record<string, React.ElementType> = {
  server_start: Server,
  server_stop: Server,
  server_ready: Server,
  server_failed: Server,
  server_backup_completed: Server,
  credit_low: CreditCard,
  credit_granted: CreditCard,
  queue_position: Users,
  schedule_run: Calendar,
  alert_fired: AlertTriangle,
  maintenance: AlertTriangle,
  workspace_invite: Users,
  workspace_member_added: Users,
  workspace_member_removed: Users,
  ownership_transferred: FolderOpen,
  volume_created: HardDrive,
  volume_near_limit: HardDrive,
  volume_deleted: HardDrive,

  api_key_created: Key,
}

interface EventPreference {
  event: string
  label: string
  description: string
  channels: Record<string, boolean>
}

// Serializable defaults (no icon component)
const defaultEvents: EventPreference[] = [
  {
    event: 'server_start',
    label: 'Server Started',
    description: 'When a server is started',
    channels: { email: false, webhook: false, in_app: true },
  },
  {
    event: 'server_stop',
    label: 'Server Stopped',
    description: 'When a server is stopped',
    channels: { email: false, webhook: false, in_app: true },
  },
  {
    event: 'server_ready',
    label: 'Server Ready',
    description: 'When a server is ready to use',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'server_failed',
    label: 'Server Failed',
    description: 'When a server fails to start',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'server_backup_completed',
    label: 'Backup Completed',
    description: 'When a server backup finishes',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'credit_low',
    label: 'Low Credits',
    description: 'When your credit balance is low',
    channels: { email: true, webhook: true, in_app: true },
  },
  {
    event: 'credit_granted',
    label: 'Credits Granted',
    description: 'When credits are added to your account',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'queue_position',
    label: 'Queue Position',
    description: 'Updates on your queue position',
    channels: { email: false, webhook: false, in_app: true },
  },
  {
    event: 'schedule_run',
    label: 'Schedule Executed',
    description: 'When a scheduled task runs',
    channels: { email: false, webhook: false, in_app: true },
  },
  {
    event: 'alert_fired',
    label: 'Alert Fired',
    description: 'When a system alert is triggered',
    channels: { email: true, webhook: true, in_app: true },
  },
  {
    event: 'maintenance',
    label: 'Maintenance Mode',
    description: 'System maintenance notifications',
    channels: { email: true, webhook: true, in_app: true },
  },
  {
    event: 'workspace_invite',
    label: 'Workspace Invitation',
    description: 'When you are invited to a workspace',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'workspace_member_added',
    label: 'Added to Workspace',
    description: 'When you are added to a workspace',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'workspace_member_removed',
    label: 'Removed from Workspace',
    description: 'When you are removed from a workspace',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'ownership_transferred',
    label: 'Ownership Transferred',
    description: 'When workspace ownership is transferred to you',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'volume_created',
    label: 'Volume Created',
    description: 'When a new volume is provisioned',
    channels: { email: false, webhook: false, in_app: true },
  },
  {
    event: 'volume_near_limit',
    label: 'Volume Near Limit',
    description: 'When a volume reaches 90% capacity',
    channels: { email: true, webhook: false, in_app: true },
  },
  {
    event: 'volume_deleted',
    label: 'Volume Deleted',
    description: 'When a volume is permanently removed',
    channels: { email: true, webhook: false, in_app: true },
  },

  {
    event: 'api_key_created',
    label: 'API Key Created',
    description: 'When a new API key is generated',
    channels: { email: true, webhook: false, in_app: true },
  },
]

function NotificationsSettingsPage() {
  const { data: user } = useCurrentUser()
  const queryClient = useQueryClient()
  const { error } = useToast()
  const [preferences, setPreferences] = useState<EventPreference[]>(defaultEvents)
  const [webhookUrl, setWebhookUrl] = useState('')
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle')

  // Load saved preferences
  useEffect(() => {
    if (user?.preferences?.notifications) {
      const saved = user.preferences.notifications as {
        events?: EventPreference[]
        webhook_url?: string
      }
      queueMicrotask(() => {
        if (saved.events) {
          setPreferences(saved.events)
        }
        if (saved.webhook_url !== undefined) {
          setWebhookUrl(saved.webhook_url)
        }
      })
    }
  }, [user])

  // Debounced auto-save
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const saveMutation = useMutation({
    mutationFn: async (payload: { events: EventPreference[]; webhook_url: string }) => {
      return api.put('/preferences/', { notifications: payload })
    },
    onSuccess: (_result, variables) => {
      setSaveStatus('saved')
      // Update cached user data directly instead of refetching
      queryClient.setQueryData(['me'], (old: unknown) => {
        if (!old) return old
        const prev = old as { preferences?: Record<string, unknown> }
        return {
          ...old,
          preferences: {
            ...(prev.preferences || {}),
            notifications: {
              events: variables.events,
              webhook_url: variables.webhook_url,
            },
          },
        }
      })
      setTimeout(() => setSaveStatus('idle'), 2000)
    },
    onError: (err) => {
      setSaveStatus('idle')
      error('Failed to save preferences', err instanceof Error ? err.message : 'Please try again')
    },
  })

  const triggerSave = useCallback(
    (newPreferences: EventPreference[], newWebhookUrl: string) => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
      setSaveStatus('saving')
      saveTimeoutRef.current = setTimeout(() => {
        saveMutation.mutate({ events: newPreferences, webhook_url: newWebhookUrl })
      }, 400)
    },
    [saveMutation]
  )

  const toggleChannel = (eventIndex: number, channelId: string) => {
    setPreferences((prev) => {
      const updated = [...prev]
      updated[eventIndex] = {
        ...updated[eventIndex],
        channels: {
          ...updated[eventIndex].channels,
          [channelId]: !updated[eventIndex].channels[channelId],
        },
      }
      triggerSave(updated, webhookUrl)
      return updated
    })
  }

  const handleWebhookChange = (value: string) => {
    setWebhookUrl(value)
    triggerSave(preferences, value)
  }

  const handleEnableAll = () => {
    const updated = preferences.map((p) => ({
      ...p,
      channels: { email: true, webhook: true, in_app: true },
    }))
    setPreferences(updated)
    triggerSave(updated, webhookUrl)
  }

  const handleDisableAll = () => {
    const updated = preferences.map((p) => ({
      ...p,
      channels: { email: false, webhook: false, in_app: false },
    }))
    setPreferences(updated)
    triggerSave(updated, webhookUrl)
  }

  const handleReset = () => {
    setPreferences(defaultEvents)
    setWebhookUrl('')
    triggerSave(defaultEvents, '')
  }

  // Calculate summary stats
  const totalEnabled = preferences.reduce(
    (acc, pref) => acc + Object.values(pref.channels).filter(Boolean).length,
    0
  )

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-10">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
          <Link
            to="/settings"
            className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="p-2 rounded-xl bg-primary/10">
            <Bell className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-bold">Notifications</h1>
            <p className="text-sm text-muted-foreground">Configure notification preferences</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {saveStatus === 'saving' && (
            <span className="text-sm text-muted-foreground flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Saving...
            </span>
          )}
          {saveStatus === 'saved' && (
            <motion.span
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="text-sm text-emerald-400 font-medium flex items-center gap-1"
            >
              <Check className="w-3.5 h-3.5" />
              Saved
            </motion.span>
          )}
          <div className="text-right">
            <p className="text-2xl font-bold">{totalEnabled}</p>
            <p className="text-xs text-muted-foreground">Active notifications</p>
          </div>
        </div>
      </motion.div>

      <div className="space-y-8">
        {/* Webhook URL */}
        <SettingsSection
          title="Webhook URL"
          description="Configure a webhook endpoint to receive notifications."
        >
          <div className="flex items-start gap-4">
            <div className="flex-1">
              <Input
                value={webhookUrl}
                onChange={(e) => handleWebhookChange(e.target.value)}
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
          description="Choose how you want to receive notifications for each event. Changes are saved automatically."
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
                const Icon = EVENT_ICONS[pref.event] || Bell
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
                )
              })}
            </div>
          </div>
        </SettingsSection>

        {/* Quick Actions */}
        <SettingsSection
          title="Quick Actions"
          description="Enable or disable all notifications at once."
        >
          <div className="flex gap-4">
            <button
              onClick={handleEnableAll}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-border/50 bg-muted/30 text-sm font-medium hover:bg-accent transition-colors"
            >
              <Check className="w-4 h-4" />
              Enable All
            </button>
            <button
              onClick={handleDisableAll}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-border/50 bg-muted/30 text-sm font-medium hover:bg-accent transition-colors"
            >
              Disable All
            </button>
            <button
              onClick={handleReset}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-border/50 bg-muted/30 text-sm font-medium hover:bg-accent transition-colors text-muted-foreground"
            >
              Reset to Defaults
            </button>
          </div>
        </SettingsSection>
      </div>
    </div>
  )
}

function SettingsSection({
  title,
  description,
  children,
}: {
  title?: string
  description?: string
  children: React.ReactNode
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
          {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
        </div>
      )}
      <div>{children}</div>
    </motion.div>
  )
}
