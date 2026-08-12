// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Check, Clock, Coins, Gift, RefreshCw, Scale, Timer, Wallet, Zap } from 'lucide-react'
import {
  useSystemDailyAllowance,
  useUpdateSystemDailyAllowance,
  useSystemMaxBalance,
  useUpdateSystemMaxBalance,
  useSystemInitialBalance,
  useUpdateSystemInitialBalance,
  useSystemAllowanceLoginWindow,
  useUpdateSystemAllowanceLoginWindow,
  useSystemAutoApproveMax,
  useUpdateSystemAutoApproveMax,
  useSystemRequestCooldown,
  useUpdateSystemRequestCooldown,
} from '../../../hooks/use-system-config'
import { useAuthStore, PERMISSIONS } from '../../../stores/auth-store'
import { cn } from '../../../lib/utils'
import { Tooltip } from '../../ui/tooltip'
import { Button } from '../../ui/button'

interface SystemSetting {
  key: string
  title: string
  description: string
  icon: React.ElementType
  iconBg: string
  iconColor: string
  input: string
  setInput: (v: string) => void
  value: number | undefined
  loading: boolean
  isPending: boolean
  onSave: () => void
  saveLabel: string
  display: (v?: number) => string
  /** When set, the input is uncontrolled and remounts with this default on server-value changes. */
  defaultValue?: number
}

