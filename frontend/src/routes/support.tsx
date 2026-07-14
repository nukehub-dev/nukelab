// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import * as React from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import {
  LifeBuoy,
  MessagesSquare,
  Mail,
  Newspaper,
  ExternalLink,
  Activity,
  HelpCircle,
  ChevronDown,
  Copy,
  Check,
  Keyboard,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { EXTERNAL_LINKS } from '../lib/external-links'
import { cn } from '../lib/utils'
import { useHealth } from '../hooks/use-health'
import { useAuthStore } from '../stores/auth-store'
import { useTimezoneStore } from '../stores/timezone-store'

export const Route = createFileRoute('/support')({
  component: SupportPage,
})

const links = [
  {
    key: 'community',
    icon: MessagesSquare,
    color: 'bg-violet-500/10 text-violet-400',
    ...EXTERNAL_LINKS.community,
  },
  { key: 'contact', icon: Mail, color: 'bg-blue-500/10 text-blue-400', ...EXTERNAL_LINKS.contact },
  {
    key: 'blog',
    icon: Newspaper,
    color: 'bg-amber-500/10 text-amber-400',
    ...EXTERNAL_LINKS.blog,
  },
]

const faqs = [
  {
    question: 'Why did my server stop?',
    answer: (
      <>
        Servers stop automatically after a period of inactivity (15 minutes by default) or when they
        hit the maximum session runtime (24 hours by default). You can adjust both under{' '}
        <Link to="/settings/servers" className="text-primary hover:underline">
          Settings → Servers
        </Link>
        .
      </>
    ),
  },
  {
    question: 'How do credits work?',
    answer: (
      <>
        Running servers consume credits based on their plan and uptime. You can track consumption on
        the{' '}
        <Link to="/usage" className="text-primary hover:underline">
          Usage
        </Link>{' '}
        page, and configure low-credit alerts under Settings → Notifications.
      </>
    ),
  },
  {
    question: "Why can't I create a server?",
    answer:
      'Your plan limits how many servers (and how much CPU, memory, and disk) you can run at once. Stop unused servers and try again, or ask an administrator to adjust your plan or quota.',
  },
  {
    question: 'Will my data persist after my server stops?',
    answer: (
      <>
        Files stored in volumes persist across server stops and restarts. You can manage volumes on
        the{' '}
        <Link to="/volumes" className="text-primary hover:underline">
          Volumes
        </Link>{' '}
        page. Anything stored outside a volume may be lost when the server is removed.
      </>
    ),
  },
  {
    question: 'Why do times look wrong, and can I change the timezone?',
    answer: (
      <>
        All dates and times are shown in your display timezone — by default your browser&apos;s. You
        can pin a specific zone (or UTC) under{' '}
        <Link to="/settings/appearance" className="text-primary hover:underline">
          Settings → Appearance → Timezone
        </Link>
        . The label next to each timestamp shows which zone is being used.
      </>
    ),
  },
  {
    question: 'How do I share an environment with someone?',
    answer: (
      <>
        Use{' '}
        <Link to="/workspaces" className="text-primary hover:underline">
          Workspaces
        </Link>{' '}
        to group servers and volumes and invite other users. Open a workspace to manage its members
        and invitations.
      </>
    ),
  },
]

function StatusCard() {
  const { data, isPending, isError } = useHealth()

  const state = isPending
    ? { dot: 'bg-muted-foreground animate-pulse', label: 'Checking status…' }
    : isError
      ? { dot: 'bg-red-400', label: 'Unable to reach the API' }
      : data?.status === 'maintenance'
        ? { dot: 'bg-amber-400', label: 'Scheduled maintenance in progress' }
        : { dot: 'bg-emerald-400', label: 'All systems operational' }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="flex items-center gap-4 p-5 rounded-xl bg-card/50 border border-border/50"
    >
      <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-emerald-500/10 text-emerald-400">
        <Activity className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={cn('w-2 h-2 rounded-full shrink-0', state.dot)} />
          <h3 className="font-semibold text-base">{state.label}</h3>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          {data?.status === 'maintenance' && data.message
            ? data.message
            : 'Live status from the NukeLab API, refreshed every 30 seconds.'}
        </p>
      </div>
    </motion.div>
  )
}

