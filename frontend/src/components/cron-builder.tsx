import { useState, useEffect, useMemo } from 'react';
import { cn } from '../lib/utils';
import { Clock, CalendarDays, Sunrise, Sunset, RotateCcw, Zap, ChevronRight, ChevronLeft } from 'lucide-react';

interface CronBuilderProps {
  value: string;
  onChange: (cron: string) => void;
}

const presets = [
  { label: 'Every hour', value: '0 * * * *', icon: RotateCcw, color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/20' },
  { label: 'Every 6 hours', value: '0 */6 * * *', icon: Zap, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' },
  { label: 'Daily at 9 AM', value: '0 9 * * *', icon: Sunrise, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' },
  { label: 'Daily at 6 PM', value: '0 18 * * *', icon: Sunset, color: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/20' },
  { label: 'Weekdays 9 AM', value: '0 9 * * 1-5', icon: CalendarDays, color: 'text-primary', bg: 'bg-primary/10', border: 'border-primary/20' },
  { label: 'Weekends 9 AM', value: '0 9 * * 0,6', icon: Clock, color: 'text-violet-400', bg: 'bg-violet-500/10', border: 'border-violet-500/20' },
];

const daysOfWeek = [
  { value: 0, label: 'Sun', short: 'S' },
  { value: 1, label: 'Mon', short: 'M' },
  { value: 2, label: 'Tue', short: 'T' },
  { value: 3, label: 'Wed', short: 'W' },
  { value: 4, label: 'Thu', short: 'T' },
  { value: 5, label: 'Fri', short: 'F' },
  { value: 6, label: 'Sat', short: 'S' },
];

// Generate hour positions on a 12-hour clock face (radius 32%)
const hourPositions = Array.from({ length: 12 }, (_, i) => {
  const num = i === 0 ? 12 : i;
  const angleDeg = num * 30 - 90;
  const angle = angleDeg * (Math.PI / 180);
  const r = 32;
  return { num, x: 50 + r * Math.cos(angle), y: 50 + r * Math.sin(angle) };
});

// Generate 5-minute positions on a clock face (radius 32%)
const minute5Positions = Array.from({ length: 12 }, (_, i) => {
  const num = i * 5;
  const angleDeg = num * 6 - 90;
  const angle = angleDeg * (Math.PI / 180);
  const r = 32;
  return { num, x: 50 + r * Math.cos(angle), y: 50 + r * Math.sin(angle) };
});

export function parseCron(cron: string) {
  const parts = cron.split(' ');
  if (parts.length !== 5) return { minute: 0, hour: 9, days: [1, 2, 3, 4, 5] };
  const m = parseInt(parts[0]);
  const h = parseInt(parts[1]);
  const dow = parts[4];
  let days: number[] = [];
  if (dow === '*') days = [0, 1, 2, 3, 4, 5, 6];
  else if (dow.includes('-')) {
    const [start, end] = dow.split('-').map(Number);
    for (let i = start; i <= end; i++) days.push(i);
  } else if (dow.includes(',')) days = dow.split(',').map(Number);
  else if (!isNaN(Number(dow))) days = [Number(dow)];
  return { minute: isNaN(m) ? 0 : m, hour: isNaN(h) ? 9 : h, days };
}

function buildCron(minute: number, hour: number, days: number[]) {
  const daysStr = days.length === 7 || days.length === 0 ? '*' : days.sort().join(',');
  return `${minute} ${hour} * * ${daysStr}`;
}

export function humanizeSchedule(minute: number, hour: number, days: number[]) {
  const time = `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
  if (days.length === 7) return `Every day at ${time}`;
  if (days.length === 5 && days.every((d, i) => d === i + 1)) return `Weekdays at ${time}`;
  if (days.length === 2 && days.includes(0) && days.includes(6)) return `Weekends at ${time}`;
  if (days.length === 1) return `${daysOfWeek[days[0]].label} at ${time}`;
  return `${days.map((d) => daysOfWeek[d].label).join(', ')} at ${time}`;
}

export function CronBuilder({ value, onChange }: CronBuilderProps) {
  const [mode, setMode] = useState<'preset' | 'custom'>('preset');
  const [clockMode, setClockMode] = useState<'hour' | 'minute'>('hour');
  const parsed = useMemo(() => parseCron(value), [value]);
  const [minute, setMinute] = useState(parsed.minute);
  const [hour, setHour] = useState(parsed.hour);
  const [isPM, setIsPM] = useState(parsed.hour >= 12);
  const [selectedDays, setSelectedDays] = useState<number[]>(parsed.days);

  useEffect(() => {
    setMinute(parsed.minute);
    setHour(parsed.hour);
    setIsPM(parsed.hour >= 12);
    setSelectedDays(parsed.days);
  }, [value]);

  useEffect(() => {
    if (mode === 'custom') {
      onChange(buildCron(minute, hour, selectedDays));
    }
  }, [mode, minute, hour, selectedDays, onChange]);

  const toggleDay = (day: number) => {
    setSelectedDays((prev) => {
      if (prev.includes(day)) {
        const filtered = prev.filter((d) => d !== day);
        return filtered.length === 0 ? [day] : filtered;
      }
      return [...prev, day].sort((a, b) => a - b);
    });
  };

  // 24h → 12h display
  const selectedClockHour = hour === 0 ? 12 : (hour > 12 ? hour - 12 : hour);

  // Hand rotation: 0° at 12 o'clock, clockwise
  const handRotation = clockMode === 'hour'
    ? (selectedClockHour % 12) * 30
    : minute * 6;

  const handleHourClick = (clockHour: number) => {
    let newHour: number;
    if (clockHour === 12) {
      newHour = isPM ? 12 : 0;
    } else {
      newHour = isPM ? clockHour + 12 : clockHour;
    }
    setHour(newHour);
    setClockMode('minute');
  };

  const handlePeriodChange = (pm: boolean) => {
    setIsPM(pm);
    const h12 = hour === 0 ? 12 : (hour > 12 ? hour - 12 : hour);
    if (h12 === 12) {
      setHour(pm ? 12 : 0);
    } else {
      setHour(pm ? h12 + 12 : h12);
    }
  };

  return (
    <div className="space-y-4">
      {/* Mode Toggle */}
      <div className="flex items-center gap-1 p-1 rounded-xl bg-muted/50 border border-border/50 w-fit">
        <button
          onClick={() => setMode('preset')}
          className={cn(
            "px-4 py-1.5 rounded-lg text-sm font-medium transition-all",
            mode === 'preset'
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          Presets
        </button>
        <button
          onClick={() => setMode('custom')}
          className={cn(
            "px-4 py-1.5 rounded-lg text-sm font-medium transition-all",
            mode === 'custom'
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          Custom
        </button>
      </div>

      {mode === 'preset' ? (
        <div className="grid grid-cols-2 gap-2">
          {presets.map((preset) => {
            const Icon = preset.icon;
            const active = value === preset.value;
            return (
              <button
                key={preset.value}
                onClick={() => onChange(preset.value)}
                className={cn(
                  "flex flex-col items-center gap-2 p-4 rounded-xl border text-center transition-all duration-150",
                  active
                    ? cn(preset.bg, preset.border, "border-2")
                    : "bg-surface/50 border-border/50 hover:bg-accent hover:border-border"
                )}
              >
                <div className={cn("p-2 rounded-lg", active ? preset.bg : "bg-muted")}>
                  <Icon className={cn("w-5 h-5", active ? preset.color : "text-muted-foreground")} />
                </div>
                <span className={cn("text-sm font-medium", active ? "text-foreground" : "text-muted-foreground")}>
                  {preset.label}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="space-y-5">
          {/* Digital time display */}
          <div className="text-center select-none">
            <button
              onClick={() => setClockMode('hour')}
              className={cn(
                "text-3xl font-light tabular-nums transition-colors px-1 rounded hover:bg-accent",
                clockMode === 'hour' ? "text-primary" : "text-muted-foreground"
              )}
            >
              {String(hour).padStart(2, '0')}
            </button>
            <span className="text-3xl font-light text-muted-foreground">:</span>
            <button
              onClick={() => setClockMode('minute')}
              className={cn(
                "text-3xl font-light tabular-nums transition-colors px-1 rounded hover:bg-accent",
                clockMode === 'minute' ? "text-primary" : "text-muted-foreground"
              )}
            >
              {String(minute).padStart(2, '0')}
            </button>
          </div>

          {/* Minute fine stepper */}
          {clockMode === 'minute' && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => setMinute((m) => (m - 1 + 60) % 60)}
                className="p-1.5 rounded-lg bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-xs text-muted-foreground font-medium px-2">minute</span>
              <button
                onClick={() => setMinute((m) => (m + 1) % 60)}
                className="p-1.5 rounded-lg bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Hour period toggle */}
          {clockMode === 'hour' && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => handlePeriodChange(false)}
                className={cn(
                  "px-5 py-1.5 rounded-lg text-sm font-medium transition-all",
                  !isPM ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-accent"
                )}
              >
                AM
              </button>
              <button
                onClick={() => handlePeriodChange(true)}
                className={cn(
                  "px-5 py-1.5 rounded-lg text-sm font-medium transition-all",
                  isPM ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-accent"
                )}
              >
                PM
              </button>
            </div>
          )}

          {/* Clock face */}
          <div className="relative w-64 h-64 mx-auto">
            {/* Outer circle */}
            <div className="absolute inset-0 rounded-full border-2 border-border/20 bg-surface/10" />

            {/* Tick marks — all 60 minutes */}
            {Array.from({ length: 60 }, (_, i) => {
              const isHourTick = i % 5 === 0;
              const angle = (i * 6 - 90) * (Math.PI / 180);
              const innerR = isHourTick ? 43 : 45;
              const x1 = 50 + innerR * Math.cos(angle);
              const y1 = 50 + innerR * Math.sin(angle);
              return (
                <div
                  key={i}
                  className={cn(
                    "absolute rounded-full bg-border/50",
                    isHourTick ? "w-0.5 h-2.5" : "w-px h-1.5"
                  )}
                  style={{
                    left: `${x1}%`,
                    top: `${y1}%`,
                    transform: `rotate(${i * 6}deg)`,
                    transformOrigin: 'top center',
                  }}
                />
              );
            })}

            {/* Center dot */}
            <div className="absolute left-1/2 top-1/2 w-2.5 h-2.5 bg-primary rounded-full -translate-x-1/2 -translate-y-1/2 z-20" />

            {/* Hand — ends at button center; buttons render above it via DOM order */}
            <div
              className="absolute left-1/2 top-1/2 w-0.5 bg-primary origin-bottom rounded-full transition-transform duration-200 ease-out"
              style={{
                height: '32%',
                transform: `translate(-50%, -100%) rotate(${handRotation}deg)`,
              }}
            />

            {/* Hour numbers */}
            {clockMode === 'hour' && hourPositions.map(({ num, x, y }) => {
              const isSelected = selectedClockHour === num;
              return (
                <button
                  key={num}
                  onClick={() => handleHourClick(num)}
                  className={cn(
                    "absolute w-9 h-9 flex items-center justify-center rounded-full text-sm font-semibold transition-all -translate-x-1/2 -translate-y-1/2",
                    isSelected
                      ? "bg-primary text-primary-foreground shadow-md scale-110"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                  style={{ left: `${x}%`, top: `${y}%` }}
                >
                  {num}
                </button>
              );
            })}

            {/* Minute numbers (every 5 min) */}
            {clockMode === 'minute' && minute5Positions.map(({ num, x, y }) => {
              const isSelected = minute === num;
              return (
                <button
                  key={num}
                  onClick={() => setMinute(num)}
                  className={cn(
                    "absolute w-9 h-9 flex items-center justify-center rounded-full text-xs font-semibold transition-all -translate-x-1/2 -translate-y-1/2",
                    isSelected
                      ? "bg-primary text-primary-foreground shadow-md scale-110"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                  style={{ left: `${x}%`, top: `${y}%` }}
                >
                  {String(num).padStart(2, '0')}
                </button>
              );
            })}
          </div>

          {/* Days of Week */}
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Days</label>
            <div className="flex gap-1.5">
              {daysOfWeek.map((day) => (
                <button
                  key={day.value}
                  onClick={() => toggleDay(day.value)}
                  className={cn(
                    "flex-1 py-2.5 rounded-lg text-xs font-bold transition-all",
                    selectedDays.includes(day.value)
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "bg-surface/50 text-muted-foreground hover:bg-accent hover:text-foreground border border-border/30"
                  )}
                >
                  {day.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Human-readable preview */}
      <div className="flex items-center gap-3 p-3 rounded-xl bg-primary/5 border border-primary/10">
        <Clock className="w-4 h-4 text-primary flex-shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">
            {humanizeSchedule(parseCron(value).minute, parseCron(value).hour, parseCron(value).days)}
          </p>
          <p className="text-xs text-muted-foreground font-mono mt-0.5">
            {value}
          </p>
        </div>
        <ChevronRight className="w-4 h-4 text-muted-foreground ml-auto flex-shrink-0" />
      </div>
    </div>
  );
}
