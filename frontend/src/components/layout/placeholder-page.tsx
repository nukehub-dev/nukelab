import type { LucideIcon } from 'lucide-react';
import { motion } from 'framer-motion';
import { PageHeader } from '../layout/page-header';
import { StatCard } from '../data/stat-card';
import { StatusBadge } from '../data/status-badge';
import { ActionButton } from '../actions/action-button';
import { SkeletonTable } from '../feedback/skeleton';
import { StaggerContainer, StaggerItem } from '../animations/animation-wrappers';

interface PlaceholderPageProps {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  description: string;
  stats?: Array<{
    title: string;
    value: string | number;
    icon: LucideIcon;
    iconColor?: string;
    bgColor?: string;
  }>;
  showTable?: boolean;
}

export function PlaceholderPage({
  title,
  subtitle,
  icon: Icon,
  description,
  stats,
  showTable = true,
}: PlaceholderPageProps) {
  return (
    <div className="min-h-screen">
      <PageHeader title={title} subtitle={subtitle} icon={Icon} />

      <div className="p-6 lg:p-10 space-y-8">
        {/* Stats Grid */}
        {stats && (
          <StaggerContainer className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {stats.map((stat) => (
              <StaggerItem key={stat.title}>
                <StatCard {...stat} />
              </StaggerItem>
            ))}
          </StaggerContainer>
        )}

        {/* Status + Actions Demo */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="bubble p-6"
        >
          <div className="flex items-center justify-between mb-6">
            <div className="space-y-1">
              <h2 className="text-lg font-semibold">{title}</h2>
              <p className="text-sm text-muted-foreground">{description}</p>
            </div>
            <div className="flex items-center gap-3">
              <StatusBadge status="running" pulse />
              <ActionButton action="deploy" onClick={() => {}} />
            </div>
          </div>

          {showTable && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <StatusBadge status="running" label="Active" size="sm" />
                <StatusBadge status="stopped" label="Offline" size="sm" />
                <StatusBadge status="pending" label="Provisioning" size="sm" pulse />
                <StatusBadge status="warning" label="Warning" size="sm" />
                <StatusBadge status="error" label="Failed" size="sm" />
              </div>
              <SkeletonTable rows={4} columns={4} />
            </div>
          )}
        </motion.div>

        {/* Action Buttons Demo */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="bubble p-6"
        >
          <h3 className="text-sm font-medium text-muted-foreground mb-4">Available Actions</h3>
          <div className="flex flex-wrap gap-3">
            <ActionButton action="start" onClick={() => {}} />
            <ActionButton action="stop" onClick={() => {}} />
            <ActionButton action="restart" onClick={() => {}} />
            <ActionButton action="view" onClick={() => {}} />
            <ActionButton action="logs" onClick={() => {}} />
            <ActionButton action="delete" onClick={() => {}} />
          </div>
        </motion.div>
      </div>
    </div>
  );
}
