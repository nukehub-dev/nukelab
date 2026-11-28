// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import {
  MIN_JOB_RUNTIME_SECONDS,
  argvByteLength,
  canCancelJob,
  convertJobRuntime,
  createJobIdempotencyKey,
  disabledJobCapabilities,
  formatJobCredits,
  isJobActive,
  isJobListActive,
  isJobTerminal,
  isValidJobIdempotencyKey,
  jobBillingRefund,
  jobErrorField,
  jobErrorMessage,
  jobLogStateDescription,
  jobLogStateLabel,
  jobMaximumCost,
  jobPaidBillingSummary,
  jobPollInterval,
  jobReasonCopy,
  jobRequestSignature,
  jobRuntimeDisplay,
  jobRuntimeSeconds,
  jobStateDescription,
  jobStateLabel,
  parseJobArgs,
  parseJobListSearch,
  validateJobArgv,
} from './batch-job'
import type { CreateJobRequest } from '../types/batch-job'

const limits = { max_argv_items: 4, max_input_bytes: 16 }
const request: CreateJobRequest = {
  name: 'Checksum run',
  revision_id: 'revision-1',
  plan_id: 'plan-1',
  volume_id: 'volume-1',
  argv: ['python', '/work/input.py'],
  max_runtime_seconds: 1800,
}

describe('job states', () => {
  it('labels lifecycle states and distinguishes terminal history', () => {
    expect(jobStateLabel('queued')).toBe('Queued')
    expect(jobStateLabel('recovery_required')).toBe('Needs review')
    expect(jobStateDescription('cancelling')).toContain('Resources remain held')
    expect(isJobActive('queued')).toBe(true)
    expect(isJobActive('cancelling')).toBe(true)
    expect(isJobActive('recovery_required')).toBe(true)
    expect(isJobTerminal('succeeded')).toBe(true)
    expect(isJobActive('failed')).toBe(false)
    expect(isJobTerminal('expired')).toBe(true)
  })

  it('detects any active row in a loaded page', () => {
    expect(isJobListActive([{ state: 'succeeded' }, { state: 'running' }])).toBe(true)
    expect(isJobListActive([{ state: 'cancelled' }, { state: 'expired' }])).toBe(false)
  })
})

describe('cancellation fallback', () => {
  it('trusts the server flag when supplied', () => {
    expect(canCancelJob({ state: 'queued', can_cancel: false })).toBe(false)
    expect(canCancelJob({ state: 'failed', can_cancel: true })).toBe(true)
  })

  it('derives the action only from states that can still stop', () => {
    expect(canCancelJob({ state: 'queued' })).toBe(true)
    expect(canCancelJob({ state: 'starting' })).toBe(true)
    expect(canCancelJob({ state: 'running' })).toBe(true)
    expect(canCancelJob({ state: 'cancelling' })).toBe(false)
    expect(canCancelJob({ state: 'recovery_required' })).toBe(false)
    expect(canCancelJob({ state: 'succeeded' })).toBe(false)
  })
})

