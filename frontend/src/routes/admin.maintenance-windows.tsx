import { createFileRoute } from '@tanstack/react-router';
import {
  Wrench,
  Trash2,
  Edit3,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Clock,
  Bell,
  Calendar as CalendarIcon,
  X,
} from 'lucide-react';
import { Tooltip } from '../components/ui/tooltip';
import { useState, useRef, useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import {
  useMaintenanceWindows,
  useCreateMaintenanceWindow,
  useUpdateMaintenanceWindow,
  useDeleteMaintenanceWindow,
  type MaintenanceWindow,
} from '../hooks/use-maintenance-windows';
import {
  useSystemConfig,
  useUpdateSystemConfig,
} from '../hooks/use-system-config';
import { ResourcePageLayout } from '../components/layout/resource-page-layout';
import { DataTable } from '../components/data/data-table';
import { useDataTable } from '../hooks/use-data-table';
import { useThemeStore } from '../stores/theme-store';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Switch } from '../components/ui/switch';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '../components/ui/dialog';
import { useToast } from '../stores/toast-store';
import { usePageGuard } from '../hooks/use-page-guard';
import { PERMISSIONS } from '../stores/auth-store';
import { useConfirmDialog } from '../components/ui/confirm-dialog';
import { cn } from '../lib/utils';
import { Calendar } from '../components/ui/calendar';
import { TimePicker } from '../components/ui/time-picker';

