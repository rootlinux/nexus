'use client'

import { type CSSProperties, useEffect, useState } from 'react'
import type { RegistrationResponseJSON } from '@simplewebauthn/browser'
import { KeyRound, LoaderCircle, Plus, Trash2 } from 'lucide-react'
import { startRegistration } from '@simplewebauthn/browser'
import {
  deleteWebAuthnCredential,
  listWebAuthnCredentials,
  webauthnRegisterBegin,
  webauthnRegisterComplete,
} from '../../lib/api'
import { useAuth } from '../../contexts/AuthContext'
import type { WebAuthnCredential } from '../../types'
import { tokens } from '../../styles/tokens'

const styles: Record<string, CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
  sectionTitle: {
    fontSize: tokens.font.sm,
    fontWeight: tokens.font.weightSemibold,
    color: tokens.colors.textPrimary,
    margin: 0,
  },
  keyList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  keyItem: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 14px',
    background: tokens.colors.surfaceElevated,
    borderRadius: tokens.radius.md,
    border: `1px solid ${tokens.colors.border}`,
  },
  keyLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  keyName: {
    fontSize: tokens.font.sm,
    fontWeight: tokens.font.weightMedium,
    color: tokens.colors.textPrimary,
    margin: 0,
  },
  keyMeta: {
    fontSize: tokens.font.xs,
    color: tokens.colors.textSecondary,
    margin: 0,
  },
  deleteButton: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: tokens.colors.textMuted,
    display: 'flex',
    alignItems: 'center',
    padding: '4px',
    borderRadius: tokens.radius.sm,
    transition: `color ${tokens.transition.fast}`,
  },
  addSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  nameInput: {
    width: '100%',
    padding: '10px 12px',
    background: tokens.colors.surface,
    border: `1px solid ${tokens.colors.border}`,
    borderRadius: tokens.radius.md,
    color: tokens.colors.textPrimary,
    fontSize: tokens.font.sm,
    outline: 'none',
    boxSizing: 'border-box',
  },
  addButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '9px 14px',
    background: tokens.colors.surface,
    border: `1px solid ${tokens.colors.border}`,
    borderRadius: tokens.radius.md,
    color: tokens.colors.textPrimary,
    fontSize: tokens.font.sm,
    fontWeight: tokens.font.weightMedium,
    cursor: 'pointer',
    transition: `background ${tokens.transition.fast}`,
  },
  addButtonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  emptyState: {
    fontSize: tokens.font.sm,
    color: tokens.colors.textSecondary,
    margin: 0,
  },
  error: {
    fontSize: tokens.font.xs,
    color: tokens.colors.danger,
    margin: 0,
  },
  deletePrompt: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    marginTop: '12px',
    padding: '12px',
    background: tokens.colors.surface,
    border: `1px solid ${tokens.colors.border}`,
    borderRadius: tokens.radius.md,
  },
  deletePromptText: {
    fontSize: tokens.font.xs,
    color: tokens.colors.textSecondary,
    margin: 0,
  },
  deleteActions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '8px',
  },
  confirmDeleteButton: {
    padding: '8px 12px',
    borderRadius: tokens.radius.md,
    border: 'none',
    background: tokens.colors.danger,
    color: '#fff',
    fontSize: tokens.font.sm,
    fontWeight: tokens.font.weightMedium,
    cursor: 'pointer',
  },
  cancelDeleteButton: {
    padding: '8px 12px',
    borderRadius: tokens.radius.md,
    border: `1px solid ${tokens.colors.border}`,
    background: tokens.colors.surfaceElevated,
    color: tokens.colors.textPrimary,
    fontSize: tokens.font.sm,
    cursor: 'pointer',
  },
  success: {
    fontSize: tokens.font.xs,
    color: tokens.colors.success,
    margin: 0,
  },
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function WebAuthnSetup() {
  const { user } = useAuth()
  const [credentials, setCredentials] = useState<WebAuthnCredential[]>([])
  const [isLoadingList, setIsLoadingList] = useState(true)
  const [isRegistering, setIsRegistering] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [registerPassword, setRegisterPassword] = useState('')
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null)
  const [deletePassword, setDeletePassword] = useState('')
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)

  const loadCredentials = async () => {
    try {
      const list = await listWebAuthnCredentials()
      setCredentials(list)
    } catch {
      // silently ignore – not critical
    } finally {
      setIsLoadingList(false)
    }
  }

  useEffect(() => {
    void loadCredentials()
  }, [])

  const handleRegister = async () => {
    const name = newKeyName.trim()
    if (!name) {
      setError('Name this key before you continue.')
      return
    }
    if (!registerPassword) {
      setError('Enter your current password to add a security key.')
      return
    }

    setError('')
    setSuccessMsg('')
    setIsRegistering(true)

    try {
      const options = await webauthnRegisterBegin(name, registerPassword)
      const credential: RegistrationResponseJSON = await startRegistration({ optionsJSON: options })
      await webauthnRegisterComplete(credential, name)
      setNewKeyName('')
      setRegisterPassword('')
      setSuccessMsg('Security key added.')
      await loadCredentials()
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'NotAllowedError') {
        setError('Setup was cancelled.')
      } else {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(detail ?? 'Could not add this security key. Please try again.')
      }
    } finally {
      setIsRegistering(false)
    }
  }

  const handleDeleteClick = (id: number) => {
    setError('')
    setSuccessMsg('')
    setDeletingCredentialId(String(id))
    setDeletePassword('')
    setDeleteError(null)
  }

  const handleDeleteCancel = () => {
    if (deleteLoading) {
      return
    }

    setDeletingCredentialId(null)
    setDeletePassword('')
    setDeleteError(null)
  }

  const handleDeleteConfirm = async () => {
    if (!deletingCredentialId || deleteLoading) {
      return
    }

    setError('')
    setSuccessMsg('')
    setDeleteError(null)
    setDeleteLoading(true)

    try {
      await deleteWebAuthnCredential(deletingCredentialId, deletePassword)
      setDeletingCredentialId(null)
      setDeletePassword('')
      setDeleteError(null)
      await loadCredentials()
      setSuccessMsg('Security key removed.')
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setDeleteError(detail ?? 'Could not remove this security key. Please try again.')
    } finally {
      setDeleteLoading(false)
    }
  }

  return (
    <div style={styles.container}>
      <p style={styles.sectionTitle}>Security keys</p>

      {/* Key list */}
      {isLoadingList ? (
        <LoaderCircle size={16} style={{ animation: 'spin 1s linear infinite', color: tokens.colors.textSecondary }} />
      ) : credentials.length === 0 ? (
        <p style={styles.emptyState}>No security keys added yet.</p>
      ) : (
        <div style={styles.keyList}>
          {credentials.map((cred) => (
            <div key={cred.id}>
              <div style={styles.keyItem}>
                <div style={styles.keyLeft}>
                  <KeyRound size={16} color={tokens.colors.accent} />
                  <div>
                    <p style={styles.keyName}>{cred.name}</p>
                    <p style={styles.keyMeta}>
                      Added {formatDate(cred.created_at)}
                      {cred.last_used_at ? ` · Last used ${formatDate(cred.last_used_at)}` : ''}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  style={styles.deleteButton}
                  onClick={() => handleDeleteClick(cred.id)}
                  disabled={deleteLoading}
                  title="Remove key"
                >
                  {deleteLoading && deletingCredentialId === String(cred.id) ? (
                    <LoaderCircle size={16} style={{ animation: 'spin 1s linear infinite' }} />
                  ) : (
                    <Trash2 size={16} />
                  )}
                </button>
              </div>

              {deletingCredentialId === String(cred.id) && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault()
                    void handleDeleteConfirm()
                  }}
                  autoComplete="on"
                  method="post"
                  name="remove-security-key"
                  style={styles.deletePrompt}
                >
                  {user ? <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden /> : null}
                  <p style={styles.deletePromptText}>
                    Enter your current password to remove this security key.
                  </p>
                  <input
                    id={`delete-security-key-password-${cred.id}`}
                    type="password"
                    name="current-password"
                    aria-label="Current password"
                    value={deletePassword}
                    onChange={(e) => setDeletePassword(e.target.value)}
                    style={styles.nameInput}
                    placeholder="Current password"
                    autoComplete="current-password"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="done"
                    disabled={deleteLoading}
                    required
                  />
                  {deleteError && <p style={styles.error}>{deleteError}</p>}
                  <div style={styles.deleteActions}>
                    <button
                      type="button"
                      style={styles.cancelDeleteButton}
                      onClick={handleDeleteCancel}
                      disabled={deleteLoading}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      style={{
                        ...styles.confirmDeleteButton,
                        ...(deleteLoading || !deletePassword ? styles.addButtonDisabled : {}),
                      }}
                      disabled={deleteLoading || !deletePassword}
                    >
                      {deleteLoading ? 'Removing…' : 'Remove key'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Register new key */}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void handleRegister()
        }}
        autoComplete="on"
        method="post"
        name="add-security-key"
        style={styles.addSection}
      >
        {user ? <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden /> : null}
        <input
          id="newSecurityKeyName"
          type="text"
          name="security-key-name"
          aria-label="Security key name"
          placeholder="Key name, for example YubiKey 5 or Touch ID"
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          style={styles.nameInput}
          maxLength={100}
          disabled={isRegistering}
          autoCapitalize="words"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="next"
          required
        />
        <input
          id="registerSecurityKeyPassword"
          type="password"
          name="current-password"
          aria-label="Current password"
          placeholder="Current password"
          value={registerPassword}
          onChange={(e) => setRegisterPassword(e.target.value)}
          style={styles.nameInput}
          autoComplete="current-password"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="done"
          disabled={isRegistering}
          required
        />
        <button
          type="submit"
          style={{
            ...styles.addButton,
            ...(isRegistering || !newKeyName.trim() || !registerPassword ? styles.addButtonDisabled : {}),
          }}
          disabled={isRegistering || !newKeyName.trim() || !registerPassword}
        >
          {isRegistering ? (
            <LoaderCircle size={15} style={{ animation: 'spin 1s linear infinite' }} />
          ) : (
            <Plus size={15} />
          )}
          {isRegistering ? 'Adding…' : 'Add security key'}
        </button>

        {error && <p style={styles.error}>{error}</p>}
        {successMsg && <p style={styles.success}>{successMsg}</p>}
      </form>

      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
