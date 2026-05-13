import { createFileRoute, Link } from '@tanstack/react-router';
import { CreditCard, Cpu, MemoryStick, HardDrive, Search, CheckCircle2, ExternalLink, XCircle } from 'lucide-react';
import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { usePlans } from '../hooks/use-plans';
import { useAuthStore } from '../stores/auth-store';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { SkeletonCard } from '../components/feedback/skeleton';
import { EmptyState } from '../components/feedback/empty-state';
import type { Plan } from '../types/api';

export const Route = createFileRoute('/plans')({
  component: PlansCatalogPage,
});

function PlanCard({ plan, index }: { plan: Plan; index: number }) {
  const isUnavailable = !plan.is_active;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, ...springs.gentle }}
      className="h-full"
    >
      <Card
        variant="bubble"
        className={cn(
          "overflow-hidden h-full flex flex-col",
          isUnavailable && "opacity-60"
        )}
      >
        <CardContent className="p-5 flex flex-col h-full">
          {/* Header */}
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className={cn("font-semibold text-lg", isUnavailable && "text-muted-foreground")}>
                {plan.name}
              </h3>
              <code className="text-[10px] text-muted-foreground">{plan.slug}</code>
            </div>
            <div className="text-right">
              <span className={cn("text-2xl font-bold", isUnavailable ? "text-muted-foreground" : "text-primary")}>
                {plan.cost_per_hour}
              </span>
              <span className="text-xs text-muted-foreground"> NUKE/hr</span>
            </div>
          </div>

          {/* Description */}
          <p className="text-sm text-muted-foreground mb-4">
            {plan.description || <span className="italic opacity-60">No description</span>}
          </p>

          {/* Specs */}
          <div className="space-y-2 mb-4 flex-1">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5" /> CPU
              </span>
              <span className="font-medium">{plan.cpu_limit} cores</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <MemoryStick className="w-3.5 h-3.5" /> Memory
              </span>
              <span className="font-medium">{plan.memory_limit}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground flex items-center gap-1.5">
                <HardDrive className="w-3.5 h-3.5" /> Disk
              </span>
              <span className="font-medium">{plan.disk_limit}</span>
            </div>
            {plan.gpu_limit > 0 && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5" /> GPU
                </span>
                <span className="font-medium">{plan.gpu_limit}</span>
              </div>
            )}
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Max Servers</span>
              <span className="font-medium">{plan.max_servers_per_user}</span>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between pt-4 border-t border-border/30">
            {plan.is_active ? (
              <span className="text-xs flex items-center gap-1 text-emerald-400">
                <CheckCircle2 className="w-3 h-3" />
                Available
              </span>
            ) : (
              <span className="text-xs flex items-center gap-1 text-muted-foreground">
                <XCircle className="w-3 h-3" />
                Unavailable
              </span>
            )}
            {plan.is_active ? (
              <Link
                to="/servers"
                className="text-xs text-primary hover:underline flex items-center gap-1"
              >
                Create Server
                <ExternalLink className="w-3 h-3" />
              </Link>
            ) : (
              <span className="text-xs text-muted-foreground flex items-center gap-1 cursor-not-allowed">
                Create Server
                <ExternalLink className="w-3 h-3" />
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function PlansCatalogPage() {
  const canManagePlans = useAuthStore((state) => state.canManagePlans());
  const [searchQuery, setSearchQuery] = useState('');

  const { data, isLoading } = usePlans({});

  const plans = data?.data || [];
  const activePlans = plans.filter((p) => p.is_active);

  // Filter and sort: active first, then inactive
  const filteredPlans = useMemo(() => {
    let result = [...plans];

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (p) =>
          p.name.toLowerCase().includes(query) ||
          p.slug.toLowerCase().includes(query) ||
          p.description?.toLowerCase().includes(query)
      );
    }

    // Sort: active plans first
    result.sort((a, b) => {
      if (a.is_active === b.is_active) return 0;
      return a.is_active ? -1 : 1;
    });

    return result;
  }, [plans, searchQuery]);

  const statCards = isLoading ? [
    { title: 'Total Plans', value: '...', icon: CreditCard, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Available', value: '...', icon: CheckCircle2, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Avg Cost', value: '...', icon: CreditCard, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ] : [
    { title: 'Total Plans', value: plans.length, icon: CreditCard, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Available', value: activePlans.length, icon: CheckCircle2, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Avg Cost', value: plans.length > 0 ? Math.round(plans.reduce((a, p) => a + p.cost_per_hour, 0) / plans.length) : 0, icon: CreditCard, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

  return (
    <ResourcePageLayout
      title="Plans"
      subtitle="Choose a server plan that fits your needs"
      icon={CreditCard}
      stats={statCards}
    >
      {/* Toolbar: Search + Admin Link */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col sm:flex-row items-start sm:items-center gap-3"
      >
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none z-10" />
          <Input
            placeholder="Search plans..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        {canManagePlans && (
          <Link
            to="/admin/plans"
            className="inline-flex items-center justify-center rounded-lg text-sm font-medium border border-input bg-background hover:bg-accent hover:text-accent-foreground h-8 px-3 ml-auto shrink-0"
          >
            Manage Plans
          </Link>
        )}
      </motion.div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} rows={4} />
          ))}
        </div>
      ) : filteredPlans.length === 0 ? (
        <EmptyState
          icon={CreditCard}
          title="No Plans Found"
          description={searchQuery ? "No plans match your search." : "No plans are currently available."}
          action={
            searchQuery
              ? {
                  label: 'Clear Search',
                  onClick: () => setSearchQuery(''),
                }
              : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredPlans.map((plan, index) => (
            <PlanCard key={plan.id} plan={plan} index={index} />
          ))}
        </div>
      )}
    </ResourcePageLayout>
  );
}