export const Route = createFileRoute('/admin/maintenance-windows')({
  component: MaintenanceWindowsPage,
});

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function toLocalDatetimeInputValue(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => n.toString().padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalDatetimeInputValue(local: string): string {
  return new Date(local).toISOString();
}

function getWindowStatus(w: MaintenanceWindow): {
  label: string;
  color: string;
  icon: React.ElementType;
} {
  const now = new Date().toISOString();
  if (!w.is_active) return { label: 'Inactive', color: 'bg-muted text-muted-foreground', icon: XCircle };
  if (w.auto_disabled) return { label: 'Completed', color: 'bg-emerald-500/10 text-emerald-400', icon: CheckCircle2 };
  if (w.auto_enabled) return { label: 'Active', color: 'bg-rose-500/10 text-rose-400', icon: AlertCircle };
  if (w.start_at <= now && w.end_at >= now) return { label: 'In Progress', color: 'bg-rose-500/10 text-rose-400', icon: AlertCircle };
  if (w.start_at > now) {
    if (w.notified_at) return { label: 'Scheduled', color: 'bg-amber-500/10 text-amber-400', icon: Bell };
    return { label: 'Pending', color: 'bg-blue-500/10 text-blue-400', icon: Clock };
  }
  return { label: 'Expired', color: 'bg-muted text-muted-foreground', icon: XCircle };
}

function MaintenanceWindowsPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ADMIN_ACCESS });
  const density = useThemeStore((state) => state.density);
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const toast = useToast();

  const {
    state: tableState,
    setPage,
    setLimit,
    setSearch,
  } = useDataTable({ defaultLimit: 20 });

  const { data, isLoading } = useMaintenanceWindows();
  const createMutation = useCreateMaintenanceWindow();
  const updateMutation = useUpdateMaintenanceWindow();
  const deleteMutation = useDeleteMaintenanceWindow();

  const { data: sysConfig, isLoading: sysLoading } = useSystemConfig();
  const updateSysConfig = useUpdateSystemConfig();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<MaintenanceWindow | null>(null);
  const [formError, setFormError] = useState('');

  const [startDateOpen, setStartDateOpen] = useState(false);
  const [endDateOpen, setEndDateOpen] = useState(false);
  const [startTimeOpen, setStartTimeOpen] = useState(false);
  const [endTimeOpen, setEndTimeOpen] = useState(false);

  const startDateRef = useRef<HTMLButtonElement>(null);
  const startTimeRef = useRef<HTMLButtonElement>(null);
  const endDateRef = useRef<HTMLButtonElement>(null);
  const endTimeRef = useRef<HTMLButtonElement>(null);

  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [startAt, setStartAt] = useState('');
  const [endAt, setEndAt] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [notifyOffsets, setNotifyOffsets] = useState<number[]>([15]);
  const [now] = useState(() => Date.now());

  const windows = data?.windows || [];
  const total = windows.length;

  const activeCount = windows.filter((w) => {
    const s = getWindowStatus(w);
    return s.label === 'Active' || s.label === 'In Progress';
  }).length;
  const scheduledCount = windows.filter((w) => getWindowStatus(w).label === 'Scheduled').length;
  const pendingCount = windows.filter((w) => getWindowStatus(w).label === 'Pending').length;

  const resetForm = () => {
    setTitle('');
    setMessage('');
    setStartAt('');
    setEndAt('');
    setIsActive(true);
    setNotifyOffsets([15]);
    setEditing(null);
    setFormError('');
    setStartDateOpen(false);
    setEndDateOpen(false);
    setStartTimeOpen(false);
    setEndTimeOpen(false);
  };

  const openCreate = () => {
    resetForm();
    const now = new Date();
    const start = new Date(now.getTime() + 60 * 60 * 1000);
    const end = new Date(start.getTime() + 60 * 60 * 1000);
    setStartAt(toLocalDatetimeInputValue(start.toISOString()));
    setEndAt(toLocalDatetimeInputValue(end.toISOString()));
    setNotifyOffsets([15]);
    setDialogOpen(true);
  };

  const openEdit = (w: MaintenanceWindow) => {
    setEditing(w);
    setTitle(w.title);
    setMessage(w.message);
    setStartAt(toLocalDatetimeInputValue(w.start_at));
    setEndAt(toLocalDatetimeInputValue(w.end_at));
    setIsActive(w.is_active);
    setNotifyOffsets(w.notify_offsets || [15]);
    setFormError('');
    setDialogOpen(true);
  };

  const handleSubmit = async () => {
    if (!title.trim() || !message.trim() || !startAt || !endAt) {
      setFormError('Please fill in all fields');
      return;
    }
    if (new Date(startAt) >= new Date(endAt)) {
      setFormError('End time must be after start time');
      return;
    }

    const payload = {
      title: title.trim(),
      message: message.trim(),
      start_at: fromLocalDatetimeInputValue(startAt),
      end_at: fromLocalDatetimeInputValue(endAt),
      is_active: isActive,
      notify_offsets: notifyOffsets,
    };

    try {
      if (editing) {
        await updateMutation.mutateAsync({ id: editing.id, payload });
        toast.success('Maintenance window updated');
      } else {
        await createMutation.mutateAsync(payload);
        toast.success('Maintenance window scheduled');
      }
      setDialogOpen(false);
      resetForm();
    } catch (err: unknown) {
      const e = err as { message?: string };
      setFormError(e.message || 'Failed to save maintenance window');
    }
  };

  const handleToggleActive = async (w: MaintenanceWindow) => {
    try {
      await updateMutation.mutateAsync({
        id: w.id,
        payload: { is_active: !w.is_active },
      });
      toast.success(w.is_active ? 'Maintenance window deactivated' : 'Maintenance window activated');
    } catch (err: unknown) {
      const e = err as { message?: string };
      toast.error(e.message || 'Failed to update status');
    }
  };

  const handleDelete = async (w: MaintenanceWindow) => {
    const confirmed = await confirm({
      title: 'Delete Maintenance Window',
      description: `Are you sure you want to delete "${w.title}"? This cannot be undone.`,
      confirmLabel: 'Delete',
      variant: 'danger',
    });
    if (confirmed) {
      try {
        await deleteMutation.mutateAsync(w.id);
        toast.success('Maintenance window deleted');
      } catch (err: unknown) {
        const e = err as { message?: string };
        toast.error(e.message || 'Failed to delete');
      }
    }
  };

  const columns: ColumnDef<MaintenanceWindow>[] = [
    {
      accessorKey: 'title',
      header: 'Title',
      cell: ({ row }) => {
        const w = row.original;
        const status = getWindowStatus(w);
        const StatusIcon = status.icon;
        return (
          <div className="flex items-center gap-3">
            <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', status.color)}>
              <StatusIcon className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium truncate">{w.title}</p>
              <p className="text-xs text-muted-foreground truncate">{w.message}</p>
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => {
        const w = row.original;
        const status = getWindowStatus(w);
        const StatusIcon = status.icon;
        return (
          <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border', status.color)}>
            <StatusIcon className="w-3 h-3" />
            {status.label}
          </span>
        );
      },
    },
    {
      accessorKey: 'start_at',
      header: 'Start',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground whitespace-nowrap">
          {formatDateTime(row.original.start_at)}
        </span>
      ),
    },
    {
      accessorKey: 'end_at',
      header: 'End',
      cell: ({ row }) => (
        <span className="text-sm text-muted-foreground whitespace-nowrap">
          {formatDateTime(row.original.end_at)}
        </span>
      ),
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => {
        const w = row.original;
        return (
          <div className="flex items-center gap-1">
            <Tooltip content="Edit">
              <button
                onClick={() => openEdit(w)}
                className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
              >
                <Edit3 className="w-4 h-4" />
              </button>
            </Tooltip>
            <Tooltip content={w.is_active ? 'Deactivate' : 'Activate'}>
              <button
                onClick={() => handleToggleActive(w)}
                disabled={updateMutation.isPending}
                className={cn(
                  'p-1.5 rounded-lg transition-colors inline-flex disabled:opacity-50',
                  w.is_active
                    ? 'hover:bg-amber-500/10 text-amber-400'
                    : 'hover:bg-emerald-500/10 text-emerald-400'
                )}
              >
                {w.is_active ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
              </button>
            </Tooltip>
            <Tooltip content="Delete">
              <button
                onClick={() => handleDelete(w)}
                className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors inline-flex"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </Tooltip>
          </div>
        );
      },
      enableSorting: false,
    },
  ];

  const mobileCardRenderer = (w: MaintenanceWindow) => {
    const status = getWindowStatus(w);
    const StatusIcon = status.icon;
    return (
      <div className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="font-medium">{w.title}</div>
          <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border', status.color)}>
            <StatusIcon className="w-3 h-3" />
            {status.label}
          </span>
        </div>
        <div className="text-sm text-muted-foreground">{w.message}</div>
        <div className="flex flex-col gap-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            {formatDateTime(w.start_at)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5" />
            {formatDateTime(w.end_at)}
          </span>
        </div>
        <div className="flex items-center justify-end gap-1 pt-1">
          <Tooltip content="Edit">
            <button
              onClick={() => openEdit(w)}
              className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
            >
              <Edit3 className="w-4 h-4" />
            </button>
          </Tooltip>
          <Tooltip content={w.is_active ? 'Deactivate' : 'Activate'}>
            <button
              onClick={() => handleToggleActive(w)}
              disabled={updateMutation.isPending}
              className={cn(
                'p-1.5 rounded-lg transition-colors inline-flex disabled:opacity-50',
                w.is_active
                  ? 'hover:bg-amber-500/10 text-amber-400'
                  : 'hover:bg-emerald-500/10 text-emerald-400'
              )}
            >
              {w.is_active ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
            </button>
          </Tooltip>
          <Tooltip content="Delete">
            <button
              onClick={() => handleDelete(w)}
              className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive transition-colors inline-flex"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </Tooltip>
        </div>
      </div>
    );
  };

  const minutesUntilStart = useMemo(() => {
    return startAt
      ? Math.max(0, Math.floor((new Date(startAt).getTime() - now) / 60000))
      : 0;
  }, [startAt, now]);

  if (!allowed) return null;

  return (
    <>
      <ResourcePageLayout
        title="Maintenance Windows"
        subtitle="Schedule and manage platform maintenance periods"
        icon={Wrench}
        backTo="/admin"
        stats={[
          {
            title: 'Active',
            value: activeCount,
            icon: AlertCircle,
            iconColor: 'text-rose-400',
            bgColor: 'bg-rose-500/10',
          },
          {
            title: 'Scheduled',
            value: scheduledCount,
            icon: Bell,
            iconColor: 'text-amber-400',
            bgColor: 'bg-amber-500/10',
          },
          {
            title: 'Pending',
            value: pendingCount,
            icon: Clock,
            iconColor: 'text-blue-400',
            bgColor: 'bg-blue-500/10',
          },
        ]}
        actions={[
          {
            action: 'create',
            onClick: openCreate,
            loading: createMutation.isPending,
          },
        ]}
      >
        {/* Emergency Maintenance Toggle */}
        <div className="bubble p-5 space-y-4 mb-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={cn(
                'w-10 h-10 rounded-xl flex items-center justify-center',
                sysConfig?.maintenance_mode ? 'bg-amber-500/10' : 'bg-emerald-500/10'
              )}>
                <Wrench className={cn('w-5 h-5', sysConfig?.maintenance_mode ? 'text-amber-400' : 'text-emerald-400')} />
              </div>
              <div>
                <h3 className="font-semibold text-base">Emergency Maintenance</h3>
                <p className="text-xs text-muted-foreground">
                  Instantly toggle maintenance mode for all non-admin users
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {!sysLoading && sysConfig && (
                <span className={cn(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
                  sysConfig.maintenance_mode
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                    : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                )}>
                  {sysConfig.maintenance_mode ? (
                    <AlertCircle className="w-3.5 h-3.5" />
                  ) : (
                    <CheckCircle2 className="w-3.5 h-3.5" />
                  )}
                  {sysConfig.maintenance_mode ? 'Active' : 'Inactive'}
                </span>
              )}
              <Switch
                checked={sysConfig?.maintenance_mode || false}
                onCheckedChange={(checked) => {
                  updateSysConfig.mutate({
                    maintenance_mode: checked,
                    maintenance_message: sysConfig?.maintenance_message || 'System under maintenance',
                  });
                }}
                disabled={updateSysConfig.isPending || sysLoading}
              />
            </div>
          </div>

          {sysConfig?.maintenance_mode && (
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">
                Maintenance message
              </label>
              <Input
                value={sysConfig?.maintenance_message || ''}
                onChange={(e) => {
                  updateSysConfig.mutate({ maintenance_message: e.target.value });
                }}
                placeholder="System under maintenance"
                disabled={updateSysConfig.isPending}
                className="h-9"
              />
            </div>
          )}

          <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/20 p-3 rounded-xl">
            <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>
              Emergency maintenance overrides all scheduled windows. Admin users can still access the platform.
              Use scheduled windows for planned downtime — use this toggle only for unexpected issues.
            </span>
          </div>
        </div>

        <DataTable
          columns={columns}
          data={windows}
          totalCount={total}
          pageCount={Math.ceil(total / tableState.limit) || 1}
          page={tableState.page}
          limit={tableState.limit}
          isLoading={isLoading}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onGlobalFilterChange={setSearch}
          globalFilter={tableState.search}
          onSortingChange={() => {}}
          onRowSelectionChange={() => {}}
          onColumnFiltersChange={() => {}}
          onColumnVisibilityChange={() => {}}
          sorting={[]}
          rowSelection={{}}
          columnFilters={[]}
          columnVisibility={{}}
          getRowId={(row) => row.id}
          enableRowSelection={false}
          density={density}
          mobileCardRenderer={mobileCardRenderer}
          searchable
          searchPlaceholder="Search maintenance windows..."
        />
      </ResourcePageLayout>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader className="relative pr-8">
            <DialogTitle>{editing ? 'Edit Maintenance Window' : 'Schedule Maintenance'}</DialogTitle>
            <DialogDescription>
              {editing
                ? 'Update the scheduled maintenance window details.'
                : 'Plan a maintenance window. Users will be notified 15 minutes before it starts.'}
            </DialogDescription>
            <button
              onClick={() => { setDialogOpen(false); resetForm(); }}
              className="absolute right-0 top-0 p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </DialogHeader>

          <form
            className="space-y-4 mt-2"
            onSubmit={(e) => {
              e.preventDefault();
              handleSubmit();
            }}
          >
            <div className="space-y-2">
              <label className="text-sm font-medium">Title</label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Platform Upgrade v2.1"
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Message</label>
              <Textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="e.g. System will be unavailable during database migration"
                rows={3}
              />
            </div>

            {/* Start */}
            <div className="space-y-2">
              <label className="text-sm font-medium inline-flex items-center gap-1.5">
                <CalendarIcon className="w-3.5 h-3.5 text-muted-foreground" />
                Start
              </label>
              <div className="flex">
                <button
                  ref={startDateRef}
                  type="button"
                  onClick={() => { setStartDateOpen((o) => !o); setEndDateOpen(false); setStartTimeOpen(false); }}
                  className="flex-1 h-9 px-3 rounded-l-md border border-r-0 border-input bg-background text-sm text-left hover:bg-accent transition-colors inline-flex items-center gap-2"
                >
                  <CalendarIcon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  <span className={cn(!startAt && 'text-muted-foreground')}>
                    {startAt ? startAt.split('T')[0] : 'Select date'}
                  </span>
                </button>
                <button
                  ref={startTimeRef}
                  type="button"
                  onClick={() => { setStartTimeOpen((o) => !o); setEndTimeOpen(false); setStartDateOpen(false); }}
                  className="h-9 px-3 rounded-r-md border border-input bg-background text-sm hover:bg-accent transition-colors inline-flex items-center gap-1.5 w-[110px] justify-center shrink-0"
                >
                  <Clock className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  <span className={cn(!startAt && 'text-muted-foreground')}>
                    {startAt ? startAt.split('T')[1]?.slice(0, 5) || '00:00' : '00:00'}
                  </span>
                </button>
              </div>
              <Calendar
                open={startDateOpen}
                onClose={() => setStartDateOpen(false)}
                anchorRef={startDateRef}
                value={startAt ? startAt.split('T')[0] : undefined}
                onSelect={(date) => {
                  const time = startAt ? startAt.split('T')[1] || '00:00' : '00:00';
                  setStartAt(`${date}T${time}`);
                  setStartDateOpen(false);
                }}
                minDate={new Date().toISOString().split('T')[0]}
              />
              <TimePicker
                open={startTimeOpen}
                onClose={() => setStartTimeOpen(false)}
                anchorRef={startTimeRef}
                hour={startAt ? parseInt(startAt.split('T')[1]?.split(':')[0] || '0') : 0}
                minute={startAt ? parseInt(startAt.split('T')[1]?.split(':')[1] || '0') : 0}
                onChange={(h, m) => {
                  const date = startAt ? startAt.split('T')[0] : new Date().toISOString().split('T')[0];
                  setStartAt(`${date}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
                }}
              />
            </div>

            {/* End */}
            <div className="space-y-2">
              <label className="text-sm font-medium inline-flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-muted-foreground" />
                End
              </label>
              <div className="flex">
                <button
                  ref={endDateRef}
                  type="button"
                  onClick={() => { setEndDateOpen((o) => !o); setStartDateOpen(false); setEndTimeOpen(false); }}
                  className="flex-1 h-9 px-3 rounded-l-md border border-r-0 border-input bg-background text-sm text-left hover:bg-accent transition-colors inline-flex items-center gap-2"
                >
                  <CalendarIcon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  <span className={cn(!endAt && 'text-muted-foreground')}>
                    {endAt ? endAt.split('T')[0] : 'Select date'}
                  </span>
                </button>
                <button
                  ref={endTimeRef}
                  type="button"
                  onClick={() => { setEndTimeOpen((o) => !o); setStartTimeOpen(false); setEndDateOpen(false); }}
                  className="h-9 px-3 rounded-r-md border border-input bg-background text-sm hover:bg-accent transition-colors inline-flex items-center gap-1.5 w-[110px] justify-center shrink-0"
                >
                  <Clock className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  <span className={cn(!endAt && 'text-muted-foreground')}>
                    {endAt ? endAt.split('T')[1]?.slice(0, 5) || '00:00' : '00:00'}
                  </span>
                </button>
              </div>
              <Calendar
                open={endDateOpen}
                onClose={() => setEndDateOpen(false)}
                anchorRef={endDateRef}
                value={endAt ? endAt.split('T')[0] : undefined}
                onSelect={(date) => {
                  const time = endAt ? endAt.split('T')[1] || '00:00' : '00:00';
                  setEndAt(`${date}T${time}`);
                  setEndDateOpen(false);
                }}
                minDate={startAt ? startAt.split('T')[0] : new Date().toISOString().split('T')[0]}
              />
              <TimePicker
                open={endTimeOpen}
                onClose={() => setEndTimeOpen(false)}
                anchorRef={endTimeRef}
                hour={endAt ? parseInt(endAt.split('T')[1]?.split(':')[0] || '0') : 0}
                minute={endAt ? parseInt(endAt.split('T')[1]?.split(':')[1] || '0') : 0}
                onChange={(h, m) => {
                  const date = endAt ? endAt.split('T')[0] : new Date().toISOString().split('T')[0];
                  setEndAt(`${date}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
                }}
              />
            </div>

            {/* Notification Reminders */}
            <div className="space-y-2">
              <label className="text-sm font-medium inline-flex items-center gap-1.5">
                <Bell className="w-3.5 h-3.5 text-muted-foreground" />
                Notification Reminders
              </label>
              {
                (() => {
                  const impossibleOffsets = notifyOffsets.filter((o) => o >= minutesUntilStart);
                  return (
                    <>
                      <div className="flex flex-wrap gap-2">
                      {[
                        { value: 15, label: '15 min' },
                        { value: 60, label: '1 hour' },
                        { value: 1440, label: '1 day' },
                        { value: 10080, label: '7 days' },
                      ].map((opt) => {
                        const selected = notifyOffsets.includes(opt.value);
                        const disabled = minutesUntilStart > 0 && opt.value >= minutesUntilStart;
                        return (
                          <button
                            key={opt.value}
                            type="button"
                            disabled={disabled}
                            onClick={() => {
                              if (disabled) return;
                              setNotifyOffsets((prev) =>
                                selected
                                  ? prev.filter((v) => v !== opt.value)
                                  : [...prev, opt.value].sort((a, b) => b - a)
                              );
                            }}
                            className={cn(
                              'px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors',
                              disabled && 'opacity-40 cursor-not-allowed bg-muted text-muted-foreground border-border',
                              !disabled && selected && 'bg-primary text-primary-foreground border-primary',
                              !disabled && !selected && 'bg-background text-muted-foreground border-input hover:bg-accent hover:text-foreground'
                            )}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                    </div>
                    {impossibleOffsets.length > 0 && (
                      <p className="text-xs text-amber-400">
                        {impossibleOffsets.length} reminder{impossibleOffsets.length > 1 ? 's' : ''} won't fire because the maintenance window starts sooner than the reminder interval. They will be ignored.
                      </p>
                    )}
                    {impossibleOffsets.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        Users will receive a notification at each selected interval before maintenance starts.
                      </p>
                    )}
                  </>
                );
              })()}
            </div>

            {formError && (
              <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-lg">
                {formError}
              </div>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => { setDialogOpen(false); resetForm(); }}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={createMutation.isPending || updateMutation.isPending}
              >
                {editing ? 'Update Window' : 'Schedule Maintenance'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {confirmDialog}
    </>
  );
}
