import { motion } from 'framer-motion';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
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

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-4 py-4">
      <div className="text-sm text-muted-foreground">
        Showing <span className="font-medium">{startItem}</span> to{' '}
        <span className="font-medium">{endItem}</span> of{' '}
        <span className="font-medium">{totalCount}</span> results
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1">
          <motion.button
            onClick={() => onPageChange(1)}
            disabled={page <= 1}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
            whileTap={{ scale: 0.95 }}
          >
            <ChevronsLeft className="w-4 h-4" />
          </motion.button>
          <motion.button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
            whileTap={{ scale: 0.95 }}
          >
            <ChevronLeft className="w-4 h-4" />
          </motion.button>

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
                <motion.button
                  key={pageNum}
                  onClick={() => onPageChange(pageNum)}
                  className={cn(
                    'min-w-[2rem] h-8 px-2 rounded-lg text-sm font-medium transition-colors',
                    page === pageNum
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-accent border border-border/50'
                  )}
                  whileTap={{ scale: 0.95 }}
                >
                  {pageNum}
                </motion.button>
              );
            })}
          </div>

          <motion.button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= pageCount}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
            whileTap={{ scale: 0.95 }}
          >
            <ChevronRight className="w-4 h-4" />
          </motion.button>
          <motion.button
            onClick={() => onPageChange(pageCount)}
            disabled={page >= pageCount}
            className={cn(
              'p-2 rounded-lg border border-border/50 transition-colors',
              'hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'
            )}
            whileTap={{ scale: 0.95 }}
          >
            <ChevronsRight className="w-4 h-4" />
          </motion.button>
        </div>

        <select
          value={limit}
          onChange={(e) => onLimitChange(Number(e.target.value))}
          className="h-8 rounded-lg border border-border/50 bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
        >
          {limitOptions.map((opt) => (
            <option key={opt} value={opt}>
              {opt} / page
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
