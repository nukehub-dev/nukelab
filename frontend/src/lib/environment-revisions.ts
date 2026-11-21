// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { ApiError, api } from './api'
import { PERMISSIONS } from '../stores/auth-store'
import type {
  EnvironmentRevisionImage,
  EnvironmentRevisionPage,
  EnvironmentRevisionPortability,
  EnvironmentRevisionSummary,
  EnvironmentRevisionVolumeMode,
  RevokeEnvironmentRevisionResponse,
  VerifyEnvironmentArtifactsResponse,
} from '../types/environment-revisions'

export const REVISION_REASON_MAX_LENGTH = 255

export const ENVIRONMENT_REVISION_READ_PERMISSIONS = [
  PERMISSIONS.ENVIRONMENT_READ,
  PERMISSIONS.ADMIN_ACCESS,
] as const

export const ENVIRONMENT_REVISION_MANAGE_PERMISSIONS = [
  PERMISSIONS.ENVIRONMENT_UPDATE,
  PERMISSIONS.ADMIN_ACCESS,
] as const

export interface EnvironmentRevisionAccess {
  canRead: boolean
  canManage: boolean
}

/** Mirrors the backend split: reads need environment read, actions need update. */
export function environmentRevisionAccess(
  hasAllPermissions: (permissions: string[]) => boolean
): EnvironmentRevisionAccess {
  return {
    canRead: hasAllPermissions([...ENVIRONMENT_REVISION_READ_PERMISSIONS]),
    canManage: hasAllPermissions([...ENVIRONMENT_REVISION_MANAGE_PERMISSIONS]),
  }
}

/** Reasons are trimmed, bounded and never blank before they reach the API. */
export function normalizeRevisionReason(value: string): string {
  return value.trim()
}

export function revisionReasonValidationError(value: string): string | null {
  const reason = normalizeRevisionReason(value)
  if (!reason) return 'Enter a reason.'
  if (reason.length > REVISION_REASON_MAX_LENGTH) {
    return `Reason must be ${REVISION_REASON_MAX_LENGTH} characters or fewer.`
  }
  if (
    Array.from(reason).some((character) => {
      const code = character.codePointAt(0) ?? 0
      return code < 32 || code === 127
    })
  ) {
    return 'Reason must not contain control characters.'
  }
  return null
}

export function canSubmitRevisionAction({
  reason,
  busy,
  requiresConfirmation,
  confirmed,
}: {
  reason: string
  busy: boolean
  requiresConfirmation: boolean
  confirmed: boolean
}): boolean {
  if (busy) return false
  if (revisionReasonValidationError(reason) !== null) return false
  return !requiresConfirmation || confirmed
}

export function revisionPortabilityLabel(portability: EnvironmentRevisionPortability): string {
  return portability === 'registry_verified' ? 'Registry verified' : 'Local only'
}

export function revisionPlatform(image: EnvironmentRevisionImage | null | undefined): string {
  if (!image) return 'Platform not recorded'
  const platform = [image.os, image.architecture].filter(Boolean).join(' / ')
  if (!platform) return 'Platform not recorded'
  return image.variant ? `${platform} (${image.variant})` : platform
}

/** Only a registry-verified image can expose an approved manifest digest. */
export function revisionManifestDigest(
  image: EnvironmentRevisionImage | null | undefined
): string | null {
  if (!image?.registry_verified) return null
  return image.manifest_digest || null
}

export function revisionVolumeModeLabel(mode: EnvironmentRevisionVolumeMode): string {
  return mode === 'read_only' ? 'Read-only' : 'Read-write'
}

export function shortRevisionId(id: string): string {
  return id.slice(0, 8)
}

export function revisionLimitationLabel(limitation: string): string {
  const labels: Record<string, string> = {
    local_only_artifact: 'Artifacts are local only; portability cannot be guaranteed.',
    registry_verification_required:
      'Registry verification is required before this revision can be portable.',
    volume_configuration_local_only:
      'Template volume declarations are not portable, so this revision is local only.',
    volume_configuration_truncated: 'Only the first volume declarations are shown.',
    configuration_not_displayable: 'Configuration details could not be displayed safely.',
    runtime_reference_not_displayable: 'The runtime image reference could not be displayed.',
    toolchain_reference_not_displayable: 'The toolchain image reference could not be displayed.',
    packages_not_displayable: 'Package names could not be displayed safely.',
    packages_truncated: 'Only the first package names are shown.',
    ports_not_displayable: 'Port declarations could not be displayed safely.',
    ports_truncated: 'Only the first port declarations are shown.',
    tool_mounts_not_displayable: 'Toolchain mount paths could not be displayed safely.',
    environment_variable_names_not_displayable:
      'Environment-variable names could not be displayed safely.',
    environment_variable_names_truncated: 'Only the first environment-variable names are shown.',
    runtime_identity_not_displayable: 'Runtime identity details are unavailable.',
    toolchain_identity_not_displayable: 'Toolchain identity details are unavailable.',
  }
  return labels[limitation] ?? limitation
}

