// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { LifeBuoy, MessagesSquare, Mail, Newspaper, ExternalLink } from 'lucide-react'
import { motion } from 'framer-motion'
import { EXTERNAL_LINKS } from '../lib/external-links'
import { cn } from '../lib/utils'

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
    </div>
  )
}
