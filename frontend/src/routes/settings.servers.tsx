// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import { Server, ArrowLeft, Clock, Power, AlertTriangle, Box, Layers } from 'lucide-react'
import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCurrentUser } from '../hooks/use-current-user'
import { usePlans } from '../hooks/use-plans'
import { useEnvironments } from '../hooks/use-environments'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'
import { cn } from '../lib/utils'
import { Switch } from '../components/ui/switch'
import { Slider } from '../components/ui/slider'
import { Select, SelectItem } from '../components/ui/select'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'

export const Route = createFileRoute('/settings/servers')({
  component: ServerBehaviorSettingsPage,
})

const TIMEOUT_OPTIONS = [
  { value: 15, label: '15 minutes' },
  { value: 30, label: '30 minutes' },
  { value: 60, label: '1 hour' },
  { value: 120, label: '2 hours' },
]

const MAX_RUNTIME_MIN = 30
const MAX_RUNTIME_MAX = 4320 // 72 hours

function formatRuntimeMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} minutes`
  if (minutes === 60) return '1 hour'
  if (minutes < 1440) return `${minutes / 60} hours`
  if (minutes === 1440) return '1 day'
  const days = Math.floor(minutes / 1440)
  const remainder = minutes % 1440
  if (remainder === 0) return `${days} days`
  const hours = remainder / 60
  return `${days} day${days > 1 ? 's' : ''} ${hours} hours`
}

function ServerBehaviorSettingsPage() {
  const { data: user } = useCurrentUser()
  const queryClient = useQueryClient()
  const { error } = useToast()

  const [idleEnabled, setIdleEnabled] = useState(true)
  const [idleTimeout, setIdleTimeout] = useState(15)
  const [maxRuntimeEnabled, setMaxRuntimeEnabled] = useState(true)
  const [maxRuntime, setMaxRuntime] = useState(1440)
  const [stopOnLogout, setStopOnLogout] = useState(false)
  const [defaultPlan, setDefaultPlan] = useState('')
  const [defaultEnvironment, setDefaultEnvironment] = useState('')
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle')

  const { data: plansData } = usePlans({ is_active: true, limit: 100 })
  const { data: envData } = useEnvironments({ is_active: true, limit: 100 })
  const plans = plansData?.data || []
  const environments = envData?.data || []

  // Load saved preferences
  useEffect(() => {
    if (user?.preferences) {
      const prefs = user.preferences
      queueMicrotask(() => {
        if (typeof prefs.idle_shutdown_enabled === 'boolean') {
          setIdleEnabled(prefs.idle_shutdown_enabled)
        }
        if (typeof prefs.idle_shutdown_timeout === 'number') {
          setIdleTimeout(prefs.idle_shutdown_timeout)
        }
        if (typeof prefs.max_server_runtime_enabled === 'boolean') {
          setMaxRuntimeEnabled(prefs.max_server_runtime_enabled)
        }
        if (typeof prefs.max_server_runtime === 'number') {
          setMaxRuntime(prefs.max_server_runtime)
        }
        if (typeof prefs.stop_on_logout === 'boolean') {
          setStopOnLogout(prefs.stop_on_logout)
        }
        if (typeof prefs.default_plan === 'string') {
          setDefaultPlan(prefs.default_plan)
        }
        if (typeof prefs.default_environment === 'string') {
          setDefaultEnvironment(prefs.default_environment)
        }
      })
    }
  }, [user])

  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const saveMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      return api.put('/preferences/', payload)
    },
    onSuccess: (_result, variables) => {
      setSaveStatus('saved')
      queryClient.setQueryData(['me'], (old: unknown) => {
        if (!old) return old
        const prev = old as { preferences?: Record<string, unknown> }
        return {
          ...old,
          preferences: {
            ...(prev.preferences || {}),
            ...variables,
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
    (updates: Record<string, unknown>) => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
      setSaveStatus('saving')
      saveTimeoutRef.current = setTimeout(() => {
        saveMutation.mutate({
          idle_shutdown_enabled: updates.idle_shutdown_enabled ?? idleEnabled,
          idle_shutdown_timeout: updates.idle_shutdown_timeout ?? idleTimeout,
          max_server_runtime_enabled: updates.max_server_runtime_enabled ?? maxRuntimeEnabled,
          max_server_runtime: updates.max_server_runtime ?? maxRuntime,
          stop_on_logout: updates.stop_on_logout ?? stopOnLogout,
          default_plan: updates.default_plan ?? defaultPlan,
          default_environment: updates.default_environment ?? defaultEnvironment,
        })
      }, 400)
    },
    [
      idleEnabled,
      idleTimeout,
      maxRuntimeEnabled,
      maxRuntime,
      stopOnLogout,
      defaultPlan,
      defaultEnvironment,
      saveMutation,
    ]
  )

  const handleIdleToggle = (checked: boolean) => {
    setIdleEnabled(checked)
    triggerSave({ idle_shutdown_enabled: checked })
  }

  const handleTimeoutChange = (value: number) => {
    setIdleTimeout(value)
    triggerSave({ idle_shutdown_timeout: value })
  }

  const handleRuntimeEnabledToggle = (checked: boolean) => {
    setMaxRuntimeEnabled(checked)
    triggerSave({ max_server_runtime_enabled: checked })
  }

  const handleRuntimeChange = (value: number) => {
    setMaxRuntime(value)
    triggerSave({ max_server_runtime: value })
  }

  const handleLogoutToggle = (checked: boolean) => {
    setStopOnLogout(checked)
    triggerSave({ stop_on_logout: checked })
  }

  const handleDefaultPlanChange = (value: string) => {
    setDefaultPlan(value)
    triggerSave({ default_plan: value })
  }

  const handleDefaultEnvironmentChange = (value: string) => {
    setDefaultEnvironment(value)
    triggerSave({ default_environment: value })
  }

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
              <span
                className={cn(
                  'text-xs px-2 py-0.5 rounded-full font-medium transition-colors',
                  saveStatus === 'saving'
                    ? 'bg-muted text-muted-foreground'
                    : 'bg-emerald-500/10 text-emerald-500'
                )}
              >
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
                Automatically stop servers after a period of inactivity to save credits and free
                resources.
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
                animate={{
                  opacity: idleEnabled ? 1 : 0.5,
                  pointerEvents: idleEnabled ? 'auto' : 'none',
                }}
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
                          'px-4 py-3 rounded-xl text-sm font-medium transition-all border',
                          idleTimeout === option.value
                            ? 'border-primary bg-primary/5 text-primary'
                            : 'border-border/50 bg-card/30 text-muted-foreground hover:border-border hover:bg-card/50'
                        )}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>

              {/* Warning */}
              <div className="warning-tip warning-tip-amber">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <p className="text-sm">
                  Unsaved work may be lost when servers auto-stop. Make sure to save your work
                  regularly.
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Max Server Runtime */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.05 }}
        >
          <Card>
            <CardHeader>
              <CardTitle>Maximum Server Runtime</CardTitle>
              <CardDescription>
                Automatically stop servers after this much continuous runtime. Starting or
                restarting a server resets the timer.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Toggle */}
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Clock className="w-4 h-4 text-muted-foreground" />
                    <h3 className="text-base font-semibold">Enable Runtime Limit</h3>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Cap how long a server can run before auto-stopping
                  </p>
                </div>
                <Switch checked={maxRuntimeEnabled} onCheckedChange={handleRuntimeEnabledToggle} />
              </div>

              {/* Slider */}
              <motion.div
                animate={{
                  opacity: maxRuntimeEnabled ? 1 : 0.5,
                  pointerEvents: maxRuntimeEnabled ? 'auto' : 'none',
                }}
                transition={{ duration: 0.2 }}
              >
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-medium">Runtime limit per session</label>
                    <span className="text-sm font-semibold text-primary">
                      {formatRuntimeMinutes(maxRuntime)}
                    </span>
                  </div>
                  <Slider
                    min={MAX_RUNTIME_MIN}
                    max={MAX_RUNTIME_MAX}
                    step={30}
                    value={maxRuntime}
                    onChange={handleRuntimeChange}
                  />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{formatRuntimeMinutes(MAX_RUNTIME_MIN)}</span>
                    <span>{formatRuntimeMinutes(MAX_RUNTIME_MAX)}</span>
                  </div>
                </div>
              </motion.div>

              <div className="warning-tip warning-tip-amber">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <p className="text-sm">
                  When the runtime limit is reached, the server will be stopped automatically. Save
                  your work before the timer expires.
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Default Spawn Preferences */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
        >
          <Card>
            <CardHeader>
              <CardTitle>Default Spawn Preferences</CardTitle>
              <CardDescription>
                Pre-select your preferred plan and environment for quick server deployment.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Default Plan */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-muted-foreground" />
                  <h3 className="text-base font-semibold">Default Plan</h3>
                </div>
                <Select
                  value={defaultPlan}
                  onChange={(value) => handleDefaultPlanChange(value)}
                  placeholder="No default (manual selection)"
                >
                  {plans.map((plan) => (
                    <SelectItem key={plan.id} value={plan.id}>
                      {plan.name} ({plan.cpu_limit} CPU / {plan.memory_limit})
                    </SelectItem>
                  ))}
                </Select>
                <p className="text-sm text-muted-foreground">
                  Used when opening the deploy dialog or pressing Alt+N.
                </p>
              </div>

              {/* Default Environment */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Box className="w-4 h-4 text-muted-foreground" />
                  <h3 className="text-base font-semibold">Default Environment</h3>
                </div>
                <Select
                  value={defaultEnvironment}
                  onChange={(value) => handleDefaultEnvironmentChange(value)}
                  placeholder="No default (manual selection)"
                >
                  {environments.map((env) => (
                    <SelectItem key={env.id} value={env.id}>
                      {env.name} ({env.slug})
                    </SelectItem>
                  ))}
                </Select>
                <p className="text-sm text-muted-foreground">
                  The environment template used for quick spawn.
                </p>
              </div>

              <div className="warning-tip warning-tip-emerald">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <p className="text-sm">
                  When both defaults are set, press Ctrl+N anywhere to instantly create a server.
                  Otherwise, the deploy dialog will open.
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Stop on Logout */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
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

              <div className="warning-tip warning-tip-rose">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <p className="text-sm">
                  This is an aggressive setting. Any background jobs or unsaved work will be lost
                  when you log out.
                </p>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  )
}