describe('owner messages', () => {
  it('maps typed API codes to actionable copy and fields', () => {
    expect(jobErrorMessage('argv_too_large', 'fallback')).toContain('command is too long')
    expect(jobErrorMessage('volume_busy', 'fallback')).toContain('busy')
    expect(jobErrorMessage('unknown_code', 'fallback')).toBe('fallback')
    expect(jobErrorField('runtime_too_long')).toBe('max_runtime_seconds')
    expect(jobErrorField('paid_plan_unsupported')).toBe('plan_id')
    expect(jobErrorField('job_limit_reached')).toBeNull()
    expect(jobReasonCopy('waiting_capacity')).toContain('capacity')
    expect(jobReasonCopy(null)).toBeNull()
  })

  it('maps additional admission and lifecycle codes with owner-safe copy', () => {
    expect(jobReasonCopy('cohort_not_allowed')).toContain('pilot cohort')
    expect(jobReasonCopy('queue_expired')).toContain('expired')
    expect(jobReasonCopy('request_cancelled')).toContain('cancelled')
    expect(jobReasonCopy('cancellation_requested')).toContain('stop')
    expect(jobErrorMessage('quota_exceeded', 'fallback')).toContain('quota')
    expect(jobErrorMessage('artifact_missing', 'fallback')).toContain('image')
    expect(jobErrorMessage('permission_revoked', 'fallback')).toContain('permission')
    expect(jobErrorMessage('plan_unavailable', 'fallback')).toContain('plan')
    expect(jobErrorMessage('cohort_not_allowed', 'fallback')).toContain('pilot cohort')
    expect(jobErrorMessage('insufficient_credits', 'fallback')).toContain(
      'Not enough NUKE credits for the maximum runtime'
    )
    expect(jobErrorMessage('insufficient_credits', 'fallback')).toContain('Reduce the runtime')
    expect(jobErrorField('insufficient_credits')).toBeNull()
  })

  it('labels log states without reusing server-view copy', () => {
    expect(jobLogStateLabel('pending')).toBe('Pending')
    expect(jobLogStateLabel('truncated')).toBe('Truncated')
    expect(jobLogStateLabel('expired')).toBe('Expired')
    expect(jobLogStateDescription('expired')).toContain('retention')
  })
})

describe('literal argv parsing', () => {
  it('keeps one argument per line and does not perform shell parsing', () => {
    expect(parseJobArgs('--flag\nvalue with spaces\n\n"quoted" | pipe')).toEqual([
      '--flag',
      'value with spaces',
      '"quoted" | pipe',
    ])
    expect(parseJobArgs('one\r\ntwo\rthree')).toEqual(['one', 'two', 'three'])
  })

  it('preserves intentional leading and trailing whitespace', () => {
    expect(parseJobArgs('  padded  ')).toEqual(['  padded  '])
  })

  it('validates count, NUL characters and input size', () => {
    expect(validateJobArgv([], limits)).toContain('executable')
    expect(validateJobArgv(['one', 'two', 'three', 'four', 'five'], limits)).toContain('at most 4')
    expect(validateJobArgv(['bad\0arg'], limits)).toContain('NUL')
    expect(validateJobArgv(['012345678901234567'], limits)).toContain('input size')
    expect(validateJobArgv(['py', 'x'], limits)).toBeNull()
    expect(argvByteLength(['ab', 'c'])).toBe(5)
  })
})

describe('idempotency keys', () => {
  it('creates a visible ASCII key valid for the header contract', () => {
    const key = createJobIdempotencyKey()
    expect(isValidJobIdempotencyKey(key)).toBe(true)
    expect(key.length).toBeLessThanOrEqual(128)
    expect(isValidJobIdempotencyKey('has space')).toBe(false)
    expect(isValidJobIdempotencyKey('')).toBe(false)
  })

  it('signs material request fields deterministically', () => {
    expect(jobRequestSignature(request)).toBe(jobRequestSignature({ ...request }))
    expect(jobRequestSignature(request)).not.toBe(
      jobRequestSignature({ ...request, argv: ['python', '/work/other.py'] })
    )
    expect(jobRequestSignature(request)).not.toBe(
      jobRequestSignature({ ...request, max_runtime_seconds: 60 })
    )
  })
})

describe('runtime units', () => {
  it('converts display values to whole seconds', () => {
    expect(jobRuntimeSeconds('60', 'seconds')).toBe(60)
    expect(jobRuntimeSeconds('30', 'minutes')).toBe(1800)
    expect(jobRuntimeSeconds('2', 'hours')).toBe(7200)
    expect(jobRuntimeSeconds('0.5', 'hours')).toBe(1800)
    expect(jobRuntimeSeconds('0.5', 'minutes')).toBe(30)
    expect(jobRuntimeSeconds('', 'minutes')).toBeNaN()
    expect(jobRuntimeSeconds('0', 'minutes')).toBeNaN()
  })

  it('chooses the largest whole display unit', () => {
    expect(jobRuntimeDisplay(1800)).toEqual({ value: '30', unit: 'minutes' })
    expect(jobRuntimeDisplay(7200)).toEqual({ value: '2', unit: 'hours' })
    expect(jobRuntimeDisplay(90)).toEqual({ value: '90', unit: 'seconds' })
  })

  it('preserves the duration across unit changes', () => {
    expect(convertJobRuntime('30', 'minutes', 'hours')).toBe('0.5')
    expect(convertJobRuntime('2', 'hours', 'minutes')).toBe('120')
    expect(convertJobRuntime('90', 'seconds', 'minutes')).toBe('1.5')
    expect(convertJobRuntime('bad', 'minutes', 'seconds')).toBe('bad')
  })

  it('exposes the one-minute backend minimum', () => {
    expect(MIN_JOB_RUNTIME_SECONDS).toBe(60)
  })
})