export interface EnvironmentRevisionErrorInfo {
  code: string | null
  message: string
  requiresLastRevisionConfirmation: boolean
  selectableRevisionCount: number
  replacementAvailable: boolean
}

const REVISION_ERROR_MESSAGES: Record<string, string> = {
  permission_denied: 'You do not have permission to manage environment revisions.',
  permission_revoked: 'Your permission to change this environment was revoked.',
  environment_not_found: 'The environment no longer exists. Refresh the list and try again.',
  revision_not_found: 'The revision no longer exists. Refresh the list and try again.',
  template_inactive: 'This environment is inactive. Activate it before verifying artifacts.',
  registry_auth_failed: 'The registry rejected the verification credentials.',
  registry_unreachable: 'The registry could not be reached.',
  registry_reference_invalid:
    'The template image reference is not valid for registry verification.',
  registry_configuration_invalid: 'Registry verification is misconfigured on the server.',
  runtime_unavailable: 'The container runtime is unavailable for artifact verification.',
  platform_unavailable: 'The registry has no manifest for this platform.',
  artifact_mismatch: 'The local artifact does not match the verified digest.',
  artifact_missing: 'The verified image digest is not available locally.',
  revision_unavailable: 'The current artifacts could not be resolved to a revision.',
  configuration_changed: 'The environment configuration changed. Reload and try again.',
  audit_unavailable: 'The audit entry could not be recorded, so no change was made.',
  last_revision_confirmation_required:
    'This is the last selectable revision. Confirm explicitly to revoke it.',
}

function revisionErrorCode(error: unknown): string | null {
  if (error instanceof ApiError) return error.code ?? null
  if (error && typeof error === 'object' && 'code' in error) {
    const code = (error as { code?: unknown }).code
    return typeof code === 'string' ? code : null
  }
  return null
}

function revisionErrorFallbackMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return 'The request failed. Try again.'
}

export function environmentRevisionErrorInfo(error: unknown): EnvironmentRevisionErrorInfo {
  const code = revisionErrorCode(error)
  if (code === 'last_revision_confirmation_required') {
    // The 409 contract fixes both values; never infer a selectable replacement.
    return {
      code,
      message: REVISION_ERROR_MESSAGES[code],
      requiresLastRevisionConfirmation: true,
      selectableRevisionCount: 0,
      replacementAvailable: false,
    }
  }
  return {
    code,
    message: (code && REVISION_ERROR_MESSAGES[code]) || revisionErrorFallbackMessage(error),
    requiresLastRevisionConfirmation: false,
    selectableRevisionCount: 0,
    replacementAvailable: false,
  }
}

export async function fetchEnvironmentRevisions(
  environmentId: string,
  { limit = 20, offset = 0 }: { limit?: number; offset?: number } = {}
): Promise<EnvironmentRevisionPage> {
  const search = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  return api.get<EnvironmentRevisionPage>(
    `/environments/${encodeURIComponent(environmentId)}/revisions?${search.toString()}`
  )
}

export async function verifyEnvironmentArtifacts(
  environmentId: string,
  reason: string
): Promise<VerifyEnvironmentArtifactsResponse> {
  return api.post<VerifyEnvironmentArtifactsResponse>(
    `/environments/${encodeURIComponent(environmentId)}/verify-artifacts`,
    { reason: normalizeRevisionReason(reason) }
  )
}

export function revokeEnvironmentRevision(
  revisionId: string,
  {
    reason,
    confirmLastRevision,
  }: {
    reason: string
    confirmLastRevision: boolean
  }
): Promise<RevokeEnvironmentRevisionResponse> {
  return api.post<RevokeEnvironmentRevisionResponse>(
    `/admin/environment-revisions/${encodeURIComponent(revisionId)}/revoke`,
    {
      reason: normalizeRevisionReason(reason),
      confirm_last_revision: confirmLastRevision === true,
    }
  )
}

/** True only when every loaded revision is history; callers must bound the check. */
export function hasNoSelectableRevision(
  revisions: EnvironmentRevisionSummary[],
  totalLoaded: boolean
): boolean {
  return totalLoaded && revisions.length > 0 && revisions.every((revision) => revision.revoked)
}
