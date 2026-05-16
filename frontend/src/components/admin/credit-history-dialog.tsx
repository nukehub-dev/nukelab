import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  History,
  ArrowDownLeft,
  Server,
  Gift,
  Clock,
  ChevronLeft,
  ChevronRight,
  SlidersHorizontal,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from 'lucide-react';
import { useCreditHistory } from '../../hooks/use-credits';
import { formatDate, cn } from '../../lib/utils';
import { Button } from '../ui/button';
import { Tooltip } from '../ui/tooltip';
import type { User as UserType, CreditTransaction } from '../../types/api';

interface CreditHistoryDialogProps {
  user: UserType | null;
  open: boolean;
  onClose: () => void;
  usersMap?: Record<string, string>;
}

const TYPE_CONFIG: Record<string, { label: string; icon: React.ElementType; color: string; bg: string }> = {
  admin_grant: { label: 'Grant', icon: Gift, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  admin_deduct: { label: 'Deduct', icon: ArrowDownLeft, color: 'text-red-400', bg: 'bg-red-500/10' },
  server_usage: { label: 'Server Usage', icon: Server, color: 'text-blue-400', bg: 'bg-blue-500/10' },
  daily_allowance: { label: 'Daily Allowance', icon: Gift, color: 'text-violet-400', bg: 'bg-violet-500/10' },
};

const FILTER_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'admin_grant', label: 'Grant' },
  { value: 'admin_deduct', label: 'Deduct' },
  { value: 'server_usage', label: 'Usage' },
  { value: 'daily_allowance', label: 'Allowance' },
];

function getTypeConfig(type: string) {
  return TYPE_CONFIG[type] || { label: type, icon: Clock, color: 'text-muted-foreground', bg: 'bg-muted' };
}

export function CreditHistoryDialog({ user, open, onClose, usersMap = {} }: CreditHistoryDialogProps) {
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [typeFilter, setTypeFilter] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortDesc, setSortDesc] = useState(true);

  const { data, isLoading } = useCreditHistory(
    user?.id || '',
    {
      page,
      limit,
      transaction_type: typeFilter || undefined,
      sort_by: sortBy,
      sort_order: sortDesc ? 'desc' : 'asc',
    }
  );

  const transactions = data?.transactions || [];
  const totalPages = data?.pagination.total_pages || 1;
  const total = data?.pagination.total || 0;

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortDesc(!sortDesc);
    } else {
      setSortBy(column);
      setSortDesc(column === 'created_at');
    }
    setPage(1);
  };

  const SortIcon = ({ column }: { column: string }) => {
    if (sortBy !== column) return <ArrowUpDown className="w-3 h-3 opacity-30" />;
    return sortDesc ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />;
  };

  if (!open) return null;

  return (
    <AnimatePresence>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            className="w-full max-w-4xl max-h-[90vh] rounded-2xl bg-card/95 backdrop-blur-xl border border-border/50 shadow-2xl overflow-hidden flex flex-col"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="h-1 bg-primary" />
            <div className="p-5 border-b border-border/50 space-y-4 shrink-0">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <span className="text-sm font-medium text-primary">
                      {user?.username?.slice(0, 2).toUpperCase()}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-semibold text-lg truncate">{user?.username}</h3>
                    <p className="text-sm text-muted-foreground">{user?.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <div className="font-mono font-bold text-lg">{user?.nuke_balance.toLocaleString()} NUKE</div>
                    <div className="text-xs text-muted-foreground">Current Balance</div>
                  </div>
                  <Button variant="ghost" size="sm" onClick={onClose}>
                    <X className="w-4 h-4" />
                  </Button>
                </div>
              </div>

              {/* Filter + Count */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <History className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm font-medium">Transaction History</span>
                  <span className="text-xs text-muted-foreground">({total})</span>
                </div>
                <div className="flex items-center gap-1 p-1 bg-muted rounded-lg">
                  <SlidersHorizontal className="w-3 h-3 text-muted-foreground ml-2 mr-1" />
                  {FILTER_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => { setTypeFilter(opt.value); setPage(1); }}
                      className={cn(
                        'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                        typeFilter === opt.value
                          ? 'bg-background text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-auto">
              {/* Column Headers */}
              <div className="grid grid-cols-[100px_1fr_100px_100px_130px] gap-3 px-5 py-2.5 text-xs font-medium text-muted-foreground border-b border-border/30 bg-muted/20 sticky top-0 z-10">
                <button onClick={() => handleSort('type')} className="flex items-center gap-1 hover:text-primary transition-colors text-left">
                  Type <SortIcon column="type" />
                </button>
                <button onClick={() => handleSort('description')} className="flex items-center gap-1 hover:text-primary transition-colors text-left">
                  Description <SortIcon column="description" />
                </button>
                <button onClick={() => handleSort('amount')} className="flex items-center gap-1 hover:text-primary transition-colors justify-end">
                  Amount <SortIcon column="amount" />
                </button>
                <button onClick={() => handleSort('balance_after')} className="flex items-center gap-1 hover:text-primary transition-colors justify-end">
                  Balance <SortIcon column="balance_after" />
                </button>
                <button onClick={() => handleSort('created_at')} className="flex items-center gap-1 hover:text-primary transition-colors justify-end">
                  Time <SortIcon column="created_at" />
                </button>
              </div>

              {isLoading ? (
                <TransactionSkeleton />
              ) : transactions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16">
                  <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-3">
                    <History className="w-6 h-6 text-muted-foreground" />
                  </div>
                  <p className="text-sm font-medium text-muted-foreground">No transactions found</p>
                </div>
              ) : (
                <div className="divide-y divide-border/20">
                  {transactions.map((tx) => (
                    <TransactionRow key={tx.id} transaction={tx} usersMap={usersMap} />
                  ))}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="p-3 border-t border-border/50 flex items-center justify-between shrink-0">
              <span className="text-xs text-muted-foreground">
                {total > 0 ? `Showing ${(page - 1) * limit + 1} to ${Math.min(page * limit, total)} of ${total}` : 'No results'}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(1)}
                  disabled={page <= 1}
                  className="h-7 w-7 p-0"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => p - 1)}
                  disabled={page <= 1}
                  className="h-7 w-7 p-0"
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <div className="flex items-center gap-1 px-2">
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    let pageNum: number;
                    if (totalPages <= 5) {
                      pageNum = i + 1;
                    } else if (page <= 3) {
                      pageNum = i + 1;
                    } else if (page >= totalPages - 2) {
                      pageNum = totalPages - 4 + i;
                    } else {
                      pageNum = page - 2 + i;
                    }
                    return (
                      <button
                        key={pageNum}
                        onClick={() => setPage(pageNum)}
                        className={cn(
                          'min-w-[1.75rem] h-7 px-1.5 rounded-lg text-xs font-medium transition-colors',
                          page === pageNum
                            ? 'bg-primary text-primary-foreground'
                            : 'hover:bg-accent'
                        )}
                      >
                        {pageNum}
                      </button>
                    );
                  })}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= totalPages}
                  className="h-7 w-7 p-0"
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(totalPages)}
                  disabled={page >= totalPages}
                  className="h-7 w-7 p-0"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

