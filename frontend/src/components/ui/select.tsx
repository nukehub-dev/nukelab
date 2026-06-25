import * as React from 'react'
import { cn } from '../../lib/utils'
import { ChevronDown, Check } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface SelectProps {
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
  placeholder?: string
  className?: string
  disabled?: boolean
  'data-testid'?: string
}

interface SelectItemProps {
  value: string
  children: React.ReactNode
  'data-testid'?: string
}

interface SelectContextType {
  value: string
  onChange: (value: string) => void
  open: boolean
  setOpen: (open: boolean) => void
}

const SelectContext = React.createContext<SelectContextType | null>(null)

function Select({
  value,
  onChange,
  children,
  placeholder,
  className,
  disabled,
  'data-testid': dataTestId,
}: SelectProps) {
  const [open, setOpen] = React.useState(false)
  const containerRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const selectedLabel = React.useMemo(() => {
    let label = placeholder || 'Select...'
    React.Children.forEach(children, (child) => {
      if (React.isValidElement<SelectItemProps>(child) && child.props.value === value) {
        label = child.props.children as string
      }
    })
    return label
  }, [children, value, placeholder])

  return (
    <SelectContext.Provider value={{ value, onChange, open, setOpen }}>
      <div ref={containerRef} data-testid={dataTestId} className={cn('relative', className)}>
        <button
          type="button"
          data-testid={dataTestId ? `${dataTestId}-trigger` : undefined}
          disabled={disabled}
          onClick={() => setOpen(!open)}
          className={cn(
            'flex h-9 w-full items-center justify-between rounded-lg border border-input bg-input/80 px-3 py-1 text-sm shadow-sm transition-colors',
            'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
            'disabled:cursor-not-allowed disabled:opacity-50 backdrop-blur-sm',
            open && 'ring-[3px] ring-ring/50',
            !value && !placeholder && 'text-muted-foreground'
          )}
        >
          <span className="truncate">{selectedLabel}</span>
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 text-muted-foreground transition-transform',
              open && 'rotate-180'
            )}
          />
        </button>
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ opacity: 0, y: -4, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -4, scale: 0.98 }}
              transition={{ duration: 0.15 }}
              className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-xl border border-border bg-popover p-1.5 shadow-lg space-y-1"
              data-testid="select-dropdown"
            >
              {children}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </SelectContext.Provider>
  )
}

function SelectItem({ value, children, 'data-testid': dataTestId }: SelectItemProps) {
  const context = React.useContext(SelectContext)
  if (!context) throw new Error('SelectItem must be used within Select')

  const { value: selectedValue, onChange, setOpen } = context
  const isSelected = selectedValue === value

  return (
    <button
      type="button"
      data-testid={dataTestId}
      onClick={() => {
        onChange(value)
        setOpen(false)
      }}
      className={cn(
        'relative flex w-full cursor-pointer select-none items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none transition-colors',
        !isSelected && 'text-foreground hover:bg-accent',
        isSelected && 'bg-primary/10 text-primary'
      )}
    >
      <Check className={cn('h-4 w-4 shrink-0', isSelected ? 'opacity-100' : 'opacity-0')} />
      <span className="flex-1 text-left whitespace-nowrap">{children}</span>
    </button>
  )
}

export { Select, SelectItem }
