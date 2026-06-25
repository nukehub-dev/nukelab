import type { LucideIcon } from 'lucide-react'
import { ArrowLeft } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { cn } from '../../lib/utils'

interface PageHeaderProps {
  title: string
  subtitle?: string
  icon?: LucideIcon
  backTo?: string
  className?: string
}

export function PageHeader({ title, subtitle, icon: Icon, backTo, className }: PageHeaderProps) {
  return (
    <div
      className={cn(
        'border-b border-border/50 bg-background/80 backdrop-blur-xl sticky top-0 z-30',
        className
      )}
    >
      <div className="flex items-center gap-4 px-6 lg:px-10 py-6">
        {backTo && (
          <Link
            to={backTo}
            className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
        )}
        {Icon && (
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10">
            <Icon className="w-5 h-5 text-primary" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground mt-1 truncate">{subtitle}</p>}
        </div>
      </div>
    </div>
  )
}