function TransactionRow({ transaction: tx, usersMap }: { transaction: CreditTransaction; usersMap: Record<string, string> }) {
  const config = getTypeConfig(tx.type);
  const Icon = config.icon;
  const isPositive = tx.amount > 0;
  const actorName = tx.actor_id ? (usersMap[tx.actor_id] || `${tx.actor_id.slice(0, 8)}...`) : null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="grid grid-cols-[100px_1fr_100px_100px_130px] gap-3 px-5 py-3 items-center hover:bg-muted/20 transition-colors"
    >
      {/* Type */}
      <div className="flex items-center gap-2">
        <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0', config.bg)}>
          <Icon className={cn('w-4 h-4', config.color)} />
        </div>
        <span className={cn('text-[10px] px-1.5 py-0.5 rounded-full font-medium', config.bg, config.color)}>
          {config.label}
        </span>
      </div>

      {/* Description */}
      <div className="min-w-0">
        <Tooltip content={tx.description}>
          <p className="text-sm font-medium line-clamp-2 cursor-help">{tx.description}</p>
        </Tooltip>
        {actorName && (
          <span className="text-[10px] text-muted-foreground/60 mt-0.5 block">
            by {actorName}
          </span>
        )}
      </div>

      {/* Amount */}
      <span className={cn('font-mono font-semibold text-sm text-right', isPositive ? 'text-emerald-400' : 'text-red-400')}>
        {isPositive ? '+' : ''}{tx.amount.toLocaleString()}
      </span>

      {/* Balance After */}
      <span className="font-mono text-sm text-right text-muted-foreground">
        {tx.balance_after.toLocaleString()}
      </span>

      {/* Time */}
      <span className="text-xs text-muted-foreground text-right whitespace-nowrap">
        {formatDate(tx.created_at)}
      </span>
    </motion.div>
  );
}

function TransactionSkeleton() {
  return (
    <div className="divide-y divide-border/20">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="grid grid-cols-[100px_1fr_100px_100px_130px] gap-3 px-5 py-3 items-center animate-pulse">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-muted shrink-0" />
            <div className="h-4 w-14 bg-muted rounded" />
          </div>
          <div className="space-y-1.5">
            <div className="h-4 w-48 bg-muted rounded" />
            <div className="h-3 w-20 bg-muted rounded" />
          </div>
          <div className="h-4 w-12 bg-muted rounded justify-self-end" />
          <div className="h-4 w-12 bg-muted rounded justify-self-end" />
          <div className="h-3 w-20 bg-muted rounded justify-self-end" />
        </div>
      ))}
    </div>
  );
}
