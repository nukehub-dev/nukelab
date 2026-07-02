// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { motion, AnimatePresence } from 'framer-motion'
import { Check } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { Row } from '@tanstack/react-table'

interface DataTableMobileProps<TData> {
  rows: Row<TData>[]
  cardRenderer?: (row: TData) => React.ReactNode
  getRowId: (row: Row<TData>) => string
  selectedRows: Record<string, boolean>
  onRowSelectionChange: (selection: Record<string, boolean>) => void
  enableRowSelection?: boolean
}

export function DataTableMobile<TData>({
  rows,
  cardRenderer,
  getRowId,
  selectedRows,
  onRowSelectionChange,
  enableRowSelection = true,
}: DataTableMobileProps<TData>) {
  const toggleRow = (rowId: string) => {
    onRowSelectionChange({
      ...selectedRows,
      [rowId]: !selectedRows[rowId],
    })
  }

  return (
    <div className="space-y-2">
      <AnimatePresence mode="popLayout">
        {rows.map((row, i) => {
          const rowId = getRowId(row)
          const isSelected = selectedRows[rowId]

          if (cardRenderer) {
            return (
              <motion.div
                key={rowId}
                layout
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ delay: i * 0.05, type: 'spring', stiffness: 300, damping: 30 }}
                className={cn(
                  'relative rounded-lg border transition-colors',
                  isSelected ? 'border-primary/50 bg-primary/5' : 'border-border/50 bg-card'
                )}
              >
                {enableRowSelection && (
                  <div className="absolute top-2 left-2 z-10">
                    <button
                      onClick={() => toggleRow(rowId)}
                      className={cn(
                        'w-5 h-5 rounded border flex items-center justify-center transition-colors',
                        isSelected ? 'bg-primary border-primary' : 'border-border bg-background'
                      )}
                    >
                      {isSelected && <Check className="w-3 h-3 text-primary-foreground" />}
                    </button>
                  </div>
                )}
                <div className={cn(enableRowSelection && 'pl-8')}>{cardRenderer(row.original)}</div>
              </motion.div>
            )
          }

          // Default card rendering
          return (
            <motion.div
              key={rowId}
              layout
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ delay: i * 0.05, type: 'spring', stiffness: 300, damping: 30 }}
              className={cn('bubble p-3 space-y-2', isSelected && 'border-primary/50')}
            >
              <div className="flex items-start justify-between">
                <div className="space-y-1 flex-1">
                  {row.getVisibleCells().map((cell) => (
                    <div key={cell.id} className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground font-medium">
                        {cell.column.columnDef.header as string}:
                      </span>
                      <span className="text-sm">{cell.getValue() as React.ReactNode}</span>
                    </div>
                  ))}
                </div>
                {enableRowSelection && (
                  <button
                    onClick={() => toggleRow(rowId)}
                    className={cn(
                      'w-5 h-5 rounded border flex items-center justify-center transition-colors shrink-0',
                      isSelected ? 'bg-primary border-primary' : 'border-border bg-background'
                    )}
                  >
                    {isSelected && <Check className="w-3 h-3 text-primary-foreground" />}
                  </button>
                )}
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
