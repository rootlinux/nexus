'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { API_BASE_URL, authFetch } from '../../lib/api'
import { tokens } from '../../styles/tokens'

type StaffRole = 'super_admin' | 'admin' | 'moderator'

interface StaffPermissionState {
  role: StaffRole
  can_create_invites: boolean
  invite_quota_monthly: number | null
  can_view_moderation_queue: boolean
  can_moderate_posts: boolean
  can_manage_invites: boolean
  can_manage_users: boolean
  can_suspend_users: boolean
  can_ban_users: boolean
  can_manage_moderators: boolean
}

interface StaffAssignment {
  id: number
  user: {
    user_id: number
    username: string
    display_name: string | null
    email: string
  }
  permissions: StaffPermissionState
  updated_by_user_id: number | null
  updated_by_username: string | null
  created_at: string
  updated_at: string
  can_edit: boolean
  can_remove: boolean
}

interface StaffListResponse {
  current_actor: {
    user_id: number
    role: StaffRole
    permissions: StaffPermissionState
    manageable_roles: StaffRole[]
  }
  items: StaffAssignment[]
}

const roleLabels: Record<StaffRole, string> = {
  super_admin: 'Super Admin',
  admin: 'Admin',
  moderator: 'Moderator',
}

const permissionLabels: Array<{ key: keyof Omit<StaffPermissionState, 'role' | 'invite_quota_monthly'>; label: string }> = [
  { key: 'can_create_invites', label: 'Create invites' },
  { key: 'can_view_moderation_queue', label: 'View moderation queue' },
  { key: 'can_moderate_posts', label: 'Moderate posts' },
  { key: 'can_manage_invites', label: 'Manage invites' },
  { key: 'can_manage_users', label: 'Manage users' },
  { key: 'can_suspend_users', label: 'Suspend users' },
  { key: 'can_ban_users', label: 'Ban users' },
  { key: 'can_manage_moderators', label: 'Manage moderators' },
]

function buildRoleDefaults(role: StaffRole): StaffPermissionState {
  if (role === 'super_admin') {
    return {
      role,
      can_create_invites: true,
      invite_quota_monthly: null,
      can_view_moderation_queue: true,
      can_moderate_posts: true,
      can_manage_invites: true,
      can_manage_users: true,
      can_suspend_users: true,
      can_ban_users: true,
      can_manage_moderators: true,
    }
  }

  if (role === 'admin') {
    return {
      role,
      can_create_invites: true,
      invite_quota_monthly: null,
      can_view_moderation_queue: true,
      can_moderate_posts: true,
      can_manage_invites: true,
      can_manage_users: true,
      can_suspend_users: true,
      can_ban_users: true,
      can_manage_moderators: true,
    }
  }

  return {
    role,
    can_create_invites: false,
    invite_quota_monthly: 0,
    can_view_moderation_queue: true,
    can_moderate_posts: true,
    can_manage_invites: false,
    can_manage_users: false,
    can_suspend_users: false,
    can_ban_users: false,
    can_manage_moderators: false,
  }
}

function normalizePermissionsForRole(permissions: StaffPermissionState): StaffPermissionState {
  if (permissions.role !== 'moderator') {
    return {
      ...permissions,
      invite_quota_monthly: null,
    }
  }

  return {
    ...permissions,
    can_manage_moderators: false,
    invite_quota_monthly: permissions.can_create_invites ? permissions.invite_quota_monthly ?? 0 : 0,
  }
}

function formatDateTime(dateStr: string) {
  return new Date(dateStr).toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function readJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(url, init)
  if (!response.ok) {
    const errorData = await response.json().catch(() => null)
    throw new Error(errorData?.detail || 'Request failed')
  }
  if (response.status === 204) {
    return null as T
  }
  return response.json() as Promise<T>
}

