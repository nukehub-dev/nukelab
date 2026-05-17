import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { cn } from '../lib/utils';
import { Tooltip } from './ui/tooltip';
import { Select, SelectItem } from './ui/select';
import {
  Terminal,
  Search,
  X,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  Copy,
  Download,
  Clock,
  ScrollText,
  ChevronDown,
  AlertTriangle,
  Square,
} from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';

interface LogViewerProps {
  logs: string;
  status?: 'running' | 'stopped' | 'error';
  tail?: number;
  isLoading?: boolean;
  onPauseChange?: (paused: boolean) => void;
}

interface LogEntry {
  raw: string;
  timestamp?: string;
  message: string;
  level: 'info' | 'warn' | 'error' | 'debug' | 'unknown';
}

function parseLogLevel(line: string): LogEntry['level'] {
  const lower = line.toLowerCase();
  if (lower.includes('error') || lower.includes('fatal') || lower.includes('panic')) return 'error';
  if (lower.includes('warn') || lower.includes('warning')) return 'warn';
  if (lower.includes('debug')) return 'debug';
  if (lower.includes('info') || lower.includes('trace')) return 'info';
  return 'unknown';
}

function parseLogs(raw: string | string[]): LogEntry[] {
  if (!raw) return [];
  const lines = Array.isArray(raw) ? raw : raw.split('\n');
  return lines.filter(Boolean).map((line) => {
    // Try to extract ISO timestamp at the start
    const tsMatch = line.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[\d\.]*(?:[+-]\d{2}:\d{2})?)\s*/);
    if (tsMatch) {
      return {
        raw: line,
        timestamp: tsMatch[1],
        message: line.slice(tsMatch[0].length),
        level: parseLogLevel(line),
      };
    }
    return { raw: line, message: line, level: parseLogLevel(line) };
  });
}

