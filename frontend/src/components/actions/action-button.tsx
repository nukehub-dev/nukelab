import { cn } from '../../lib/utils';
import { motion } from 'framer-motion';
import { ACTION_CONFIGS, type ActionType } from './action-config';

interface ActionButtonProps {
  action: ActionType;
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  size?: 'sm' | 'default' | 'lg';
  className?: string;
}

export function ActionButton({
  action,
  onClick,
  loading = false,
  disabled = false,
  size = 'default',
  className,
}: ActionButtonProps) {
  const config = ACTION_CONFIGS[action];
  if (!config) return null;

  const { label, icon: Icon, variant, tone, loadingLabel } = config;

  const sizeClasses = {
    sm: 'h-7 px-2.5 text-xs gap-1.5',
    default: 'h-9 px-4 text-sm gap-2',
    lg: 'h-10 px-5 text-sm gap-2',
  };

  const variantClasses = {
    default: cn(
      'bg-primary text-primary-foreground hover:bg-primary/90',
      tone === 'destructive' && 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
      tone === 'success' && 'bg-emerald-500 text-white hover:bg-emerald-500/90',
      tone === 'warning' && 'bg-amber-500 text-white hover:bg-amber-500/90',
    ),
    outline: cn(
      'border border-input bg-background hover:bg-accent',
      tone === 'destructive' && 'border-red-500/30 text-red-400 hover:bg-red-500/10',
      tone === 'success' && 'border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10',
      tone === 'warning' && 'border-amber-500/30 text-amber-400 hover:bg-amber-500/10',
      tone === 'primary' && 'border-primary/30 text-primary hover:bg-primary/10',
    ),
    ghost: cn(
      'hover:bg-accent hover:text-accent-foreground',
      tone === 'destructive' && 'text-red-400 hover:bg-red-500/10',
      tone === 'success' && 'text-emerald-400 hover:bg-emerald-500/10',
      tone === 'warning' && 'text-amber-400 hover:bg-amber-500/10',
      tone === 'primary' && 'text-primary hover:bg-primary/10',
    ),
    destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
  };

  return (
    <motion.button
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium whitespace-nowrap',
        'transition-all duration-200',
        'disabled:pointer-events-none disabled:opacity-50',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
        'relative overflow-hidden',
        sizeClasses[size],
        variantClasses[variant],
        className
      )}
      whileHover={{ scale: 1.02, y: -1 }}
      whileTap={{ scale: 0.95 }}
      transition={{ type: 'spring', stiffness: 400, damping: 17 }}
    >
      {loading && (
        <span className="absolute inset-0 flex items-center justify-center bg-inherit">
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
          >
            <Icon className="w-4 h-4" />
          </motion.span>
        </span>
      )}
      <span className={cn('flex items-center gap-2', loading && 'opacity-0')}>
        <Icon className="w-4 h-4" />
        <span>{loading ? loadingLabel : label}</span>
      </span>
    </motion.button>
  );
}

interface ActionButtonGroupProps {
  actions: ActionType[];
  onAction: (action: ActionType) => void;
  loadingActions?: Record<ActionType, boolean>;
  disabledActions?: Record<ActionType, boolean>;
  size?: 'sm' | 'default' | 'lg';
  className?: string;
}

export function ActionButtonGroup({
  actions,
  onAction,
  loadingActions = {},
  disabledActions = {},
  size = 'default',
  className,
}: ActionButtonGroupProps) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      {actions.map((action) => (
        <ActionButton
          key={action}
          action={action}
          onClick={() => onAction(action)}
          loading={loadingActions[action]}
          disabled={disabledActions[action]}
          size={size}
        />
      ))}
    </div>
  );
}
