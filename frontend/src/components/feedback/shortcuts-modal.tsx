// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Keyboard } from 'lucide-react'
import { useShortcutsList } from '../../hooks/use-keyboard-shortcuts'
import { cn } from '../../lib/utils'
import { Modal } from '../ui/modal'

export function ShortcutsModal() {
  const [isOpen, setIsOpen] = useState(false)
  const shortcuts = useShortcutsList()
  const isMac = /mac/i.test(navigator.platform)

  // 'mod' is ctrl-or-meta; render the label matching the user's platform
  const modifierLabel = (mod: string) => (mod === 'mod' ? (isMac ? '⌘' : 'Ctrl') : mod)

  useEffect(() => {
    const handleShow = () => setIsOpen(true)
    window.addEventListener('show-shortcuts', handleShow)
    return () => window.removeEventListener('show-shortcuts', handleShow)
  }, [])

  return (
    <Modal open={isOpen} onOpenChange={setIsOpen} showClose={false} className="bubble max-w-lg">
      <div className="flex items-center gap-3 px-5 pt-5 pb-2">
        <Keyboard className="w-5 h-5 text-primary" />
        <h2 className="text-lg font-semibold">Keyboard Shortcuts</h2>
      </div>

      <div className="p-6 pt-0 space-y-3">
        {shortcuts.map((shortcut, index) => (
          <motion.div
            key={shortcut.description}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.05 }}
            className="flex items-center justify-between py-2 border-b border-border/50 last:border-0"
          >
            <span className="text-sm text-muted-foreground">{shortcut.description}</span>
            <div className="flex items-center gap-1">
              {shortcut.modifiers?.map((mod) => (
                <kbd
                  key={mod}
                  className={cn(
                    'px-2 py-0.5 text-xs font-medium rounded',
                    'bg-muted border border-border',
                    'text-muted-foreground uppercase'
                  )}
                >
                  {modifierLabel(mod)}
                </kbd>
              ))}
              <kbd
                className={cn(
                  'px-2 py-0.5 text-xs font-medium rounded',
                  'bg-muted border border-border',
                  'text-muted-foreground uppercase'
                )}
              >
                {shortcut.key}
              </kbd>
            </div>
          </motion.div>
        ))}
      </div>
    </Modal>
  )
}
