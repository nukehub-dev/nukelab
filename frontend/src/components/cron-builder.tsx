import { useState, useEffect } from 'react';
import { cn } from '../lib/utils';

interface CronBuilderProps {
  value: string;
  onChange: (cron: string) => void;
}

const presets = [
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Daily at 9 AM', value: '0 9 * * *' },
  { label: 'Daily at 6 PM', value: '0 18 * * *' },
  { label: 'Weekly (Monday 9 AM)', value: '0 9 * * 1' },
  { label: 'Weekdays at 9 AM', value: '0 9 * * 1-5' },
  { label: 'Weekends at 9 AM', value: '0 9 * * 0,6' },
];

const minutes = Array.from({ length: 60 }, (_, i) => i);
const hours = Array.from({ length: 24 }, (_, i) => i);
const daysOfWeek = [
  { value: 0, label: 'Sun' },
  { value: 1, label: 'Mon' },
  { value: 2, label: 'Tue' },
  { value: 3, label: 'Wed' },
  { value: 4, label: 'Thu' },
  { value: 5, label: 'Fri' },
  { value: 6, label: 'Sat' },
];

export function CronBuilder({ value, onChange }: CronBuilderProps) {
  const [mode, setMode] = useState<'preset' | 'custom'>('preset');
  const [minute, setMinute] = useState(0);
  const [hour, setHour] = useState(9);
  const [selectedDays, setSelectedDays] = useState<number[]>([1, 2, 3, 4, 5]);

  // Parse existing cron value
  useEffect(() => {
    const parts = value.split(' ');
    if (parts.length === 5) {
      const m = parseInt(parts[0]);
      const h = parseInt(parts[1]);
      if (!isNaN(m)) setMinute(m);
      if (!isNaN(h)) setHour(h);
      
      // Parse days
      const dow = parts[4];
      if (dow === '*') {
        setSelectedDays([0, 1, 2, 3, 4, 5, 6]);
      } else if (dow.includes('-')) {
        const [start, end] = dow.split('-').map(Number);
        const days = [];
        for (let i = start; i <= end; i++) days.push(i);
        setSelectedDays(days);
      } else if (dow.includes(',')) {
        setSelectedDays(dow.split(',').map(Number));
      } else if (!isNaN(Number(dow))) {
        setSelectedDays([Number(dow)]);
      }
    }
  }, [value]);

  // Build cron from custom selections
  useEffect(() => {
    if (mode === 'custom') {
      const daysStr = selectedDays.length === 7
        ? '*'
        : selectedDays.sort().join(',');
      const cron = `${minute} ${hour} * * ${daysStr}`;
      onChange(cron);
    }
  }, [mode, minute, hour, selectedDays, onChange]);

  const toggleDay = (day: number) => {
    setSelectedDays((prev) => {
      if (prev.includes(day)) {
        return prev.filter((d) => d !== day);
      }
      return [...prev, day].sort();
    });
  };

  return (
    <div className="space-y-3">
      {/* Mode Toggle */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setMode('preset')}
          className={cn(
            "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
            mode === 'preset'
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
          )}
        >
          Presets
        </button>
        <button
          onClick={() => setMode('custom')}
          className={cn(
            "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
            mode === 'custom'
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
          )}
        >
          Custom
        </button>
      </div>

      {mode === 'preset' ? (
        <div className="grid grid-cols-1 gap-1">
          {presets.map((preset) => (
            <button
              key={preset.value}
              onClick={() => onChange(preset.value)}
              className={cn(
                "flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors",
                value === preset.value
                  ? "bg-primary/10 text-primary border border-primary/30"
                  : "hover:bg-accent text-foreground"
              )}
            >
              <span>{preset.label}</span>
              <span className="text-xs text-muted-foreground font-mono">{preset.value}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {/* Time Selectors */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Hour</label>
              <select
                value={hour}
                onChange={(e) => setHour(Number(e.target.value))}
                className="w-full h-9 px-3 rounded-lg border border-input bg-background text-sm"
              >
                {hours.map((h) => (
                  <option key={h} value={h}>
                    {h.toString().padStart(2, '0')}:00
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Minute</label>
              <select
                value={minute}
                onChange={(e) => setMinute(Number(e.target.value))}
                className="w-full h-9 px-3 rounded-lg border border-input bg-background text-sm"
              >
                {minutes.map((m) => (
                  <option key={m} value={m}>
                    :{m.toString().padStart(2, '0')}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Days of Week */}
          <div>
            <label className="text-xs text-muted-foreground mb-2 block">Days of Week</label>
            <div className="flex gap-1">
              {daysOfWeek.map((day) => (
                <button
                  key={day.value}
                  onClick={() => toggleDay(day.value)}
                  className={cn(
                    "flex-1 py-2 rounded-lg text-xs font-medium transition-colors",
                    selectedDays.includes(day.value)
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-muted/80"
                  )}
                >
                  {day.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Preview */}
      <div className="p-2 rounded-lg bg-muted/50 border border-border/50">
        <p className="text-xs text-muted-foreground">
          Cron: <span className="font-mono text-foreground">{value}</span>
        </p>
      </div>
    </div>
  );
}
