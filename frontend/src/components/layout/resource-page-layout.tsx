import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'
import { FloatingHeader } from './floating-header'
import type { StatCardProps } from '../data/stat-card'
import type { ActionType } from '../actions/action-config'

interface ResourcePageLayoutProps {
  title: string
  subtitle?: string
  icon?: LucideIcon
  stats?: StatCardProps[]
  actions?: Array<{
    action: ActionType
    onClick: () => void
    loading?: boolean
    disabled?: boolean
  }>
  backTo?: string
  filters?: React.ReactNode
  children: React.ReactNode
  className?: string
}

export function ResourcePageLayout({
  title,
  subtitle,
  icon,
  stats,
  actions,
  backTo,
  filters,
  children,
  className,
}: ResourcePageLayoutProps) {
  return (
    <div className={cn('min-h-screen', className)}>
      <FloatingHeader
        title={title}
        subtitle={subtitle}
        icon={icon}
        stats={stats}
        actions={actions}
        backTo={backTo}
      />

      <div className="p-6 lg:p-10 space-y-6">
        {/* Filters */}
        {filters && (
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
            {filters}
          </div>
        )}

        {/* Main Content */}
        {children}
      </div>
    </div>
  )
}
