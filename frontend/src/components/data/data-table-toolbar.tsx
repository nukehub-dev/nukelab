import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  X,
  Filter,
  Eye,
  List,
  LayoutGrid,
  ChevronDown,
  Check,
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
  const [openFilterKey, setOpenFilterKey] = useState<string | null>(null);
  const filterRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Close filter dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (openFilterKey) {
        const ref = filterRefs.current[openFilterKey];
        if (ref && !ref.contains(event.target as Node)) {
          setOpenFilterKey(null);
        }
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [openFilterKey]);

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
                'w-full h-9 pl-9 pr-8 rounded-lg border border-input bg-input/80',
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
              'h-9 px-3 rounded-lg border border-input/50 bg-input/80 text-sm font-medium',
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

          {/* Column Visibility - hidden in card view */}
          {!isMobileView && (
            <div className="relative">
              <button
                onClick={() => setShowColumnMenu(!showColumnMenu)}
                className={cn(
                  'h-9 px-3 rounded-lg border border-input/50 bg-input/80 text-sm font-medium',
                  'transition-colors hover:bg-accent flex items-center gap-2',
                  showColumnMenu && 'bg-primary/10 border-primary/30 text-primary'
                )}
              >
                <Eye className="w-4 h-4" />
                View
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
                    className="absolute right-0 mt-2 w-48 p-2 bg-popover border border-border rounded-xl shadow-lg z-50 space-y-1"
                  >
                    <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Toggle columns
                    </div>
                    {table.getAllLeafColumns()
                      .filter((column) => {
                        const header = column.columnDef.header;
                        return typeof header === 'string' && header.trim() !== '';
                      })
                      .map((column) => (
                        <button
                          key={column.id}
                          onClick={() => column.toggleVisibility()}
                          className={cn(
                            'w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm transition-colors',
                            column.getIsVisible()
                              ? 'text-foreground'
                              : 'text-muted-foreground'
                          )}
                        >
                          <Check className={cn('w-4 h-4', column.getIsVisible() ? 'opacity-100' : 'opacity-0')} />
                          <span>{column.columnDef.header as string}</span>
                        </button>
                      ))}
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>
          )}

          {/* View Toggle */}
          <button
            onClick={onViewToggle}
            className={cn(
              'h-9 px-3 rounded-lg border border-input/50 bg-input/80 text-sm font-medium',
              'transition-colors hover:bg-accent flex items-center gap-2',
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
          >
            <div className="flex flex-wrap items-center gap-2 p-3 rounded-lg border border-border/50 bg-muted/30">
              {filters.map((filter) => {
                const currentValue = (table.getColumn(filter.key)?.getFilterValue() as string) || '';
                const selectedOption = filter.options.find((opt) => opt.value === currentValue);
                const isOpen = openFilterKey === filter.key;
                
                return (
                  <div
                    key={filter.key}
                    ref={(el) => { filterRefs.current[filter.key] = el; }}
                    className="relative"
                  >
                    <button
                      onClick={() => setOpenFilterKey(isOpen ? null : filter.key)}
                      className={cn(
                        'relative h-8 px-3 pr-8 rounded-lg border text-sm font-medium',
                        'transition-colors flex items-center gap-2',
                        currentValue
                          ? 'bg-primary/10 border-primary/30 text-primary'
                          : 'border-border/50 bg-background hover:bg-accent'
                      )}
                    >
                      <span>{selectedOption ? selectedOption.label : filter.label}</span>
                      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
                    </button>
                    
                    <AnimatePresence>
                      {isOpen && (
                        <>
                          <div
                            className="fixed inset-0 z-40"
                            onClick={() => setOpenFilterKey(null)}
                          />
                          <motion.div
                            initial={{ opacity: 0, y: 4, scale: 0.95 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{ opacity: 0, y: 4, scale: 0.95 }}
                            transition={{ duration: 0.1 }}
                            className="absolute left-0 top-full mt-1 min-w-[160px] p-1.5 bg-popover border border-border rounded-xl shadow-lg z-50 space-y-1"
                          >
                            <button
                              onClick={() => {
                                const column = table.getColumn(filter.key);
                                if (column) column.setFilterValue(undefined);
                                setOpenFilterKey(null);
                              }}
                              className={cn(
                                'w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors',
                                !currentValue
                                  ? 'bg-primary/10 text-primary'
                                  : 'hover:bg-accent text-foreground'
                              )}
                            >
                              <Check className={cn('w-4 h-4', !currentValue ? 'opacity-100' : 'opacity-0')} />
                              <span>All {filter.label}s</span>
                            </button>
                            {filter.options.map((opt) => (
                              <button
                                key={opt.value}
                                onClick={() => {
                                  const column = table.getColumn(filter.key);
                                  if (column) column.setFilterValue(opt.value);
                                  setOpenFilterKey(null);
                                }}
                                className={cn(
                                  'w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors',
                                  currentValue === opt.value
                                    ? 'bg-primary/10 text-primary'
                                    : 'hover:bg-accent text-foreground'
                                )}
                              >
                                <Check className={cn('w-4 h-4', currentValue === opt.value ? 'opacity-100' : 'opacity-0')} />
                                <span>{opt.label}</span>
                              </button>
                            ))}
                          </motion.div>
                        </>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}

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
                <button
                  key={action.label}
                  onClick={() => action.onClick(selectedIds)}
                  className={cn(
                    'h-8 px-3 rounded-lg text-sm font-medium flex items-center gap-2',
                    'transition-all duration-100 active:translate-y-[1px]',
                    action.variant === 'destructive'
                      ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90 hover:brightness-110'
                      : 'bg-primary text-primary-foreground hover:bg-primary/90 hover:brightness-110'
                  )}
                >
                  {action.icon}
                  {action.label}
                </button>
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
