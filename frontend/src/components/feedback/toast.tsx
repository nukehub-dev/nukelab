import { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, AlertCircle, AlertTriangle, Info, X } from 'lucide-react';
import { useToastStore } from '../../stores/toast-store';
import { cn } from '../../lib/utils';
import type { Toast, ToastType } from '../../stores/toast-store';

const toastIcons: Record<ToastType, typeof CheckCircle> = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

const toastStyles: Record<ToastType, string> = {
  success: 'shadow-[0_0_20px_-4px_rgba(16,185,129,0.25)] dark:border-emerald-500/15',
  error: 'shadow-[0_0_20px_-4px_rgba(239,68,68,0.25)] dark:border-red-500/15',
  warning: 'shadow-[0_0_20px_-4px_rgba(245,158,11,0.25)] dark:border-amber-500/15',
  info: 'shadow-[0_0_20px_-4px_rgba(59,130,246,0.25)] dark:border-blue-500/15',
};

const iconBgStyles: Record<ToastType, string> = {
  success: 'bg-emerald-500/15 text-emerald-500 dark:text-emerald-400',
  error: 'bg-red-500/15 text-red-500 dark:text-red-400',
  warning: 'bg-amber-500/15 text-amber-500 dark:text-amber-400',
  info: 'bg-blue-500/15 text-blue-500 dark:text-blue-400',
};

const titleColors: Record<ToastType, string> = {
  success: 'text-emerald-700 dark:text-emerald-300',
  error: 'text-red-700 dark:text-red-300',
  warning: 'text-amber-700 dark:text-amber-300',
  info: 'text-blue-700 dark:text-blue-300',
};

const progressColors: Record<ToastType, string> = {
  success: 'bg-emerald-400',
  error: 'bg-red-400',
  warning: 'bg-amber-400',
  info: 'bg-blue-400',
};

function ToastItem({ toast }: { toast: Toast }) {
  const removeToast = useToastStore((s) => s.removeToast);
  const Icon = toastIcons[toast.type];
  const duration = toast.duration ?? 5000;

  useEffect(() => {
    if (duration === Infinity) return;
    const timer = setTimeout(() => {
      removeToast(toast.id);
    }, duration);
    return () => clearTimeout(timer);
  }, [toast.id, duration, removeToast]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -50, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 100, scale: 0.9 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
      className={cn(
        'relative w-full max-w-sm rounded-xl border border-border/30 p-4 shadow-2xl backdrop-blur-xl overflow-hidden bg-background/80',
        toastStyles[toast.type]
      )}
    >
      {/* Colored tint overlay */}
      <div className={cn(
        'absolute inset-0 opacity-[0.08] dark:opacity-[0.12] pointer-events-none',
        toast.type === 'success' && 'bg-emerald-500',
        toast.type === 'error' && 'bg-red-500',
        toast.type === 'warning' && 'bg-amber-500',
        toast.type === 'info' && 'bg-blue-500',
      )} />

      <div className="relative flex items-start gap-3">
        <div className={cn('p-1.5 rounded-lg shrink-0', iconBgStyles[toast.type])}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0 pt-0.5">
          <p className={cn('font-semibold text-sm leading-tight', titleColors[toast.type])}>{toast.title}</p>
          {toast.message && (
            <p className="mt-1 text-xs text-foreground/65 dark:text-foreground/80 leading-relaxed">{toast.message}</p>
          )}
          {toast.action && (
            <button
              onClick={toast.action.onClick}
              className="mt-2 text-xs font-medium underline underline-offset-2 hover:opacity-80"
            >
              {toast.action.label}
            </button>
          )}
        </div>
        <button
          onClick={() => removeToast(toast.id)}
          className="shrink-0 p-1 rounded-md opacity-50 hover:opacity-100 hover:bg-foreground/10 transition-all text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Progress bar */}
      {duration !== Infinity && (
        <motion.div
          className={cn('absolute bottom-0 left-0 h-[3px] rounded-full', progressColors[toast.type])}
          initial={{ width: '100%' }}
          animate={{ width: '0%' }}
          transition={{ duration: duration / 1000, ease: 'linear' }}
        />
      )}
    </motion.div>
  );
}

export function ToastProvider() {
  const toasts = useToastStore((s) => s.toasts);

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-full max-w-sm pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <ToastItem toast={toast} />
          </div>
        ))}
      </AnimatePresence>
    </div>
  );
}
