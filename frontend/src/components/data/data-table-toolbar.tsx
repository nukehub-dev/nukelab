import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  X,
  Filter,
  Columns,
  List,
  LayoutGrid,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Table } from '@tanstack/react-table';

interface FilterConfig {
  key: string;
  label: string;
  options: Array<{ label: string; value: string }>;
}

interface BulkAction {
  label: string;
  icon: React.ReactNode;
  onClick: (selectedIds: string[]) => void;
  variant?: 'default' | 'destructive';
}

interface DataTableToolbarProps<TData> {
  table: Table<TData>;
  globalFilter: string;
  onGlobalFilterChange: (filter: string) => void;
  selectedCount: number;
  selectedIds: string[];
  bulkActions?: BulkAction[];
  filters?: FilterConfig[];
  searchable?: boolean;
  searchPlaceholder?: string;
  onViewToggle: () => void;
  isMobileView: boolean;
}

export function DataTableToolbar<TData>({
  table,
  globalFilter,
  onGlobalFilterChange,
  selectedCount,
  selectedIds,
  bulkActions,
  filters,
  searchable = true,
  searchPlaceholder = 'Search...',
  onViewToggle,
  isMobileView,
}: DataTableToolbarProps<TData>) {
  const [showFilters, setShowFilters] = useState(false);
  const [showColumnMenu, setShowColumnMenu] = useState(false);

  return (
    <div className="space-y-3">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        {/* Search */}
        {searchable && (
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={globalFilter}
              onChange={(e) => onGlobalFilterChange(e.target.value)}
              placeholder={searchPlaceholder}
              className={cn(
                'w-full h-9 pl-9 pr-8 rounded-lg border border-input bg-background',
                'text-sm placeholder:text-muted-foreground',
                'focus:outline-none focus:ring-2 focus:ring-ring/50'
              )}
            />
            {globalFilter && (
              <button
                onClick={() => onGlobalFilterChange('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-accent"
              >
                <X className="w-3.5 h-3.5 text-muted-foreground" />
              </button>
            )}
          </div>
        )}

        <div className="flex items-center gap-2">
          {/* Filter Button */}
          {filters && filters.length > 0 && (
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={cn(
                'h-9 px-3 rounded-lg border border-border/50 text-sm font-medium',
                'transition-colors hover:bg-accent flex items-center gap-2',
                showFilters && 'bg-primary/10 border-primary/30 text-primary'
              )}
            >
              <Filter className="w-4 h-4" />
              Filters
              {table.getState().columnFilters.length > 0 && (
                <span className="bg-primary text-primary-foreground text-xs px-1.5 py-0.5 rounded-full">
                  {table.getState().columnFilters.length}
                </span>
              )}
            </button>
          )}

          {/* Column Visibility */}
          <div className="relative">
            <button
              onClick={() => setShowColumnMenu(!showColumnMenu)}
              className={cn(
                'h-9 px-3 rounded-lg border border-border/50 text-sm font-medium',
                'transition-colors hover:bg-accent flex items-center gap-2',
                showColumnMenu && 'bg-primary/10 border-primary/30 text-primary'
              )}
            >
              <Columns className="w-4 h-4" />
              Columns
            </button>

            <AnimatePresence>
              {showColumnMenu && (
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setShowColumnMenu(false)}
                  />
                  <motion.div
                    initial={{ opacity: 0, y: 10, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 10, scale: 0.95 }}
                    className="absolute right-0 mt-2 w-48 p-2 bg-popover border border-border rounded-xl shadow-lg z-50"
                  >
                    <div className="space-y-1">
                      {table.getAllLeafColumns().map((column) => (
                        <label
                          key={column.id}
                          className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-accent cursor-pointer text-sm"
                        >
                          <input
                            type="checkbox"
                            checked={column.getIsVisible()}
                            onChange={column.getToggleVisibilityHandler()}
                            className="rounded border-border"
                          />
                          <span>{column.columnDef.header as string}</span>
                        </label>
                      ))}
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>

          {/* View Toggle */}
          <button
            onClick={onViewToggle}
            className={cn(
              'h-9 px-3 rounded-lg border border-border/50 text-sm font-medium',
              'transition-colors hover:bg-accent flex items-center gap-2 md:hidden',
              isMobileView && 'bg-primary/10 border-primary/30 text-primary'
            )}
          >
            {isMobileView ? (
              <>
                <List className="w-4 h-4" />
                List
              </>
            ) : (
              <>
                <LayoutGrid className="w-4 h-4" />
                Cards
              </>
            )}
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <AnimatePresence>
        {showFilters && filters && filters.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="flex flex-wrap items-center gap-2 p-3 rounded-lg border border-border/50 bg-muted/30">
              {filters.map((filter) => (
                <div key={filter.key} className="relative">
                  <select
                    value={
                      (table.getColumn(filter.key)?.getFilterValue() as string) || ''
                    }
                    onChange={(e) => {
                      const value = e.target.value;
                      const column = table.getColumn(filter.key);
                      if (column) {
                        column.setFilterValue(value || undefined);
                      }
                    }}
                    className={cn(
                      'h-8 px-3 pr-8 rounded-lg border border-border/50 bg-background',
                      'text-sm focus:outline-none focus:ring-2 focus:ring-ring/50',
                      'appearance-none cursor-pointer'
                    )}
                  >
                    <option value="">{filter.label}</option>
                    {filter.options.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <Filter className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
                </div>
              ))}

              {table.getState().columnFilters.length > 0 && (
                <button
                  onClick={() => table.resetColumnFilters()}
                  className="h-8 px-3 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                >
                  Clear filters
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bulk Actions Bar */}
      <AnimatePresence>
        {selectedCount > 0 && bulkActions && bulkActions.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="flex items-center justify-between p-3 rounded-lg border border-primary/30 bg-primary/5"
          >
            <span className="text-sm font-medium">
              {selectedCount} selected
            </span>
            <div className="flex items-center gap-2">
              {bulkActions.map((action) => (
                <motion.button
                  key={action.label}
                  onClick={() => action.onClick(selectedIds)}
                  className={cn(
                    'h-8 px-3 rounded-lg text-sm font-medium flex items-center gap-2',
                    'transition-colors',
                    action.variant === 'destructive'
                      ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
                      : 'bg-primary text-primary-foreground hover:bg-primary/90'
                  )}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.95 }}
                >
                  {action.icon}
                  {action.label}
                </motion.button>
              ))}
              <button
                onClick={() => table.toggleAllRowsSelected(false)}
                className="h-8 px-3 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              >
                Clear
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
