import { useState } from 'react';
import { Calendar, Plus, Play, Square, RotateCcw, Trash2, Clock, X } from 'lucide-react';
import { cn, formatDate } from '../../lib/utils';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogClose } from '../ui/dialog';
import { Select, SelectItem } from '../ui/select';
import { Input } from '../ui/input';
import { CronBuilder, humanizeSchedule, parseCron } from '../cron-builder';
import { useServerSchedules, useCreateSchedule, useDeleteSchedule } from '../../hooks/use-servers';
import { useConfirmDialog } from '../ui/confirm-dialog';

interface ScheduleDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  serverId: string | null;
}

function actionMeta(action: string) {
  switch (action) {
    case 'start': return { icon: Play, label: 'Start', bg: 'bg-emerald-500/10', text: 'text-emerald-400', iconBg: 'bg-emerald-500/15' };
    case 'stop': return { icon: Square, label: 'Stop', bg: 'bg-amber-500/10', text: 'text-amber-400', iconBg: 'bg-amber-500/15' };
    default: return { icon: RotateCcw, label: 'Restart', bg: 'bg-primary/10', text: 'text-primary', iconBg: 'bg-primary/15' };
  }
}

export function ScheduleDialog({ open, onOpenChange, serverId }: ScheduleDialogProps) {
  const [showForm, setShowForm] = useState(false);
  const [newSchedule, setNewSchedule] = useState<{ action: 'start' | 'stop' | 'restart'; cron_expression: string; timezone: string; is_active: boolean }>(
    { action: 'start', cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true }
  );
  const { data: schedules = [] } = useServerSchedules(serverId || '');
  const createSchedule = useCreateSchedule();
  const deleteSchedule = useDeleteSchedule();
  const { confirm, dialog } = useConfirmDialog();

  if (!serverId) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogClose onClick={() => onOpenChange(false)} />
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-primary" />
            Scheduled Actions
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 mt-2">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {schedules.length} schedule{schedules.length !== 1 ? 's' : ''} configured
            </p>
            {!showForm && (
              <button
                onClick={() => setShowForm(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-all text-sm font-medium"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Schedule
              </button>
            )}
          </div>

          {showForm && (
            <div className="p-4 rounded-xl bg-surface/50 border border-border/50 space-y-3 relative">
              <button
                onClick={() => setShowForm(false)}
                className="absolute top-2 right-2 p-1 rounded hover:bg-muted text-muted-foreground transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Action</label>
                  <Select
                    value={newSchedule.action}
                    onChange={(value) => setNewSchedule({ ...newSchedule, action: value as 'start' | 'stop' | 'restart' })}
                  >
                    <SelectItem value="start">Start</SelectItem>
                    <SelectItem value="stop">Stop</SelectItem>
                    <SelectItem value="restart">Restart</SelectItem>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Timezone</label>
                  <Input
                    type="text"
                    value={newSchedule.timezone}
                    onChange={(e) => setNewSchedule({ ...newSchedule, timezone: e.target.value })}
                    placeholder="UTC"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Schedule</label>
                <CronBuilder
                  value={newSchedule.cron_expression}
                  onChange={(cron) => setNewSchedule({ ...newSchedule, cron_expression: cron })}
                />
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    createSchedule.mutate({ serverId, data: newSchedule });
                    setShowForm(false);
                    setNewSchedule({ action: 'start', cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true });
                  }}
                  className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                >
                  Create Schedule
                </button>
                <button
                  onClick={() => setShowForm(false)}
                  className="px-4 py-2 rounded-lg bg-muted text-muted-foreground text-sm font-medium hover:bg-muted/80 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {schedules.length === 0 && !showForm ? (
            <div className="text-center py-8 text-muted-foreground">
              <Calendar className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No schedules configured</p>
              <p className="text-xs mt-1">Create a schedule to automate server actions</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[400px] overflow-y-auto">
              {schedules.map((schedule) => {
                const meta = actionMeta(schedule.action);
                const ActionIcon = meta.icon;
                const parsed = parseCron(schedule.cron_expression);
                const humanCron = humanizeSchedule(parsed.minute, parsed.hour, parsed.days);
                return (
                  <div key={schedule.id} className="flex items-center gap-3 p-3 rounded-xl bg-surface/50 border border-border/50">
                    <div className={cn('p-2.5 rounded-xl flex-shrink-0', meta.iconBg)}>
                      <ActionIcon className={cn('w-4 h-4', meta.text)} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium capitalize">{meta.label}</span>
                        <span className={cn(
                          'text-xs px-2 py-0.5 rounded-full font-medium',
                          schedule.is_active ? 'bg-emerald-500/10 text-emerald-400' : 'bg-muted text-muted-foreground'
                        )}>
                          {schedule.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <Clock className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                        <span className="text-xs text-muted-foreground">{humanCron}</span>
                      </div>
                      {schedule.next_run_at && (
                        <p className="text-xs text-muted-foreground/70 mt-0.5">
                          Next: {formatDate(schedule.next_run_at)}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={async () => {
                        const confirmed = await confirm({
                          title: 'Delete Schedule',
                          description: 'Are you sure you want to delete this schedule?',
                          confirmLabel: 'Delete',
                          cancelLabel: 'Cancel',
                          variant: 'danger',
                        });
                        if (confirmed) deleteSchedule.mutate({ serverId, scheduleId: schedule.id });
                      }}
                      className="p-2 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors flex-shrink-0"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {dialog}
      </DialogContent>
    </Dialog>
  );
}