const levelConfig = {
  error: { color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20', label: 'ERR' },
  warn: { color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', label: 'WRN' },
  info: { color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/20', label: 'INF' },
  debug: { color: 'text-violet-400', bg: 'bg-violet-500/10', border: 'border-violet-500/20', label: 'DBG' },
  unknown: { color: 'text-muted-foreground', bg: 'bg-muted/30', border: 'border-border/20', label: 'LOG' },
};

export function LogViewer({ logs, status, tail = 100, isLoading, onPauseChange }: LogViewerProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [levelFilter, setLevelFilter] = useState<LogEntry['level'] | 'all'>('all');
  const [showTimestamps, setShowTimestamps] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [isPaused, setIsPaused] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [userScrolledUp, setUserScrolledUp] = useState(false);

  const entries = useMemo(() => parseLogs(logs), [logs]);

  const filtered = useMemo(() => {
    let result = entries;
    if (levelFilter !== 'all') {
      result = result.filter((e) => e.level === levelFilter);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((e) => e.raw.toLowerCase().includes(q));
    }
    return result;
  }, [entries, levelFilter, searchQuery]);

  // Auto-scroll
  useEffect(() => {
    if (!autoScroll || userScrolledUp || isPaused) return;
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [filtered, autoScroll, userScrolledUp, isPaused]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    setUserScrolledUp(!nearBottom);
  }, []);

  const togglePause = () => {
    const next = !isPaused;
    setIsPaused(next);
    onPauseChange?.(next);
  };

  const copyLogs = async () => {
    const text = filtered.map((e) => e.raw).join('\n');
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const downloadLogs = () => {
    const text = filtered.map((e) => e.raw).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `container-logs-${new Date().toISOString().slice(0, 19)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const highlightMatch = (text: string, query: string) => {
    if (!query.trim()) return text;
    const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'));
    return parts.map((part, i) =>
      part.toLowerCase() === query.toLowerCase() ? (
        <mark key={i} className="bg-primary/30 text-primary rounded px-0.5">{part}</mark>
      ) : (
        <span key={i}>{part}</span>
      )
    );
  };

  const containerClasses = isFullscreen
    ? 'fixed inset-0 z-50 bg-background flex flex-col overflow-hidden rounded-xl'
    : 'flex flex-col overflow-hidden rounded-xl';

  if (status === 'stopped') {
    return (
      <div className="p-8 rounded-lg bg-black/30 border border-border/50 text-center">
        <Square className="w-8 h-8 mx-auto mb-3 text-muted-foreground opacity-40" />
        <p className="text-sm text-muted-foreground">Server is stopped</p>
        <p className="text-xs text-muted-foreground/70 mt-1">Start the server to view container logs</p>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="p-8 rounded-lg bg-black/30 border border-border/50 text-center">
        <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-amber-400 opacity-40" />
        <p className="text-sm text-muted-foreground">Container unavailable</p>
        <p className="text-xs text-muted-foreground/70 mt-1">The container may have exited or failed to start</p>
      </div>
    );
  }

  return (
    <div className={containerClasses}>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 p-3 rounded-t-xl bg-surface/50 border border-border/50 border-b-0">
        <Terminal className="w-4 h-4 text-primary flex-shrink-0" />
        <span className="text-sm font-medium mr-2">Container Logs</span>

        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <span className="absolute left-2.5 inset-y-0 flex items-center pointer-events-none z-10">
            <Search className="w-4 h-4 text-muted-foreground" strokeWidth={2} />
          </span>
          <Input
            type="text"
            placeholder="Search logs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 h-8 text-xs"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 inset-y-0 flex items-center text-muted-foreground hover:text-foreground"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>

        {/* Level filter */}
        <Select
          value={levelFilter}
          onChange={(v) => setLevelFilter(v as LogEntry['level'] | 'all')}
          placeholder="All levels"
          className="w-28"
        >
          <SelectItem value="all">All levels</SelectItem>
          <SelectItem value="error">Error</SelectItem>
          <SelectItem value="warn">Warning</SelectItem>
          <SelectItem value="info">Info</SelectItem>
          <SelectItem value="debug">Debug</SelectItem>
        </Select>

        <div className="flex-1" />

        {/* Controls */}
        <div className="flex items-center gap-1">
          <Tooltip content={isPaused ? 'Resume' : 'Pause'} position="bottom">
            <Button
              variant="ghost"
              size="sm"
              onClick={togglePause}
              className={cn('h-8 px-2 text-xs', isPaused && 'text-amber-400')}
            >
              {isPaused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
            </Button>
          </Tooltip>

          <Tooltip content="Auto-scroll" position="bottom">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setAutoScroll((v) => !v)}
              className={cn('h-8 px-2 text-xs', autoScroll && 'text-primary')}
            >
              <ChevronDown className="w-3.5 h-3.5" />
            </Button>
          </Tooltip>

          <Tooltip content="Toggle timestamps" position="bottom">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowTimestamps((v) => !v)}
              className={cn('h-8 px-2 text-xs', showTimestamps && 'text-primary')}
            >
              <Clock className="w-3.5 h-3.5" />
            </Button>
          </Tooltip>

          <Tooltip content="Copy logs" position="bottom">
            <Button
              variant="ghost"
              size="sm"
              onClick={copyLogs}
              className="h-8 px-2 text-xs"
            >
              <Copy className="w-3.5 h-3.5" />
            </Button>
          </Tooltip>

          <Tooltip content="Download logs" position="bottom">
            <Button
              variant="ghost"
              size="sm"
              onClick={downloadLogs}
              className="h-8 px-2 text-xs"
            >
              <Download className="w-3.5 h-3.5" />
            </Button>
          </Tooltip>

          <Tooltip content={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'} position="bottom">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsFullscreen((v) => !v)}
              className="h-8 px-2 text-xs"
            >
              {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            </Button>
          </Tooltip>
        </div>
      </div>

      {/* Stats bar */}
      <div className="flex items-center gap-4 px-3 py-1.5 bg-black/20 border-x border-border/50 text-xs text-muted-foreground">
        <span>{filtered.length} lines</span>
        {searchQuery && <span>{filtered.length} matches</span>}
        {isPaused && <span className="text-amber-400 font-medium">● Paused</span>}
        {copied && <span className="text-emerald-400">Copied!</span>}
        {isLoading && <span className="animate-pulse">Updating...</span>}
      </div>

      {/* Log entries */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={cn(
          "flex-1 overflow-auto bg-black/60 border border-border/50 font-mono text-xs",
          isFullscreen ? 'max-h-none rounded-b-xl' : 'max-h-[600px] rounded-b-xl'
        )}
      >
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            <ScrollText className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No logs to display</p>
            {searchQuery && <p className="text-xs mt-1">Try adjusting your search or filters</p>}
          </div>
        ) : (
          <div className="divide-y divide-border/10">
            {filtered.map((entry, idx) => {
              const cfg = levelConfig[entry.level];
              return (
                <div
                  key={idx}
                  className={cn(
                    "flex items-start gap-2 px-3 py-1.5 hover:bg-white/5 transition-colors group",
                    entry.level === 'error' && 'bg-red-500/5',
                    entry.level === 'warn' && 'bg-amber-500/5'
                  )}
                >
                  {/* Level badge */}
                  <span
                    className={cn(
                      "flex-shrink-0 mt-0.5 px-1 py-0.5 rounded text-[10px] font-bold leading-none",
                      cfg.bg,
                      cfg.color
                    )}
                  >
                    {cfg.label}
                  </span>

                  {/* Timestamp */}
                  {showTimestamps && entry.timestamp && (
                    <span className="flex-shrink-0 text-muted-foreground/60 tabular-nums">
                      {entry.timestamp}
                    </span>
                  )}

                  {/* Message */}
                  <span className="break-all whitespace-pre-wrap text-foreground/80">
                    {searchQuery ? highlightMatch(entry.message, searchQuery) : entry.message}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

    </div>
  );
}
