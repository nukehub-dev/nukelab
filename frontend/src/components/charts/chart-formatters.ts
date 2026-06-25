import { formatBytes } from '../../lib/utils'

export const formatters = {
  percent: (value: number) => `${value.toFixed(1)}%`,
  bytes: (value: number) => formatBytes(value),
  bytesPerSecond: (value: number) => `${formatBytes(value)}/s`,
  number: (value: number) => value.toFixed(0),
  time: (value: string) => {
    const date = new Date(value)
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  },
  date: (value: string) => {
    const date = new Date(value)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    })
  },
  dateShort: (value: string) => {
    const date = new Date(value)
    return `${date.getMonth() + 1}/${date.getDate()}`
  },
}
