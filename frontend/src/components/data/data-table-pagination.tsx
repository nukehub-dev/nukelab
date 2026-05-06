import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ChevronDown, Check } from 'lucide-react';
import { cn } from '../../lib/utils';

interface DataTablePaginationProps {
  page: number;
  limit: number;
  totalCount: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  onLimitChange: (limit: number) => void;
}

export function DataTablePagination({
  page,
  limit,
  totalCount,
  pageCount,
  onPageChange,
  onLimitChange,
}: DataTablePaginationProps) {
  const startItem = (page - 1) * limit + 1;
  const endItem = Math.min(page * limit, totalCount);

  const limitOptions = [10, 20, 50, 100];
  const [showLimitDropdown, setShowLimitDropdown] = useState(false);
  const limitRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (limitRef.current && !limitRef.current.contains(event.target as Node)) {
        setShowLimitDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-4 py-4">
      <div className="text-sm text-muted-foreground">
        Showing <span className="font-medium">{startItem}</span> to{' '}
        <span className="font-medium">{endItem}</span> of{' '}
        <span className="font-medium">{totalCount}</span> results
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1">
          <button
            onClick={() => onPageChange(1)}
            disabled={page <= 1}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
          >
            <ChevronsLeft className="w-4 h-4" />
          </button>
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
          >
            <ChevronLeft className="w-4 h-4" />
          </button>

          <div className="flex items-center gap-1 px-2">
            {Array.from({ length: Math.min(5, pageCount) }, (_, i) => {
              let pageNum: number;
              if (pageCount <= 5) {
                pageNum = i + 1;
              } else if (page <= 3) {
                pageNum = i + 1;
              } else if (page >= pageCount - 2) {
                pageNum = pageCount - 4 + i;
              } else {
                pageNum = page - 2 + i;
              }

              return (
                <button
                  key={pageNum}
                  onClick={() => onPageChange(pageNum)}
                  className={cn(
                    'min-w-[2rem] h-8 px-2 rounded-lg text-sm font-medium transition-colors cursor-pointer',
                    page === pageNum
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-accent border border-border/50'
                  )}
                >
                  {pageNum}
                </button>
              );
            })}
          </div>

          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= pageCount}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            onClick={() => onPageChange(pageCount)}
            disabled={page >= pageCount}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
          >
            <ChevronsRight className="w-4 h-4" />
          </button>
        </div>

        <div ref={limitRef} className="relative">
          <button
            onClick={() => setShowLimitDropdown(!showLimitDropdown)}
            className={cn(
              'relative h-8 px-3 pr-8 rounded-lg border text-sm font-medium',
              'transition-colors flex items-center gap-2 cursor-pointer',
              'border-border/50 bg-background hover:bg-accent'
            )}
          >
            <span>{limit} / page</span>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
          </button>

          <AnimatePresence>
            {showLimitDropdown && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setShowLimitDropdown(false)}
                />
                <motion.div
                  initial={{ opacity: 0, y: 4, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 4, scale: 0.95 }}
                  transition={{ duration: 0.1 }}
                            className="absolute right-0 bottom-full mb-1 min-w-[120px] p-1.5 bg-popover border border-border rounded-xl shadow-lg z-50 space-y-1"
                >
                  {limitOptions.map((opt) => (
                      <button
                      key={opt}
                      onClick={() => {
                        onLimitChange(opt);
                        setShowLimitDropdown(false);
                      }}
                      className={cn(
                        'w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors whitespace-nowrap cursor-pointer',
                        limit === opt
                          ? 'bg-primary/10 text-primary'
                          : 'hover:bg-accent text-foreground'
                      )}
                    >
                      <Check className={cn('w-4 h-4 shrink-0', limit === opt ? 'opacity-100' : 'opacity-0')} />
                      <span>{opt} / page</span>
                    </button>
                  ))}
                </motion.div>
              </>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
