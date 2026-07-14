// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatBytes(bytes: number | null | undefined, decimals = 2): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '0 B'
  const safeBytes = Number(bytes)
  if (safeBytes === 0 || !Number.isFinite(safeBytes)) return '0 B'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.max(0, Math.min(Math.floor(Math.log(safeBytes) / Math.log(k)), sizes.length - 1))
  return `${parseFloat((safeBytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

export function formatNumber(num: number): string {
  if (num >= 1_000_000_000) return `${(num / 1_000_000_000).toFixed(1)}B`
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`
  return num.toString()
}

export function formatPlanResource(value: string | undefined): string {
  if (!value) return '-'
  const match = value.match(/^([\d.]+)\s*([a-z]+)$/i)
  if (!match) return value

  const num = parseFloat(match[1])
  const unit = match[2].toLowerCase()

  const units: Record<string, string> = {
    b: 'B',
    k: 'KB',
    kb: 'KB',
    m: 'MB',
    mb: 'MB',
    g: 'GB',
    gb: 'GB',
    t: 'TB',
    tb: 'TB',
  }

  const prettyUnit = units[unit] || unit.toUpperCase()
  return `${num} ${prettyUnit}`
}

export function formatDuration(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${secs}s`
  return `${secs}s`
}

/** Parse a Docker-style memory/disk string (e.g. "10g", "512m") to bytes */
export function parseMemoryString(memoryStr: string): number {
  if (!memoryStr) return 0
  const str = memoryStr.toLowerCase().trim()
  const multipliers: Record<string, number> = {
    b: 1,
    k: 1024,
    m: 1024 ** 2,
    g: 1024 ** 3,
    t: 1024 ** 4,
  }
  for (const suffix of Object.keys(multipliers)) {
    if (str.endsWith(suffix)) {
      const num = parseFloat(str.slice(0, -suffix.length))
      return Math.floor(num * multipliers[suffix])
    }
  }
  return parseInt(str, 10) || 0
}

/**
 * Backend timestamps are naive UTC (ISO 8601 without Z/offset), and
 * new Date() parses offset-less date-time strings as local time.
 * Normalize naive strings to UTC before parsing; strings that already
 * carry a timezone designator (Z or ±HH:MM) and Date objects pass through.
 */
export function parseUtcDate(date: Date | string): Date {
  if (date instanceof Date) return date
  if (date.includes('T') && !date.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(date)) {
    return new Date(date + 'Z')
  }
  return new Date(date)
}

export function formatDate(date: Date | string): string {
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parseUtcDate(date))
}

export function formatRelativeTime(dateStr: string): string {
  const date = parseUtcDate(dateStr)
  const now = new Date()
  const diffMs = date.getTime() - now.getTime()
  const diffSec = Math.round(diffMs / 1000)
  const diffMin = Math.round(diffSec / 60)
  const diffHour = Math.round(diffMin / 60)
  const diffDay = Math.round(diffHour / 24)

  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

  if (Math.abs(diffDay) >= 365) {
    return formatDate(dateStr)
  }
  if (Math.abs(diffDay) >= 1) {
    return rtf.format(diffDay, 'day')
  }
  if (Math.abs(diffHour) >= 1) {
    return rtf.format(diffHour, 'hour')
  }
  if (Math.abs(diffMin) >= 1) {
    return rtf.format(diffMin, 'minute')
  }
  return rtf.format(diffSec, 'second')
}
