// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export type AdminOperationKind = 'launch' | 'backup' | 'restore'
export type AdminOperationLiveness = 'alive' | 'stopped' | 'ambiguous'
export type AdminOperationRuntimeState = 'present' | 'absent' | 'ambiguous'
export type AdminOperationTerminalState = 'succeeded' | 'failed' | 'recovery_required'

export interface AdminOperation {
  kind: AdminOperationKind
  id: string
  state: string
  action: string | null
  owner_id: string | null
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
  reason_code: string | null
  evidence_reason_code: string | null
  recovery_required: boolean
  heartbeat_age_seconds: number | null
  liveness: AdminOperationLiveness | null
  proof_source: string | null
  runtime_state: AdminOperationRuntimeState | null
  diagnostics: Record<string, string>
  counters: Record<string, number>
}

export interface AdminOperationPagination {
  limit: number
  offset: number
  total: number
  has_more: boolean
}

export interface AdminOperationPage {
  items: AdminOperation[]
  pagination: AdminOperationPagination
}

export interface AdminOperationReconcileResult extends AdminOperation {
  previous_state: string
  applied: boolean
  terminal_state: AdminOperationTerminalState | null
}

export interface AdminOperationFilters {
  kind?: AdminOperationKind | null
  state?: string | null
  owner_id?: string | null
  age_days?: number | null
  older_than?: string | null
  recovery_required?: boolean | null
  limit?: number
  offset?: number
}

export interface AdminOperationRecoveryEvidence {
  state: string | null
  liveness: AdminOperationLiveness | null
  proof_source: string | null
  runtime_state: AdminOperationRuntimeState | null
  reason_code: string | null
  diagnostics: Record<string, string>
}