function FaqItem({ question, answer }: { question: string; answer: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)

  return (
    <div className="border border-border/50 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-4 p-4 text-left hover:bg-accent/40 transition-colors"
      >
        <span className="font-medium text-sm">{question}</span>
        <ChevronDown
          className={cn(
            'w-4 h-4 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-180'
          )}
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <p className="px-4 pb-4 text-sm text-muted-foreground">{answer}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function DebugInfoCard() {
  const [copied, setCopied] = React.useState(false)
  const { data: health } = useHealth()
  const user = useAuthStore((s) => s.user)
  const timezone = useTimezoneStore((s) => s.preference)
  const effectiveZone = useTimezoneStore((s) => s.effectiveZone)

  const handleCopy = async () => {
    const info = [
      `Status: ${health?.status ?? 'unknown'}`,
      `User: ${user?.username ?? 'unknown'}`,
      `Timezone: ${timezone === 'auto' ? `auto (${effectiveZone})` : timezone}`,
      `Browser: ${navigator.userAgent}`,
      `Time: ${new Date().toISOString()}`,
    ].join('\n')

    try {
      await navigator.clipboard.writeText(info)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard requires a secure context / permission; nothing sensible to fall back to.
    }
  }

  return (
    <div className="p-5 rounded-xl bg-card/50 border border-border/50 h-full flex flex-col">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-blue-500/10 text-blue-400">
          <Copy className="w-5 h-5" />
        </div>
        <h3 className="font-semibold text-base">Copy debug info</h3>
      </div>
      <p className="text-sm text-muted-foreground mt-3 flex-1">
        Copies your API status, username, timezone, and browser details — paste it into a community
        post or contact message to help us diagnose your issue faster.
      </p>
      <button
        type="button"
        onClick={handleCopy}
        className="mt-4 inline-flex items-center justify-center gap-2 h-9 px-4 rounded-lg bg-muted text-sm font-medium hover:bg-muted/70 transition-colors"
      >
        {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
        {copied ? 'Copied' : 'Copy to clipboard'}
      </button>
    </div>
  )
}

function ShortcutsCard() {
  return (
    <div className="p-5 rounded-xl bg-card/50 border border-border/50 h-full flex flex-col">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-violet-500/10 text-violet-400">
          <Keyboard className="w-5 h-5" />
        </div>
        <h3 className="font-semibold text-base">Keyboard shortcuts</h3>
      </div>
      <p className="text-sm text-muted-foreground mt-3 flex-1">
        Press{' '}
        <kbd className="px-1.5 py-0.5 rounded border border-border bg-muted text-xs font-mono">
          ?
        </kbd>{' '}
        anywhere in the app to see every available shortcut.
      </p>
      <button
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent('show-shortcuts'))}
        className="mt-4 inline-flex items-center justify-center gap-2 h-9 px-4 rounded-lg bg-muted text-sm font-medium hover:bg-muted/70 transition-colors"
      >
        <Keyboard className="w-4 h-4" />
        View shortcuts
      </button>
    </div>
  )
}

function SupportPage() {
  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <div className="p-2 rounded-xl bg-primary/10">
          <LifeBuoy className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Support</h1>
          <p className="text-sm text-muted-foreground">
            Get help from the community, contact the team, or catch up on updates
          </p>
        </div>
      </motion.div>

      {/* System Status */}
      <StatusCard />

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {links.map((link, i) => (
          <motion.div
            key={link.key}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05, duration: 0.4 }}
            className="h-full"
          >
            <a
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-start gap-4 p-5 rounded-xl bg-card/50 border border-border/50 hover:border-primary/30 hover:bg-card/80 transition-all duration-200 h-full"
            >
              <div
                className={cn(
                  'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
                  link.color
                )}
              >
                <link.icon className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-base group-hover:text-primary transition-colors">
                  {link.label}
                </h3>
                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                  {link.description}
                </p>
                <p className="text-xs text-primary/70 mt-2 truncate">
                  {link.url.replace('https://', '')}
                </p>
              </div>
              <ExternalLink className="w-5 h-5 text-muted-foreground/50 group-hover:text-muted-foreground transition-all shrink-0 mt-1" />
            </a>
          </motion.div>
        ))}
      </div>

      {/* FAQ */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="space-y-4"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-primary/10">
            <HelpCircle className="w-4 h-4 text-primary" />
          </div>
          <h2 className="text-lg font-semibold">Frequently asked questions</h2>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
          {faqs.map((faq) => (
            <FaqItem key={faq.question} question={faq.question} answer={faq.answer} />
          ))}
        </div>
      </motion.div>

      {/* Debug Info + Shortcuts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <DebugInfoCard />
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.05 }}
        >
          <ShortcutsCard />
        </motion.div>
      </div>
    </div>
  )
}
