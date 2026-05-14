import { motion } from 'framer-motion';
import {
  ArrowDownLeft,
  Server,
  Gift,
  Clock,
  User,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { formatDate } from '../../lib/utils';
import type { CreditTransaction } from '../../types/api';
import { Button } from '../ui/button';

interface CreditTransactionTableProps {
  transactions: CreditTransaction[];
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  isLoading?: boolean;
}

const TYPE_CONFIG: Record<string, { label: string; icon: React.ElementType; color: string; bg: string }> = {
  admin_grant: { label: 'Grant', icon: Gift, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  admin_deduct: { label: 'Deduct', icon: ArrowDownLeft, color: 'text-red-400', bg: 'bg-red-500/10' },
  server_usage: { label: 'Server Usage', icon: Server, color: 'text-blue-400', bg: 'bg-blue-500/10' },
  daily_allowance: { label: 'Daily Allowance', icon: Gift, color: 'text-violet-400', bg: 'bg-violet-500/10' },
};

function getTypeConfig(type: string) {
  return TYPE_CONFIG[type] || { label: type, icon: Clock, color: 'text-muted-foreground', bg: 'bg-muted' };
}

export function CreditTransactionTable({
  transactions,
  page,
  totalPages,
  onPageChange,
  isLoading,
}: CreditTransactionTableProps) {
  if (isLoading) {
    return <TransactionSkeleton />;
  }

  if (transactions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-3">
          <Clock className="w-6 h-6 text-muted-foreground" />
        </div>
        <p className="text-sm font-medium text-muted-foreground">No transactions found</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {transactions.map((tx, i) => {
          const config = getTypeConfig(tx.type);
          const Icon = config.icon;
          const isPositive = tx.amount > 0;

          return (
            <motion.div
              key={tx.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
              className="flex items-start gap-3 p-3 rounded-xl bg-card/30 border border-border/30 hover:bg-card/50 transition-colors"
            >
              <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', config.bg)}>
                <Icon className={cn('w-4 h-4', config.color)} />
              </div>

              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm font-medium truncate">{tx.description}</span>
                    <span className={cn('text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0', config.bg, config.color)}>
                      {config.label}
                    </span>
                  </div>
                  <span className={cn('font-mono font-semibold text-sm shrink-0', isPositive ? 'text-emerald-400' : 'text-red-400')}>
                    {isPositive ? '+' : ''}{tx.amount.toLocaleString()}
                  </span>
                </div>

                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatDate(tx.created_at)}
                  </span>
                  <span className="flex items-center gap-1">
                    <User className="w-3 h-3" />
                    Balance after: {tx.balance_after.toLocaleString()}
                  </span>
                  {tx.actor_id && (
                    <span className="flex items-center gap-1">
                      <User className="w-3 h-3" />
                      Actor: {tx.actor_id.slice(0, 8)}...
                    </span>
                  )}
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="w-8 h-8"
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="w-8 h-8"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function TransactionSkeleton() {
  return (
    <div className="space-y-2">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-start gap-3 p-3 rounded-xl bg-card/30 border border-border/30 animate-pulse">
          <div className="w-9 h-9 rounded-lg bg-muted shrink-0" />
          <div className="flex-1 space-y-2">
            <div className="flex items-center justify-between">
              <div className="h-4 w-40 bg-muted rounded" />
              <div className="h-4 w-16 bg-muted rounded" />
            </div>
            <div className="h-3 w-32 bg-muted rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}
