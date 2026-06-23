import { createFileRoute, Link } from '@tanstack/react-router';
import { Boxes, Search, ExternalLink, Layers, GitBranch, CheckCircle2, XCircle } from 'lucide-react';
import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useEnvironments } from '../hooks/use-environments';
import { useAuthStore } from '../stores/auth-store';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { SkeletonCard } from '../components/feedback/skeleton';
import { EmptyState } from '../components/feedback/empty-state';
import type { Environment as EnvironmentType } from '../types/api';

export const Route = createFileRoute('/environments')({
  component: EnvironmentsCatalogPage,
});

const categoryColors: Record<string, string> = {
  simulation: 'bg-blue-500/10 text-blue-400',
  development: 'bg-emerald-500/10 text-emerald-400',
  ml: 'bg-violet-500/10 text-violet-400',
  data: 'bg-amber-500/10 text-amber-400',
  default: 'bg-muted text-muted-foreground',
};

function EnvironmentCard({ env, index }: { env: EnvironmentType; index: number }) {
  const categoryColor = categoryColors[env.category || ''] || categoryColors.default;
  const isInactive = !env.is_active;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, ...springs.gentle }}
    >
      <Card
        variant="bubble"
        interactive
        className={cn("overflow-hidden h-full", isInactive && "opacity-60")}
      >
        <CardContent className="p-5 flex flex-col h-full">
          {/* Header */}
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className={cn("p-2 rounded-xl shrink-0", categoryColor)}>
                <Boxes className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <h3 className={cn("font-semibold text-sm truncate", isInactive && "text-muted-foreground")}>
                  {env.name}
                </h3>
                <code className="text-[10px] text-muted-foreground">{env.slug}</code>
              </div>
            </div>
            {env.is_public && (
              <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-emerald-500/10 text-emerald-400">
                Public
              </span>
            )}
          </div>

          {/* Description */}
          <p className="text-sm text-muted-foreground line-clamp-2 mb-3 flex-1">
            {env.description || <span className="italic opacity-60">No description</span>}
          </p>

          {/* Meta */}
          <div className="flex items-center gap-2 flex-wrap mb-3">
            {env.category && (
              <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium", categoryColor)}>
                {env.category}
              </span>
            )}
            <span className="text-xs text-muted-foreground font-mono">
              {env.image}
            </span>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between pt-3 border-t border-border/30">
            {env.is_active ? (
              <span className="text-xs flex items-center gap-1 text-emerald-400">
                <CheckCircle2 className="w-3 h-3" />
                Active
              </span>
            ) : (
              <span className="text-xs flex items-center gap-1 text-muted-foreground">
                <XCircle className="w-3 h-3" />
                Inactive
              </span>
            )}
            {env.is_active ? (
              <Link
                to="/servers"
                className="text-xs text-primary hover:underline flex items-center gap-1"
              >
                Deploy
                <ExternalLink className="w-3 h-3" />
              </Link>
            ) : (
              <span className="text-xs text-muted-foreground flex items-center gap-1 cursor-not-allowed">
                Deploy
                <ExternalLink className="w-3 h-3" />
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function EnvironmentsCatalogPage() {
  const canManageEnvironments = useAuthStore((state) => state.canManageEnvironments());
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');

  const { data, isLoading } = useEnvironments({
    search: searchQuery || undefined,
  });

  const environments = useMemo(() => data?.data || [], [data?.data]);

  // Filter by category client-side, sort active first
  const filteredEnvironments = useMemo(() => {
    let result = [...environments];
    if (selectedCategory !== '') {
      result = result.filter((e) => e.category === selectedCategory);
    }
    // Sort: active environments first
    result.sort((a, b) => {
      if (a.is_active === b.is_active) return 0;
      return a.is_active ? -1 : 1;
    });
    return result;
  }, [environments, selectedCategory]);

  // Categories
  const categories = useMemo(() => {
    const cats = [...new Set(environments.map((e) => e.category).filter((c): c is string => !!c))];
    return cats;
  }, [environments]);

  const statCards = isLoading ? [
    { title: 'Total', value: '...', icon: Boxes, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: '...', icon: CheckCircle2, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Public', value: '...', icon: GitBranch, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Categories', value: '...', icon: Layers, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ] : [
    { title: 'Total', value: environments.length, icon: Boxes, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Active', value: environments.filter((e) => e.is_active).length, icon: CheckCircle2, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Public', value: environments.filter((e) => e.is_public).length, icon: GitBranch, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
    { title: 'Categories', value: categories.length, icon: Layers, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

  return (
    <ResourcePageLayout
      title="Environments"
      subtitle="Browse available deployment environments"
      icon={Boxes}
      stats={statCards}
    >
      {/* Toolbar: Search + Category Filters + Admin Link */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col sm:flex-row items-start sm:items-center gap-3"
      >
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none z-10" />
          <Input
            placeholder="Search environments..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        {categories.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <Button
              variant={selectedCategory === '' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setSelectedCategory('')}
            >
              All
            </Button>
            {categories.map((cat) => (
              <Button
                key={cat}
                variant={selectedCategory === cat ? 'default' : 'outline'}
                size="sm"
                onClick={() => setSelectedCategory(cat === selectedCategory ? '' : cat)}
              >
                {cat}
              </Button>
            ))}
          </div>
        )}
        {canManageEnvironments && (
          <Link
            to="/admin/environments"
            className="inline-flex items-center justify-center rounded-lg text-sm font-medium border border-input bg-background hover:bg-accent hover:text-accent-foreground h-8 px-3 ml-auto shrink-0"
          >
            Manage Environments
          </Link>
        )}
      </motion.div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonCard key={i} rows={3} />
          ))}
        </div>
      ) : filteredEnvironments.length === 0 ? (
        <EmptyState
          icon={Boxes}
          title="No Environments"
          description={searchQuery || selectedCategory ? "No environments match your filters." : "No environments available."}
          action={
            (searchQuery || selectedCategory)
              ? {
                  label: 'Clear Filters',
                  onClick: () => { setSearchQuery(''); setSelectedCategory(''); },
                }
              : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
          <AnimatePresence mode="popLayout">
            {filteredEnvironments.map((env, index) => (
              <EnvironmentCard key={env.id} env={env} index={index} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </ResourcePageLayout>
  );
}
