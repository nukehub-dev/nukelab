import * as React from 'react'
import { cn } from '../../lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
import { modalOverlayVariants } from '../../lib/animations'
import { X } from 'lucide-react'

interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
  size?: 'default' | 'lg' | 'xl' | '2xl' | 'full'
}

const sizeClasses: Record<string, string> = {
  default: 'w-[420px]',
  lg: 'w-[560px]',
  xl: 'w-[800px]',
  '2xl': 'w-[1000px]',
  full: 'w-[90vw]',
}

function Dialog({ open, onOpenChange, children, size = 'default' }: DialogProps) {
  React.useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false)
    }
    if (open) {
      document.addEventListener('keydown', handleEscape)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [open, onOpenChange])

  const widthClass = sizeClasses[size] || sizeClasses.default

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Overlay */}
          <motion.div
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
            variants={modalOverlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={() => onOpenChange(false)}
          />
          {/* Mobile: Bottom Sheet */}
          <motion.div
            className="fixed inset-x-0 bottom-0 z-50 max-h-[90vh] rounded-t-2xl bg-card/95 backdrop-blur-xl border-t border-border/50 flex flex-col overflow-hidden lg:opacity-0 lg:pointer-events-none"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.3 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 80 || info.velocity.y > 500) {
                onOpenChange(false)
              }
            }}
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-3 pb-1 cursor-grab active:cursor-grabbing shrink-0">
              <div className="w-12 h-1.5 rounded-full bg-muted-foreground/30" />
            </div>
            {/* Content */}
            <div className="flex-1 overflow-y-auto min-h-0">{children}</div>
          </motion.div>
          {/* Desktop: Right Drawer */}
          <motion.div
            className={cn(
              'fixed inset-y-0 right-0 z-50 max-w-full bg-card/95 backdrop-blur-xl border-l border-border/50 overflow-hidden opacity-0 pointer-events-none lg:opacity-100 lg:pointer-events-auto',
              widthClass
            )}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          >
            <div className="h-full overflow-y-auto">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

const DialogContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, children, ...props }, ref) => (
    <div ref={ref} className={cn('relative p-6', className)} {...props}>
      {children}
    </div>
  )
)
DialogContent.displayName = 'DialogContent'

const DialogHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex flex-col space-y-1.5 pr-10', className)} {...props} />
  )
)
DialogHeader.displayName = 'DialogHeader'

const DialogTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h2
      ref={ref}
      className={cn('text-lg font-semibold leading-none tracking-tight', className)}
      {...props}
    />
  )
)
DialogTitle.displayName = 'DialogTitle'

const DialogDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p ref={ref} className={cn('text-sm text-muted-foreground', className)} {...props} />
))
DialogDescription.displayName = 'DialogDescription'

const DialogFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex flex-col-reverse gap-2 lg:flex-row lg:justify-end lg:gap-2 mt-6 pt-6 border-t border-border/50',
        className
      )}
      {...props}
    />
  )
)
DialogFooter.displayName = 'DialogFooter'

const DialogClose = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ className, ...props }, ref) => (
  <button
    ref={ref}
    className={cn(
      'absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100',
      'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
      'disabled:pointer-events-none',
      className
    )}
    {...props}
  >
    <X className="h-4 w-4" />
    <span className="sr-only">Close</span>
  </button>
))
DialogClose.displayName = 'DialogClose'

export {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
}
