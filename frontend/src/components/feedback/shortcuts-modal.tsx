// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useEffect, useMemo } from 'react'
import { motion } from 'framer-motion'
import { Keyboard } from 'lucide-react'
import { useShortcutsList } from '../../hooks/use-keyboard-shortcuts'
import { cn } from '../../lib/utils'
import { Modal } from '../ui/modal'

type ShortcutEntry = ReturnType<typeof useShortcutsList>[number]

interface ShortcutGroup {
  description: string
  combos: Pick<ShortcutEntry, 'key' | 'modifiers'>[]
}

export function ShortcutsModal() {
  const [isOpen, setIsOpen] = useState(false)
  const shortcuts = useShortcutsList()
  const isMac = /mac/i.test(navigator.platform)

  // 'mod' is ctrl-or-meta; render the label matching the user's platform
  const modifierLabel = (mod: string) => (mod === 'mod' ? (isMac ? '⌘' : 'Ctrl') : mod)

  // One row per action: shortcuts sharing a description (e.g. Ctrl+K and /
  // both opening search) are grouped and their key combos shown side by side.
  const groups = useMemo<ShortcutGroup[]>(() => {
    const map = new Map<string, ShortcutGroup>()
    for (const s of shortcuts) {
      const existing = map.get(s.description)
      if (existing) {
        existing.combos.push({ key: s.key, modifiers: s.modifiers })
      } else {
        map.set(s.description, {
          description: s.description,
          combos: [{ key: s.key, modifiers: s.modifiers }],
        })
      }
    }
    return [...map.values()]
  }, [shortcuts])

  useEffect(() => {
    const handleShow = () => setIsOpen(true)
    window.addEventListener('show-shortcuts', handleShow)
    return () => window.removeEventListener('show-shortcuts', handleShow)
  }, [])

  const kbdClass = cn(
    'px-2 py-0.5 text-xs font-medium rounded',
    'bg-muted border border-border',
    'text-muted-foreground uppercase'
  )

  return (
    <Modal open={isOpen} onOpenChange={setIsOpen} showClose={false} className="bubble max-w-lg">
      <div className="flex items-center gap-3 px-5 pt-5 pb-2">
        <Keyboard className="w-5 h-5 text-primary" />
        <h2 className="text-lg font-semibold">Keyboard Shortcuts</h2>
      </div>

      <div className="p-6 pt-0 space-y-3">
        {groups.map((group, index) => (
          <motion.div
            key={group.description}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.05 }}
            className="flex items-center justify-between py-2 border-b border-border/50 last:border-0"
          >
            <span className="text-sm text-muted-foreground">{group.description}</span>
            <div className="flex items-center gap-1">
              {group.combos.map((combo, comboIndex) => (
                <span key={comboIndex} className="flex items-center gap-1">
                  {comboIndex > 0 && (
                    <span className="text-xs text-muted-foreground/60 px-0.5">or</span>
                  )}
                  {combo.modifiers?.map((mod) => (
                    <kbd key={mod} className={kbdClass}>
                      {modifierLabel(mod)}
                    </kbd>
                  ))}
                  <kbd className={kbdClass}>{combo.key}</kbd>
                </span>
              ))}
            </div>
          </motion.div>
        ))}
      </div>
    </Modal>
  )
}