export function SettingsTab() {
  const hasPermission = useAuthStore((state) => state.hasPermission)
  const canManageSystemAllowance = hasPermission(PERMISSIONS.ADMIN_ACCESS)

  const {
    data: systemAllowanceData,
    isLoading: systemAllowanceLoading,
    refetch: refetchSystemAllowance,
  } = useSystemDailyAllowance()
  const updateSystemAllowance = useUpdateSystemDailyAllowance()

  const {
    data: systemMaxBalanceData,
    isLoading: systemMaxBalanceLoading,
    refetch: refetchSystemMaxBalance,
  } = useSystemMaxBalance()
  const updateSystemMaxBalance = useUpdateSystemMaxBalance()

  const {
    data: systemInitialBalanceData,
    isLoading: systemInitialBalanceLoading,
    refetch: refetchSystemInitialBalance,
  } = useSystemInitialBalance()
  const updateSystemInitialBalance = useUpdateSystemInitialBalance()

  const {
    data: systemLoginWindowData,
    isLoading: systemLoginWindowLoading,
    refetch: refetchSystemLoginWindow,
  } = useSystemAllowanceLoginWindow()
  const updateSystemLoginWindow = useUpdateSystemAllowanceLoginWindow()

  const {
    data: systemAutoApproveData,
    isLoading: systemAutoApproveLoading,
    refetch: refetchSystemAutoApprove,
  } = useSystemAutoApproveMax()
  const updateSystemAutoApproveMax = useUpdateSystemAutoApproveMax()

  const {
    data: systemCooldownData,
    isLoading: systemCooldownLoading,
    refetch: refetchSystemCooldown,
  } = useSystemRequestCooldown()
  const updateSystemCooldown = useUpdateSystemRequestCooldown()

  const [systemAllowanceInput, setSystemAllowanceInput] = useState('')
  const systemAllowanceValue = systemAllowanceData?.default_daily_allowance

  const [systemMaxBalanceInput, setSystemMaxBalanceInput] = useState('')
  const systemMaxBalanceValue = systemMaxBalanceData?.max_balance

  const [systemInitialBalanceInput, setSystemInitialBalanceInput] = useState('')
  const systemInitialBalanceValue = systemInitialBalanceData?.initial_balance

  const [systemLoginWindowInput, setSystemLoginWindowInput] = useState('')
  const systemLoginWindowValue = systemLoginWindowData?.login_window_hours

  // These two inputs are uncontrolled (defaultValue + remount key in the render below)
  // so they sync from the server value without effect-based setState.
  const [systemAutoApproveInput, setSystemAutoApproveInput] = useState('')
  const systemAutoApproveValue = systemAutoApproveData?.auto_approve_max

  const [systemCooldownInput, setSystemCooldownInput] = useState('')
  const systemCooldownValue = systemCooldownData?.request_cooldown_hours

  useEffect(() => {
    if (systemAllowanceValue !== undefined) {
      setSystemAllowanceInput(String(systemAllowanceValue))
    }
  }, [systemAllowanceValue])

  useEffect(() => {
    if (systemMaxBalanceValue !== undefined) {
      setSystemMaxBalanceInput(String(systemMaxBalanceValue))
    }
  }, [systemMaxBalanceValue])

  useEffect(() => {
    if (systemInitialBalanceValue !== undefined) {
      setSystemInitialBalanceInput(String(systemInitialBalanceValue))
    }
  }, [systemInitialBalanceValue])

  useEffect(() => {
    if (systemLoginWindowValue !== undefined) {
      setSystemLoginWindowInput(String(systemLoginWindowValue))
    }
  }, [systemLoginWindowValue])

  const handleSaveSystemAllowance = () => {
    const value = parseInt(systemAllowanceInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemAllowanceValue) return
    updateSystemAllowance.mutate(value)
  }

  const handleSaveSystemMaxBalance = () => {
    const value = parseInt(systemMaxBalanceInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemMaxBalanceValue) return
    updateSystemMaxBalance.mutate(value)
  }

  const handleSaveSystemInitialBalance = () => {
    const value = parseInt(systemInitialBalanceInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemInitialBalanceValue) return
    updateSystemInitialBalance.mutate(value)
  }

  const handleSaveSystemLoginWindow = () => {
    const value = parseInt(systemLoginWindowInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemLoginWindowValue) return
    updateSystemLoginWindow.mutate(value)
  }

  const handleSaveSystemAutoApproveMax = () => {
    const value = parseInt(systemAutoApproveInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemAutoApproveValue) return
    updateSystemAutoApproveMax.mutate(value)
  }

  const handleSaveSystemCooldown = () => {
    const value = parseInt(systemCooldownInput, 10)
    if (Number.isNaN(value) || value < 0) return
    if (value === systemCooldownValue) return
    updateSystemCooldown.mutate(value)
  }

  const systemSettings: SystemSetting[] = [
    {
      key: 'allowance',
      title: 'Default Daily Allowance',
      description: 'NUKE / day applied to new users',
      icon: Coins,
      iconBg: 'bg-violet-500/10',
      iconColor: 'text-violet-400',
      input: systemAllowanceInput,
      setInput: setSystemAllowanceInput,
      value: systemAllowanceValue,
      loading: systemAllowanceLoading,
      isPending: updateSystemAllowance.isPending,
      onSave: handleSaveSystemAllowance,
      saveLabel: 'Save Default',
      display: (v?: number) => `${(v ?? 0).toLocaleString()} NUKE / day`,
    },
    {
      key: 'max-balance',
      title: 'Max Balance',
      description: 'Hard cap in NUKE, 0 = unlimited',
      icon: Scale,
      iconBg: 'bg-rose-500/10',
      iconColor: 'text-rose-400',
      input: systemMaxBalanceInput,
      setInput: setSystemMaxBalanceInput,
      value: systemMaxBalanceValue,
      loading: systemMaxBalanceLoading,
      isPending: updateSystemMaxBalance.isPending,
      onSave: handleSaveSystemMaxBalance,
      saveLabel: 'Save Cap',
      display: (v?: number) => (v === 0 ? 'Unlimited' : `${(v ?? 0).toLocaleString()} NUKE`),
    },
    {
      key: 'initial-balance',
      title: 'Signup Initial Balance',
      description: 'NUKE granted on first signup',
      icon: Gift,
      iconBg: 'bg-emerald-500/10',
      iconColor: 'text-emerald-400',
      input: systemInitialBalanceInput,
      setInput: setSystemInitialBalanceInput,
      value: systemInitialBalanceValue,
      loading: systemInitialBalanceLoading,
      isPending: updateSystemInitialBalance.isPending,
      onSave: handleSaveSystemInitialBalance,
      saveLabel: 'Save Initial Balance',
      display: (v?: number) => `${(v ?? 0).toLocaleString()} NUKE`,
    },
    {
      key: 'login-window',
      title: 'Allowance Login Window',
      description: 'Hours of recent login required',
      icon: Clock,
      iconBg: 'bg-amber-500/10',
      iconColor: 'text-amber-400',
      input: systemLoginWindowInput,
      setInput: setSystemLoginWindowInput,
      value: systemLoginWindowValue,
      loading: systemLoginWindowLoading,
      isPending: updateSystemLoginWindow.isPending,
      onSave: handleSaveSystemLoginWindow,
      saveLabel: 'Save Window',
      display: (v?: number) => `${v ?? 0} hours`,
    },
    {
      key: 'auto-approve-max',
      title: 'Auto-approve Max',
      description: 'Requests at or below auto-approve, 0 = disabled',
      icon: Zap,
      iconBg: 'bg-sky-500/10',
      iconColor: 'text-sky-400',
      input: systemAutoApproveInput,
      setInput: setSystemAutoApproveInput,
      value: systemAutoApproveValue,
      loading: systemAutoApproveLoading,
      isPending: updateSystemAutoApproveMax.isPending,
      onSave: handleSaveSystemAutoApproveMax,
      saveLabel: 'Save Auto-approve',
      display: (v?: number) => (v === 0 ? 'Disabled' : `${(v ?? 0).toLocaleString()} NUKE`),
      defaultValue: systemAutoApproveValue,
    },
    {
      key: 'request-cooldown',
      title: 'Request Cooldown',
      description: 'Hours between credit requests per user',
      icon: Timer,
      iconBg: 'bg-orange-500/10',
      iconColor: 'text-orange-400',
      input: systemCooldownInput,
      setInput: setSystemCooldownInput,
      value: systemCooldownValue,
      loading: systemCooldownLoading,
      isPending: updateSystemCooldown.isPending,
      onSave: handleSaveSystemCooldown,
      saveLabel: 'Save Cooldown',
      display: (v?: number) => `${v ?? 0} hours`,
      defaultValue: systemCooldownValue,
    },
  ]

  return (
    /* System Credit Settings */
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
      className="bubble p-5 space-y-4"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wallet className="w-4 h-4 text-violet-400" />
          <h3 className="font-semibold text-sm">System Credit Settings</h3>
        </div>
        <Tooltip content="Refresh all">
          <button
            onClick={() => {
              refetchSystemAllowance()
              refetchSystemMaxBalance()
              refetchSystemInitialBalance()
              refetchSystemLoginWindow()
              refetchSystemAutoApprove()
              refetchSystemCooldown()
            }}
            className="p-1.5 rounded-lg hover:bg-accent transition-colors"
          >
            <RefreshCw className="w-4 h-4 text-muted-foreground" />
          </button>
        </Tooltip>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-x-10">
        {systemSettings.map((s) => (
          <div
            key={s.key}
            className="flex items-center gap-3 py-3 border-b border-border/50 first:pt-0 last:border-0 xl:[&:nth-child(n+5)]:border-b-0 xl:[&:nth-child(n+5)]:pb-0"
          >
            <div
              className={cn(
                'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
                s.iconBg
              )}
            >
              <s.icon className={cn('w-4 h-4', s.iconColor)} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium leading-tight">{s.title}</p>
              <p className="text-xs text-muted-foreground leading-tight truncate">
                {s.description}
              </p>
            </div>
            {s.loading && s.value === undefined ? (
              <div className="h-8 w-32 bg-muted/50 rounded-lg animate-pulse" />
            ) : canManageSystemAllowance ? (
              <div className="flex items-center gap-2 shrink-0">
                <input
                  type="number"
                  min={0}
                  step={1}
                  aria-label={s.title}
                  {...(s.defaultValue !== undefined
                    ? { key: String(s.defaultValue), defaultValue: s.defaultValue }
                    : { value: s.input })}
                  onChange={(e) => s.setInput(e.target.value)}
                  disabled={s.isPending}
                  className="w-28 h-8 px-2.5 text-sm text-right bg-background border border-border/50 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                />
                <Tooltip content={s.saveLabel}>
                  <Button
                    size="sm"
                    onClick={s.onSave}
                    disabled={
                      s.isPending ||
                      Number.isNaN(parseInt(s.input, 10)) ||
                      parseInt(s.input, 10) < 0 ||
                      parseInt(s.input, 10) === s.value
                    }
                    className="h-8 w-8 p-0 shrink-0"
                  >
                    {s.isPending ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Check className="w-3.5 h-3.5" />
                    )}
                  </Button>
                </Tooltip>
              </div>
            ) : (
              <span className="font-mono font-medium text-sm shrink-0">{s.display(s.value)}</span>
            )}
          </div>
        ))}
      </div>
    </motion.div>
  )
}
