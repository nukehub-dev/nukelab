import type { LucideIcon } from 'lucide-react';
import {
  Play,
  Square,
  RotateCcw,
  Trash2,
  Rocket,
  Eye,
  FileText,
  Pause,
  Download,
  RefreshCw,
  Plus,
} from 'lucide-react';

export type ActionVariant = 'default' | 'outline' | 'ghost' | 'destructive';
export type ActionTone = 'default' | 'primary' | 'success' | 'warning' | 'destructive';

export interface ActionConfig {
  label: string;
  icon: LucideIcon;
  variant: ActionVariant;
  tone: ActionTone;
  loadingLabel?: string;
}

export const ACTION_CONFIGS: Record<string, ActionConfig> = {
  start: {
    label: 'Start',
    icon: Play,
    variant: 'outline',
    tone: 'success',
    loadingLabel: 'Starting...',
  },
  stop: {
    label: 'Stop',
    icon: Square,
    variant: 'outline',
    tone: 'warning',
    loadingLabel: 'Stopping...',
  },
  pause: {
    label: 'Pause',
    icon: Pause,
    variant: 'outline',
    tone: 'warning',
    loadingLabel: 'Pausing...',
  },
  restart: {
    label: 'Restart',
    icon: RotateCcw,
    variant: 'outline',
    tone: 'primary',
    loadingLabel: 'Restarting...',
  },
  delete: {
    label: 'Delete',
    icon: Trash2,
    variant: 'outline',
    tone: 'destructive',
    loadingLabel: 'Deleting...',
  },
  deploy: {
    label: 'Deploy',
    icon: Rocket,
    variant: 'default',
    tone: 'primary',
    loadingLabel: 'Deploying...',
  },
  view: {
    label: 'View',
    icon: Eye,
    variant: 'ghost',
    tone: 'default',
  },
  logs: {
    label: 'Logs',
    icon: FileText,
    variant: 'ghost',
    tone: 'default',
  },
  pull: {
    label: 'Pull',
    icon: Download,
    variant: 'outline',
    tone: 'primary',
    loadingLabel: 'Pulling...',
  },
  refresh: {
    label: 'Refresh',
    icon: RefreshCw,
    variant: 'ghost',
    tone: 'default',
    loadingLabel: 'Refreshing...',
  },
  create: {
    label: 'Create',
    icon: Plus,
    variant: 'default',
    tone: 'primary',
    loadingLabel: 'Creating...',
  },
};

export type ActionType = keyof typeof ACTION_CONFIGS;

export const toneColorMap: Record<ActionTone, string> = {
  default: 'text-foreground',
  primary: 'text-primary',
  success: 'text-emerald-400',
  warning: 'text-amber-400',
  destructive: 'text-red-400',
};

export const toneBgMap: Record<ActionTone, string> = {
  default: 'bg-muted',
  primary: 'bg-primary/10',
  success: 'bg-emerald-500/10',
  warning: 'bg-amber-500/10',
  destructive: 'bg-red-500/10',
};
