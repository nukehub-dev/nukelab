// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { formatBytes, parseLocalDate, parseUtcDate } from '../../lib/utils'
import { useTimezoneStore } from '../../stores/timezone-store'

export const formatters = {
  percent: (value: number) => `${value.toFixed(1)}%`,
  bytes: (value: number) => formatBytes(value),
  bytesPerSecond: (value: number) => `${formatBytes(value)}/s`,
  number: (value: number) => value.toFixed(0),
  time: (value: string) => {
    const date = parseUtcDate(value)
    return new Intl.DateTimeFormat(undefined, {
      timeZone: useTimezoneStore.getState().effectiveZone,
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date)
  },
  date: (value: string) => {
    // Day bucket (YYYY-MM-DD): local construction + local formatting keeps the
    // calendar label stable in every zone — it must not shift with the tz pref.
    const date = parseLocalDate(value)
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    })
  },
  dateShort: (value: string) => {
    const date = parseLocalDate(value)
    return `${date.getMonth() + 1}/${date.getDate()}`
  },
}