describe('paging, polling and cost', () => {
  it('retains only validated list filters', () => {
    expect(parseJobListSearch({ state: 'active' })).toEqual({ state: 'active' })
    expect(parseJobListSearch({ state: 'history' })).toEqual({ state: 'history' })
    expect(parseJobListSearch({ state: 'deleted' })).toEqual({})
    expect(parseJobListSearch({ state: ['active'] })).toEqual({})
  })

  it('polls active work with bounded backoff and pauses hidden tabs', () => {
    expect(jobPollInterval(true, 0, false)).toBe(5000)
    expect(jobPollInterval(true, 2, false)).toBe(20000)
    expect(jobPollInterval(true, 100, false)).toBe(60000)
    expect(jobPollInterval(true, 1, true)).toBe(false)
    expect(jobPollInterval(false, 0, false)).toBe(false)
  })

  it('rounds the paid hold up to whole NUKE credits with a one-credit minimum', () => {
    expect(jobMaximumCost(2, 1800, 'zero_cost')).toBe(0)
    expect(jobMaximumCost(2, 1800, 'paid')).toBe(1)
    expect(jobMaximumCost(2, 3600, 'paid')).toBe(2)
    expect(jobMaximumCost(2, 3601, 'paid')).toBe(3)
    expect(jobMaximumCost(10, 900, 'paid')).toBe(3)
    expect(jobMaximumCost(10, 60, 'paid')).toBe(1)
    expect(jobMaximumCost(3600, 1, 'paid')).toBe(1)
    expect(jobMaximumCost(0, 3600, 'paid')).toBe(0)
    expect(jobMaximumCost(2, 0, 'paid')).toBe(0)
  })

  it('formats paid billing states from the server snapshot', () => {
    const billing = {
      mode: 'paid' as const,
      charged: 4,
      authorized: 5,
      rate_per_hour: 10,
      state: 'settled' as const,
      unpaid: 0,
    }
    expect(jobPaidBillingSummary({ ...billing, state: 'held', charged: 0 })).toBe('5 NUKE held')
    expect(jobPaidBillingSummary(billing)).toBe('4 NUKE charged, 1 NUKE refunded')
    expect(jobPaidBillingSummary({ ...billing, charged: 5 })).toBe(
      '5 NUKE charged, 0 NUKE refunded'
    )
    expect(jobPaidBillingSummary({ ...billing, charged: 0, state: 'released' })).toBe(
      '0 NUKE charged; hold released'
    )
    expect(jobPaidBillingSummary({ ...billing, charged: 0, state: 'none' })).toBe('0 NUKE charged')
    expect(jobPaidBillingSummary({ ...billing, charged: 4, unpaid: 1 })).toBe(
      '4 NUKE charged, 1 NUKE unpaid'
    )
    expect(jobBillingRefund(billing)).toBe(1)
    expect(jobBillingRefund({ ...billing, charged: 4, unpaid: 1 })).toBe(0)
    expect(formatJobCredits(1234)).toBe((1234).toLocaleString(undefined))
  })

  it('provides disabled capabilities with complete limits', () => {
    const capabilities = disabledJobCapabilities()
    expect(capabilities.enabled).toBe(false)
    expect(capabilities.can_submit).toBe(false)
    expect(capabilities.limits.max_runtime_seconds).toBe(7200)
  })
})
