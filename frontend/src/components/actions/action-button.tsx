import { cn } from '../../lib/utils';
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
      'bg-primary text-primary-foreground hover:bg-primary/90 hover:brightness-110',
      tone === 'destructive' && 'bg-destructive text-destructive-foreground hover:bg-destructive/90 hover:brightness-110',
      tone === 'success' && 'bg-emerald-500 text-white hover:bg-emerald-500/90 hover:brightness-110',
      tone === 'warning' && 'bg-amber-500 text-white hover:bg-amber-500/90 hover:brightness-110',
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
    destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90 hover:brightness-110',
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium whitespace-nowrap',
        'transition-all duration-100 hover:-translate-y-[1px] active:translate-y-[1px]',
        'disabled:pointer-events-none disabled:opacity-50',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
        'relative overflow-hidden',
        sizeClasses[size],
        variantClasses[variant],
        className
      )}
    >
      {loading && (
        <span className="absolute inset-0 flex items-center justify-center bg-inherit">
          <span className="animate-spin">
            <Icon className="w-4 h-4" />
          </span>
        </span>
      )}
      <span className={cn('flex items-center gap-2', loading && 'opacity-0')}>
        <Icon className="w-4 h-4" />
        <span>{loading ? loadingLabel : label}</span>
      </span>
    </button>
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
