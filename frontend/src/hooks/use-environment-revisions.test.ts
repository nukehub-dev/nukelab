// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import { environmentRevisionKeys } from './use-environment-revisions'

describe('environment revision query keys', () => {
  it('separates environments and pagination windows', () => {
    expect(environmentRevisionKeys.list('env-one', 10, 0)).not.toEqual(
      environmentRevisionKeys.list('env-two', 10, 0)
    )
    expect(environmentRevisionKeys.list('env-one', 10, 0)).not.toEqual(
      environmentRevisionKeys.list('env-one', 10, 10)
    )
  })

  it('keeps every list under the environment invalidation prefix', () => {
    const prefix = environmentRevisionKeys.environment('env-one')
    const list = environmentRevisionKeys.list('env-one', 20, 40)
    expect(list.slice(0, prefix.length)).toEqual(prefix)
  })
})
