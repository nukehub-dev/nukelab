import { motion } from 'framer-motion';
import { ArrowRight, Minus, Plus } from 'lucide-react';
import { cn } from '../../lib/utils';

interface AuditLogDiffProps {
  beforeState: Record<string, unknown>;
  afterState: Record<string, unknown>;
}

interface DiffItem {
  key: string;
  before: unknown;
  after: unknown;
  type: 'added' | 'removed' | 'changed' | 'unchanged';
}

function computeDiff(
  before: Record<string, unknown>,
  after: Record<string, unknown>
): DiffItem[] {
  const keys = new Set([
    ...Object.keys(before || {}),
    ...Object.keys(after || {}),
  ]);

  const items: DiffItem[] = [];

  for (const key of keys) {
    const hasBefore = Object.prototype.hasOwnProperty.call(before || {}, key);
    const hasAfter = Object.prototype.hasOwnProperty.call(after || {}, key);

    if (!hasBefore && hasAfter) {
      items.push({ key, before: undefined, after: after[key], type: 'added' });
    } else if (hasBefore && !hasAfter) {
      items.push({ key, before: before[key], after: undefined, type: 'removed' });
    } else {
      const beforeVal = before[key];
      const afterVal = after[key];
      const changed = JSON.stringify(beforeVal) !== JSON.stringify(afterVal);
      items.push({
        key,
        before: beforeVal,
        after: afterVal,
        type: changed ? 'changed' : 'unchanged',
      });
    }
  }

  return items.sort((a, b) => {
    if (a.type === 'changed' && b.type !== 'changed') return -1;
    if (b.type === 'changed' && a.type !== 'changed') return 1;
    if (a.type === 'added' && b.type === 'removed') return -1;
    if (a.type === 'removed' && b.type === 'added') return 1;
    return a.key.localeCompare(b.key);
  });
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value || '""';
  if (Array.isArray(value)) return `[${value.length} items]`;
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function getTypeColor(type: DiffItem['type']): { bg: string; text: string; icon: typeof Plus } {
  switch (type) {
    case 'added':
      return { bg: 'bg-emerald-500/10', text: 'text-emerald-400', icon: Plus };
    case 'removed':
      return { bg: 'bg-red-500/10', text: 'text-red-400', icon: Minus };
    case 'changed':
      return { bg: 'bg-amber-500/10', text: 'text-amber-400', icon: ArrowRight };
    default:
      return { bg: 'bg-muted/30', text: 'text-muted-foreground', icon: ArrowRight };
  }
}

export function AuditLogDiff({ beforeState, afterState }: AuditLogDiffProps) {
  const hasBefore = Object.keys(beforeState || {}).length > 0;
  const hasAfter = Object.keys(afterState || {}).length > 0;

  if (!hasBefore && !hasAfter) {
    return (
      <p className="text-sm text-muted-foreground italic">No state captured</p>
    );
  }

  const diff = computeDiff(beforeState || {}, afterState || {});

  return (
    <div className="space-y-1">
      {diff.map((item, index) => {
        const { bg, text, icon: Icon } = getTypeColor(item.type);
        const isMultiline =
          (typeof item.before === 'object' && item.before !== null) ||
          (typeof item.after === 'object' && item.after !== null);

        return (
          <motion.div
            key={item.key}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            className={cn(
              'rounded-lg p-2.5 text-sm',
              bg,
              item.type === 'unchanged' && 'opacity-60'
            )}
          >
            <div className="flex items-center gap-2 mb-1.5">
              <Icon className={cn('w-3.5 h-3.5', text)} />
              <span className={cn('font-mono text-xs font-medium', text)}>
                {item.key}
              </span>
              <span className="ml-auto text-[10px] uppercase tracking-wider opacity-70">
                {item.type}
              </span>
            </div>

            {isMultiline ? (
              <div className="grid grid-cols-2 gap-2">
                {item.type !== 'added' && (
                  <pre className="text-xs text-muted-foreground bg-black/20 rounded p-2 overflow-auto max-h-40">
                    {formatValue(item.before)}
                  </pre>
                )}
                {item.type !== 'removed' && (
                  <pre className="text-xs text-foreground bg-black/20 rounded p-2 overflow-auto max-h-40">
                    {formatValue(item.after)}
                  </pre>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2">
                {item.type !== 'added' && (
                  <span className="text-muted-foreground line-through">
                    {formatValue(item.before)}
                  </span>
                )}
                {item.type === 'changed' && (
                  <ArrowRight className="w-3 h-3 text-amber-400 shrink-0" />
                )}
                {item.type !== 'removed' && (
                  <span className="font-medium">{formatValue(item.after)}</span>
                )}
              </div>
            )}
          </motion.div>
        );
      })}
    </div>
  );
}
