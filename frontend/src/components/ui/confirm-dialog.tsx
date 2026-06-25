import { useState, useCallback, type ReactNode } from 'react'
import { AlertTriangle, Trash2, Ban, RefreshCw, type LucideIcon } from 'lucide-react'
import { Button } from './button'
import { Modal } from './modal'
import { cn } from '../../lib/utils'

export type ConfirmVariant = 'danger' | 'warning' | 'info' | 'destructive'

interface ConfirmOptions {
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: ConfirmVariant
  icon?: LucideIcon
  /** When set, user must type this exact string (case-insensitive) to enable confirm */
  typeToConfirm?: string
  /** Extra content rendered between description and actions */
  customContent?: ReactNode
}

interface ConfirmState extends ConfirmOptions {
  isOpen: boolean
  resolve: ((value: boolean) => void) | null
}

const variantConfig: Record<
  ConfirmVariant,
  { icon: LucideIcon; color: string; buttonVariant: 'destructive' | 'default' | 'secondary' }
> = {
  danger: { icon: Trash2, color: 'text-destructive', buttonVariant: 'destructive' },
  warning: { icon: AlertTriangle, color: 'text-amber-500', buttonVariant: 'default' },
  info: { icon: RefreshCw, color: 'text-primary', buttonVariant: 'default' },
  destructive: { icon: Ban, color: 'text-destructive', buttonVariant: 'destructive' },
}

export function useConfirmDialog() {
  const [state, setState] = useState<ConfirmState>({
    isOpen: false,
    title: '',
    description: '',
    confirmLabel: 'Confirm',
    cancelLabel: 'Cancel',
    variant: 'info',
    resolve: null,
  })
  const [typedText, setTypedText] = useState('')

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setTypedText('')
      setState({
        ...options,
        confirmLabel: options.confirmLabel ?? 'Confirm',
        cancelLabel: options.cancelLabel ?? 'Cancel',
        variant: options.variant ?? 'info',
        isOpen: true,
        resolve,
      })
    })
  }, [])

  const resolve = state.resolve

  const handleClose = useCallback(
    (value: boolean) => {
      resolve?.(value)
      setState((prev) => ({ ...prev, isOpen: false, resolve: null }))
      setTypedText('')
    },
    [resolve]
  )

  const config = variantConfig[state.variant ?? 'info']
  const Icon = state.icon ?? config.icon

  const confirmDisabled =
    !!state.typeToConfirm &&
    typedText.toLowerCase().trim() !== state.typeToConfirm.toLowerCase().trim()

  const dialog = (
    <Modal
      open={state.isOpen}
      onOpenChange={(v) => handleClose(v)}
      showClose={false}
      className={state.typeToConfirm || state.customContent ? 'max-w-lg' : 'max-w-md'}
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
            <Icon className={cn('w-5 h-5', config.color)} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-semibold">{state.title}</h3>
            {state.description && (
              <p className="text-sm text-muted-foreground mt-1">{state.description}</p>
            )}
          </div>
        </div>

        {/* Custom content */}
        {state.customContent && <div className="mt-4">{state.customContent}</div>}

        {/* Type to confirm */}
        {state.typeToConfirm && (
          <div className="mt-5 space-y-2">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Type <span className="text-foreground">{state.typeToConfirm}</span> to confirm
            </label>
            <input
              type="text"
              value={typedText}
              onChange={(e) => setTypedText(e.target.value)}
              placeholder={`Type ${state.typeToConfirm} to confirm`}
              className="w-full rounded-lg border border-border/60 bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground/50 focus:border-amber-500/60 focus:ring-1 focus:ring-amber-500/30 focus:outline-none transition-colors"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !confirmDisabled) {
                  e.preventDefault()
                  handleClose(true)
                }
              }}
              autoFocus
            />
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 mt-6 pt-4 border-t border-border/50">
          <Button
            variant="outline"
            data-testid="confirm-dialog-cancel"
            onClick={() => handleClose(false)}
            className="w-full sm:w-auto"
          >
            {state.cancelLabel}
          </Button>
          <Button
            variant={config.buttonVariant}
            data-testid="confirm-dialog-confirm"
            onClick={() => handleClose(true)}
            className="w-full sm:w-auto"
            disabled={confirmDisabled}
          >
            {state.confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )

  return { confirm, dialog }
}
