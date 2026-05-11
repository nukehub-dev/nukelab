import { useState, useCallback } from 'react';
import {
  AlertTriangle,
  Trash2,
  Ban,
  RefreshCw,
  type LucideIcon,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { modalOverlayVariants } from '../../lib/animations';
import { Button } from './button';
import { cn } from '../../lib/utils';

export type ConfirmVariant = 'danger' | 'warning' | 'info' | 'destructive';

interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: ConfirmVariant;
  icon?: LucideIcon;
}

interface ConfirmState extends ConfirmOptions {
  isOpen: boolean;
  resolve: ((value: boolean) => void) | null;
}

const variantConfig: Record<ConfirmVariant, { icon: LucideIcon; color: string; buttonVariant: 'destructive' | 'default' | 'secondary' }> = {
  danger: { icon: Trash2, color: 'text-destructive', buttonVariant: 'destructive' },
  warning: { icon: AlertTriangle, color: 'text-amber-500', buttonVariant: 'default' },
  info: { icon: RefreshCw, color: 'text-primary', buttonVariant: 'default' },
  destructive: { icon: Ban, color: 'text-destructive', buttonVariant: 'destructive' },
};

export function useConfirmDialog() {
  const [state, setState] = useState<ConfirmState>({
    isOpen: false,
    title: '',
    description: '',
    confirmLabel: 'Confirm',
    cancelLabel: 'Cancel',
    variant: 'info',
    resolve: null,
  });

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setState({
        ...options,
        confirmLabel: options.confirmLabel ?? 'Confirm',
        cancelLabel: options.cancelLabel ?? 'Cancel',
        variant: options.variant ?? 'info',
        isOpen: true,
        resolve,
      });
    });
  }, []);

  const handleClose = useCallback(
    (value: boolean) => {
      state.resolve?.(value);
      setState((prev) => ({ ...prev, isOpen: false, resolve: null }));
    },
    [state.resolve]
  );

  const config = variantConfig[state.variant ?? 'info'];
  const Icon = state.icon ?? config.icon;

  const dialog = (
    <AnimatePresence>
      {state.isOpen && (
        <>
          {/* Overlay */}
          <motion.div
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
            variants={modalOverlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={() => handleClose(false)}
          />
          {/* Dialog */}
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              className="relative w-full max-w-md rounded-2xl bg-card/95 backdrop-blur-xl border border-border/50 shadow-2xl overflow-hidden"
              initial={{ scale: 0.9, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 20 }}
              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Top accent line */}
              <div
                className={cn(
                  'h-1 w-full',
                  state.variant === 'danger' || state.variant === 'destructive'
                    ? 'bg-destructive'
                    : state.variant === 'warning'
                      ? 'bg-amber-500'
                      : 'bg-primary'
                )}
              />

              <div className="p-6">
                {/* Icon + Title */}
                <div className="flex items-start gap-4">
                  <div
                    className={cn(
                      'flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center',
                      state.variant === 'danger' || state.variant === 'destructive'
                        ? 'bg-destructive/10'
                        : state.variant === 'warning'
                          ? 'bg-amber-500/10'
                          : 'bg-primary/10'
                    )}
                  >
                    <Icon
                      className={cn('w-5 h-5', config.color)}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-lg font-semibold">{state.title}</h3>
                    {state.description && (
                      <p className="text-sm text-muted-foreground mt-1">
                        {state.description}
                      </p>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 mt-6 pt-4 border-t border-border/50">
                  <Button
                    variant="outline"
                    onClick={() => handleClose(false)}
                    className="w-full sm:w-auto"
                  >
                    {state.cancelLabel}
                  </Button>
                  <Button
                    variant={config.buttonVariant}
                    onClick={() => handleClose(true)}
                    className="w-full sm:w-auto"
                  >
                    {state.confirmLabel}
                  </Button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );

  return { confirm, dialog };
}