export default function StaffManagementPanel() {
  const [data, setData] = useState<StaffListResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [isRemoving, setIsRemoving] = useState(false)

  const [createUsername, setCreateUsername] = useState('')
  const [createRole, setCreateRole] = useState<StaffRole>('moderator')
  const [createPermissions, setCreatePermissions] = useState<StaffPermissionState>(buildRoleDefaults('moderator'))

  const [editPermissions, setEditPermissions] = useState<StaffPermissionState | null>(null)

  const loadStaff = useCallback(async () => {
    setIsLoading(true)
    setError('')
    try {
      const response = await readJson<StaffListResponse>(`${API_BASE_URL}/admin/staff`)
      setData(response)
      setSelectedId((current) => current ?? response.items[0]?.id ?? null)
      setCreateRole(response.current_actor.manageable_roles[0] ?? 'moderator')
      setCreatePermissions(buildRoleDefaults(response.current_actor.manageable_roles[0] ?? 'moderator'))
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load staff assignments')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadStaff()
  }, [loadStaff])

  const selectedAssignment = useMemo(
    () => data?.items.find((item) => item.id === selectedId) ?? null,
    [data, selectedId],
  )

  useEffect(() => {
    if (!selectedAssignment) {
      setEditPermissions(null)
      return
    }
    setEditPermissions({ ...selectedAssignment.permissions })
  }, [selectedAssignment])

  const canManageStaff = Boolean(data?.current_actor.permissions.can_manage_moderators)

  const handleCreateRoleChange = (nextRole: StaffRole) => {
    setCreateRole(nextRole)
    setCreatePermissions(buildRoleDefaults(nextRole))
  }

  const handleCreatePermissionToggle = (key: keyof Omit<StaffPermissionState, 'role' | 'invite_quota_monthly'>) => {
    setCreatePermissions((current) => normalizePermissionsForRole({ ...current, [key]: !current[key] }))
  }

  const handleEditPermissionToggle = (key: keyof Omit<StaffPermissionState, 'role' | 'invite_quota_monthly'>) => {
    setEditPermissions((current) => {
      if (!current) return current
      return normalizePermissionsForRole({ ...current, [key]: !current[key] })
    })
  }

  const handleCreate = async () => {
    if (!createUsername.trim()) {
      setError('Enter a username to add a staff assignment.')
      return
    }
    if (!window.confirm(`Create ${roleLabels[createPermissions.role]} access for @${createUsername.trim()}?`)) {
      return
    }

    setIsSaving(true)
    setError('')
    setSuccessMessage('')
    try {
      await readJson<StaffAssignment>(`${API_BASE_URL}/admin/staff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: createUsername.trim(),
          role: createPermissions.role,
          permissions: createPermissions,
        }),
      })
      setCreateUsername('')
      setSuccessMessage('Staff assignment created successfully.')
      await loadStaff()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Could not create this staff assignment')
    } finally {
      setIsSaving(false)
    }
  }

  const handleSave = async () => {
    if (!selectedAssignment || !editPermissions) return
    if (!window.confirm(`Save permission changes for @${selectedAssignment.user.username}?`)) {
      return
    }

    setIsSaving(true)
    setError('')
    setSuccessMessage('')
    try {
      await readJson<StaffAssignment>(`${API_BASE_URL}/admin/staff/${selectedAssignment.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role: editPermissions.role,
          permissions: editPermissions,
          reason: `Updated by ${data?.current_actor.role || 'staff'} via admin UI`,
        }),
      })
      setSuccessMessage('Staff permissions updated successfully.')
      await loadStaff()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Could not update this staff assignment')
    } finally {
      setIsSaving(false)
    }
  }

  const handleRemove = async () => {
    if (!selectedAssignment) return
    if (!window.confirm(`Remove staff access for @${selectedAssignment.user.username}? This cannot be undone.`)) {
      return
    }

    setIsRemoving(true)
    setError('')
    setSuccessMessage('')
    try {
      await readJson(`${API_BASE_URL}/admin/staff/${selectedAssignment.id}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: `Removed by ${data?.current_actor.role || 'staff'} via admin UI`,
        }),
      })
      setSuccessMessage('Staff assignment removed successfully.')
      setSelectedId(null)
      await loadStaff()
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : 'Could not remove this staff assignment')
    } finally {
      setIsRemoving(false)
    }
  }

  if (isLoading) {
    return <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>Loading staff…</div>
  }

  if (error && !data) {
    return <div style={{ padding: '20px', color: tokens.colors.danger }}>{error}</div>
  }

  if (!data) {
    return null
  }

  return (
    <div style={{ display: 'grid', gap: '16px' }}>
      <section
        style={{
          padding: '16px',
          borderRadius: tokens.radius.lg,
          backgroundColor: tokens.colors.surface,
          border: `1px solid ${tokens.colors.border}`,
          display: 'grid',
          gap: '8px',
        }}
      >
        <h2 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: tokens.font.md }}>Moderators</h2>
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
          Staff access is backed by dedicated permissions records. Roles, flags, and moderator invite quota stay separate.
        </p>
        {successMessage ? <div style={{ color: tokens.colors.success, fontSize: tokens.font.sm }}>{successMessage}</div> : null}
        {error ? <div style={{ color: tokens.colors.danger, fontSize: tokens.font.sm }}>{error}</div> : null}
      </section>

      {canManageStaff && data.current_actor.manageable_roles.length > 0 ? (
        <section
          style={{
            padding: '16px',
            borderRadius: tokens.radius.lg,
            backgroundColor: tokens.colors.surface,
            border: `1px solid ${tokens.colors.border}`,
            display: 'grid',
            gap: '12px',
          }}
        >
          <h3 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: tokens.font.md }}>Add staff member</h3>
          <div style={{ display: 'grid', gap: '10px', gridTemplateColumns: 'minmax(180px, 1fr) minmax(180px, 220px) auto', alignItems: 'end' }}>
            <label style={{ display: 'grid', gap: '6px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
              Username
              <input
                value={createUsername}
                onChange={(event) => setCreateUsername(event.target.value)}
                placeholder="Username"
                style={{
                  padding: '10px 12px',
                  borderRadius: tokens.radius.md,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: tokens.colors.bg,
                  color: tokens.colors.textPrimary,
                }}
              />
            </label>
            <label style={{ display: 'grid', gap: '6px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
              Role
              <select
                value={createRole}
                onChange={(event) => handleCreateRoleChange(event.target.value as StaffRole)}
                style={{
                  padding: '10px 12px',
                  borderRadius: tokens.radius.md,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: tokens.colors.bg,
                  color: tokens.colors.textPrimary,
                }}
              >
                {data.current_actor.manageable_roles.map((role) => (
                  <option key={role} value={role}>
                    {roleLabels[role]}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => void handleCreate()}
              disabled={isSaving}
              style={{
                padding: '10px 16px',
                borderRadius: tokens.radius.full,
                border: `1px solid ${tokens.colors.border}`,
                backgroundColor: tokens.colors.textPrimary,
                color: tokens.colors.bg,
                cursor: isSaving ? 'default' : 'pointer',
                opacity: isSaving ? 0.6 : 1,
              }}
            >
              {isSaving ? 'Saving...' : 'Add staff'}
            </button>
          </div>
          <div style={{ display: 'grid', gap: '8px', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            {permissionLabels.map((permission) => (
              <label key={permission.key} style={{ display: 'flex', gap: '8px', alignItems: 'center', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                <input
                  type="checkbox"
                  checked={createPermissions[permission.key]}
                  onChange={() => handleCreatePermissionToggle(permission.key)}
                  disabled={permission.key === 'can_manage_moderators' && createPermissions.role === 'moderator'}
                />
                {permission.label}
              </label>
            ))}
          </div>
          {createPermissions.role === 'moderator' ? (
            <label style={{ display: 'grid', gap: '6px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm, maxWidth: '220px' }}>
              Monthly invite quota
              <input
                type="number"
                min={0}
                max={500}
                value={createPermissions.invite_quota_monthly ?? 0}
                disabled={!createPermissions.can_create_invites}
                onChange={(event) => setCreatePermissions((current) => ({ ...current, invite_quota_monthly: Number(event.target.value) }))}
                style={{
                  padding: '10px 12px',
                  borderRadius: tokens.radius.md,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: tokens.colors.bg,
                  color: tokens.colors.textPrimary,
                }}
              />
            </label>
          ) : null}
        </section>
      ) : null}

      <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: 'minmax(320px, 1.1fr) minmax(320px, 1fr)' }}>
        <section
          style={{
            borderRadius: tokens.radius.lg,
            backgroundColor: tokens.colors.surface,
            border: `1px solid ${tokens.colors.border}`,
            overflow: 'hidden',
          }}
        >
          <div style={{ padding: '14px 16px', borderBottom: `1px solid ${tokens.colors.border}`, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
            {data.items.length} staff account{data.items.length === 1 ? '' : 's'}
          </div>
          <div style={{ display: 'grid' }}>
            {data.items.map((item) => {
              const isSelected = item.id === selectedId
              return (
                <button
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  style={{
                    textAlign: 'left',
                    padding: '14px 16px',
                    border: 'none',
                    borderBottom: `1px solid ${tokens.colors.border}`,
                    backgroundColor: isSelected ? tokens.colors.surfaceElevated : tokens.colors.surface,
                    color: tokens.colors.textPrimary,
                    cursor: 'pointer',
                    display: 'grid',
                    gap: '8px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center' }}>
                    <div style={{ display: 'grid', gap: '2px' }}>
                      <strong>@{item.user.username}</strong>
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{item.user.display_name || item.user.email}</span>
                    </div>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{roleLabels[item.permissions.role]}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                    {item.permissions.can_manage_users ? <span>Users</span> : null}
                    {item.permissions.can_manage_invites ? <span>Invites</span> : null}
                    {item.permissions.can_moderate_posts ? <span>Posts</span> : null}
                    {item.permissions.can_view_moderation_queue ? <span>Queue</span> : null}
                    {item.permissions.can_create_invites && item.permissions.role === 'moderator' ? (
                      <span>Quota {item.permissions.invite_quota_monthly ?? 0}/mo</span>
                    ) : null}
                  </div>
                </button>
              )
            })}
          </div>
        </section>

        <section
          style={{
            padding: '16px',
            borderRadius: tokens.radius.lg,
            backgroundColor: tokens.colors.surface,
            border: `1px solid ${tokens.colors.border}`,
            display: 'grid',
            gap: '12px',
            alignContent: 'start',
          }}
        >
          {!selectedAssignment || !editPermissions ? (
            <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Select a staff member to review role, permissions, and quota.</div>
          ) : (
            <>
              <div style={{ display: 'grid', gap: '4px' }}>
                <h3 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: tokens.font.md }}>@{selectedAssignment.user.username}</h3>
                <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                  Last updated {formatDateTime(selectedAssignment.updated_at)}
                  {selectedAssignment.updated_by_username ? ` by @${selectedAssignment.updated_by_username}` : ''}
                </span>
              </div>

              <label style={{ display: 'grid', gap: '6px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                Role
                <select
                  value={editPermissions.role}
                  disabled={!selectedAssignment.can_edit || isSaving}
                  onChange={(event) => setEditPermissions(buildRoleDefaults(event.target.value as StaffRole))}
                  style={{
                    padding: '10px 12px',
                    borderRadius: tokens.radius.md,
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: tokens.colors.bg,
                    color: tokens.colors.textPrimary,
                  }}
                >
                  {Array.from(new Set([editPermissions.role, ...data.current_actor.manageable_roles])).map((role) => (
                    <option key={role} value={role}>
                      {roleLabels[role]}
                    </option>
                  ))}
                </select>
              </label>

              <div style={{ display: 'grid', gap: '8px', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                {permissionLabels.map((permission) => (
                  <label key={permission.key} style={{ display: 'flex', gap: '8px', alignItems: 'center', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                    <input
                      type="checkbox"
                      checked={editPermissions[permission.key]}
                      disabled={!selectedAssignment.can_edit || (permission.key === 'can_manage_moderators' && editPermissions.role === 'moderator')}
                      onChange={() => handleEditPermissionToggle(permission.key)}
                    />
                    {permission.label}
                  </label>
                ))}
              </div>

              {editPermissions.role === 'moderator' ? (
                <label style={{ display: 'grid', gap: '6px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm, maxWidth: '220px' }}>
                  Monthly invite quota
                  <input
                    type="number"
                    min={0}
                    max={500}
                    value={editPermissions.invite_quota_monthly ?? 0}
                    disabled={!selectedAssignment.can_edit || !editPermissions.can_create_invites}
                    onChange={(event) => setEditPermissions((current) => (current ? { ...current, invite_quota_monthly: Number(event.target.value) } : current))}
                    style={{
                      padding: '10px 12px',
                      borderRadius: tokens.radius.md,
                      border: `1px solid ${tokens.colors.border}`,
                      backgroundColor: tokens.colors.bg,
                      color: tokens.colors.textPrimary,
                    }}
                  />
                </label>
              ) : null}

              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                {selectedAssignment.can_edit ? (
                  <button
                    onClick={() => void handleSave()}
                    disabled={isSaving}
                    style={{
                      padding: '10px 16px',
                      borderRadius: tokens.radius.full,
                      border: `1px solid ${tokens.colors.border}`,
                      backgroundColor: tokens.colors.textPrimary,
                      color: tokens.colors.bg,
                      cursor: isSaving ? 'default' : 'pointer',
                      opacity: isSaving ? 0.6 : 1,
                    }}
                  >
                    {isSaving ? 'Saving...' : 'Save changes'}
                  </button>
                ) : null}
                {selectedAssignment.can_remove ? (
                  <button
                    onClick={() => void handleRemove()}
                    disabled={isRemoving}
                    style={{
                      padding: '10px 16px',
                      borderRadius: tokens.radius.full,
                      border: '1px solid rgba(244, 33, 46, 0.4)',
                      backgroundColor: 'rgba(244, 33, 46, 0.12)',
                      color: tokens.colors.danger,
                      cursor: isRemoving ? 'default' : 'pointer',
                      opacity: isRemoving ? 0.6 : 1,
                    }}
                  >
                    {isRemoving ? 'Removing...' : 'Remove staff'}
                  </button>
                ) : null}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
