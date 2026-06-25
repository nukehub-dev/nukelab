import * as React from 'react'
import { cn } from '../../lib/utils'
import { Check } from 'lucide-react'

export interface CheckboxProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  'onChange'
> {
  checked: boolean
  onChange: (checked: boolean) => void
  'data-testid'?: string
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, checked, onChange, 'data-testid': dataTestId, ...props }, ref) => {
    return (
      <label
        data-testid={dataTestId}
        className={cn('flex items-center gap-3 cursor-pointer group', className)}
      >
        <div className="relative">
          <input
            type="checkbox"
            className="peer sr-only"
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
            ref={ref}
            {...props}
          />
          <div
            className={cn(
              'h-5 w-5 rounded-md border-2 transition-all duration-150',
              'flex items-center justify-center',
              checked
                ? 'bg-primary border-primary'
                : 'border-input bg-input/50 group-hover:border-primary/50'
            )}
          >
            <Check
              className={cn(
                'h-3 w-3 text-primary-foreground transition-all duration-150',
                checked ? 'opacity-100 scale-100' : 'opacity-0 scale-75'
              )}
              strokeWidth={3}
            />
          </div>
        </div>
      </label>
    )
  }
)
Checkbox.displayName = 'Checkbox'

export { Checkbox }
