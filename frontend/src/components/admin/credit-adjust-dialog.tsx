import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  Plus,
  Minus,
  Wallet,
  AlertTriangle,
  CreditCard,
} from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '../ui/dialog';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { useCreditActions } from '../../hooks/use-credits';
import { useAuthStore, PERMISSIONS } from '../../stores/auth-store';
import { cn } from '../../lib/utils';
import type { User } from '../../types/api';

type Operation = 'grant' | 'deduct';

interface CreditAdjustDialogProps {
  user: User | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreditAdjustDialog({ user, open, onOpenChange }: CreditAdjustDialogProps) {
  const hasPermission = useAuthStore((state) => state.hasPermission);
  const canGrant = hasPermission(PERMISSIONS.CREDITS_GRANT);
  const canDeduct = hasPermission(PERMISSIONS.CREDITS_DEDUCT);

  const actions = useCreditActions();

  const [operation, setOperation] = useState<Operation>('grant');
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [amountError, setAmountError] = useState('');
  const [reasonError, setReasonError] = useState('');

  const currentBalance = user?.nuke_balance ?? 0;
  const numericAmount = parseInt(amount, 10) || 0;

  const newBalance = useMemo(() => {
    if (operation === 'grant') return currentBalance + numericAmount;
    return currentBalance - numericAmount;
  }, [operation, currentBalance, numericAmount]);

  const isOverdraft = newBalance < 0;
  const isBusy = actions.grantCredits.isPending || actions.deductCredits.isPending;

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setAmount('');
      setReason('');
      setAmountError('');
      setReasonError('');
      setOperation(canGrant ? 'grant' : 'deduct');
    }
    onOpenChange(open);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;

    let hasError = false;

    if (!amount || numericAmount <= 0) {
      setAmountError('Enter a valid amount greater than 0');
      hasError = true;
    } else {
      setAmountError('');
    }

    if (!reason.trim()) {
      setReasonError('Reason is required');
      hasError = true;
    } else {
      setReasonError('');
    }

    if (operation === 'deduct' && isOverdraft) {
      setAmountError('Amount exceeds current balance');
      hasError = true;
    }

    if (hasError) return;

    if (operation === 'grant') {
      actions.grantCredits.mutate(
        { userId: user.id, amount: numericAmount, reason: reason.trim() },
        { onSuccess: () => handleOpenChange(false) }
      );
    } else {
      actions.deductCredits.mutate(
        { userId: user.id, amount: numericAmount, reason: reason.trim() },
        { onSuccess: () => handleOpenChange(false) }
      );
    }
  };

  const availableOperations: { value: Operation; label: string; icon: React.ElementType; color: string; activeBg: string }[] = [];
  if (canGrant) {
    availableOperations.push({
      value: 'grant',
      label: 'Grant',
      icon: Plus,
      color: 'text-emerald-400',
      activeBg: 'bg-emerald-500/10 border-emerald-500/30',
    });
  }
  if (canDeduct) {
    availableOperations.push({
      value: 'deduct',
      label: 'Deduct',
      icon: Minus,
      color: 'text-red-400',
      activeBg: 'bg-red-500/10 border-red-500/30',
    });
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CreditCard className="w-5 h-5 text-primary" />
            Adjust Credits
          </DialogTitle>
          <DialogDescription>
            {user ? (
              <>
                Adjust credits for <span className="font-medium text-foreground">{user.username}</span>
              </>
            ) : (
              'Select a user to adjust credits'
            )}
          </DialogDescription>
        </DialogHeader>

        <form id="credit-adjust-form" onSubmit={handleSubmit} className="mt-4 space-y-5">
          {/* Operation Toggle */}
          {availableOperations.length > 1 && (
            <div className="flex gap-2 p-1 bg-muted rounded-xl">
              {availableOperations.map((op) => (
                <button
                  key={op.value}
                  type="button"
                  onClick={() => setOperation(op.value)}
                  className={cn(
                    'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                    operation === op.value
                      ? `${op.activeBg} ${op.color} shadow-sm`
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <op.icon className="w-4 h-4" />
                  {op.label}
                </button>
              ))}
            </div>
          )}

          {/* Amount */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Amount</label>
            <div className="relative">
              <Wallet className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                type="number"
                min={1}
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                  if (amountError) setAmountError('');
                }}
                placeholder="0"
                className="pl-10"
                disabled={isBusy}
              />
            </div>
            {amountError && <p className="text-xs text-destructive">{amountError}</p>}
          </div>

          {/* Reason */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Reason</label>
            <Input
              type="text"
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                if (reasonError) setReasonError('');
              }}
              placeholder="e.g., Monthly bonus, Refund, Server overcharge"
              disabled={isBusy}
            />
            {reasonError && <p className="text-xs text-destructive">{reasonError}</p>}
            <p className="text-xs text-muted-foreground">
              This reason will be recorded in the transaction audit log.
            </p>
          </div>

          {/* Balance Preview */}
          <motion.div
            layout
            className={cn(
              'p-4 rounded-xl border space-y-3',
              operation === 'grant'
                ? 'bg-emerald-500/5 border-emerald-500/20'
                : 'bg-red-500/5 border-red-500/20'
            )}
          >
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Current Balance</span>
              <span className="font-mono font-medium">{currentBalance.toLocaleString()} NUKE</span>
            </div>

            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{operation === 'grant' ? 'Granting' : 'Deducting'}</span>
              <span className={cn('font-mono font-medium', operation === 'grant' ? 'text-emerald-400' : 'text-red-400')}>
                {operation === 'grant' ? '+' : '-'}{numericAmount.toLocaleString()} NUKE
              </span>
            </div>

            <div className="h-px bg-border/50" />

            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">New Balance</span>
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-lg">{newBalance.toLocaleString()} NUKE</span>
                {isOverdraft && (
                  <span className="inline-flex items-center gap-1 text-xs text-destructive">
                    <AlertTriangle className="w-3 h-3" />
                    Overdraft
                  </span>
                )}
              </div>
            </div>

            {isOverdraft && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 text-destructive text-xs"
              >
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>This deduction would result in a negative balance. Reduce the amount or grant credits first.</span>
              </motion.div>
            )}
          </motion.div>
        </form>

        <DialogFooter>
          <Button variant="outline" type="button" onClick={() => handleOpenChange(false)} disabled={isBusy}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="credit-adjust-form"
            loading={isBusy}
            variant={operation === 'deduct' ? 'destructive' : 'default'}
            disabled={isOverdraft}
          >
            {operation === 'grant' ? 'Grant Credits' : 'Deduct Credits'}
          </Button>
        </DialogFooter>
        <DialogClose onClick={() => handleOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
