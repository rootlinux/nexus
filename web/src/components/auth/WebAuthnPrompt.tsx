'use client'

import { type CSSProperties, useState } from 'react'
import type { AuthenticationResponseJSON } from '@simplewebauthn/browser'
import { KeyRound, LoaderCircle, ShieldCheck } from 'lucide-react'
import { startAuthentication } from '@simplewebauthn/browser'
import { webauthnAuthBegin } from '../../lib/api'
import { tokens } from '../../styles/tokens'

interface WebAuthnPromptProps {
  mfaSessionToken: string
  onSuccess: (credential: AuthenticationResponseJSON) => Promise<void>
  onCancel: () => void
}

const styles: Record<string, CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '24px',
    padding: '32px 0',
  },
  iconWrap: {
    width: '56px',
    height: '56px',
    borderRadius: tokens.radius.full,
    background: tokens.colors.accentMuted,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heading: {
    fontSize: tokens.font.lg,
    fontWeight: tokens.font.weightSemibold,
    color: tokens.colors.textPrimary,
    textAlign: 'center',
    margin: 0,
  },
  body: {
    fontSize: tokens.font.sm,
    color: tokens.colors.textSecondary,
    textAlign: 'center',
    margin: 0,
    lineHeight: '1.5',
  },
  helpText: {
    fontSize: tokens.font.xs,
    color: tokens.colors.textMuted,
    textAlign: 'center',
    margin: 0,
  },
  button: {
    width: '100%',
    padding: '12px 0',
    borderRadius: tokens.radius.md,
    border: 'none',
    background: tokens.colors.accent,
    color: '#000',
    fontSize: tokens.font.base,
    fontWeight: tokens.font.weightSemibold,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    transition: `background ${tokens.transition.fast}`,
  },
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  cancelButton: {
    background: 'none',
    border: 'none',
    color: tokens.colors.textSecondary,
    fontSize: tokens.font.sm,
    cursor: 'pointer',
    padding: '4px 0',
    textDecoration: 'underline',
  },
  error: {
    fontSize: tokens.font.sm,
    color: tokens.colors.danger,
    textAlign: 'center',
    margin: 0,
    padding: '10px 12px',
    background: tokens.colors.dangerSurface,
    borderRadius: tokens.radius.md,
    width: '100%',
  },
}

export function WebAuthnPrompt({ mfaSessionToken, onSuccess, onCancel }: WebAuthnPromptProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  const handleAuthenticate = async () => {
    setError('')
    setIsLoading(true)

    try {
      const options = await webauthnAuthBegin(mfaSessionToken)
      const credential = await startAuthentication({ optionsJSON: options })
      await onSuccess(credential)
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'NotAllowedError') {
        setError('Verification was cancelled or timed out.')
      } else {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(detail ?? 'Could not verify with your security key. Please try again.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.iconWrap}>
        <ShieldCheck size={28} color={tokens.colors.accent} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
        <p style={styles.heading}>Verify your sign-in</p>
        <p style={styles.body}>
          Use your security key or this device&apos;s built-in authenticator to continue.
        </p>
      </div>

      {error && <p style={styles.error}>{error}</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', width: '100%' }}>
        <button
          type="button"
          style={{ ...styles.button, ...(isLoading ? styles.buttonDisabled : {}) }}
          onClick={handleAuthenticate}
          disabled={isLoading}
        >
          {isLoading ? (
            <LoaderCircle size={18} style={{ animation: 'spin 1s linear infinite' }} />
          ) : (
            <KeyRound size={18} />
          )}
          {isLoading ? 'Waiting for verification…' : 'Verify now'}
        </button>

        <p style={styles.helpText}>
          If you no longer have access to your key, contact an admin to recover the account.
        </p>

        <button
          type="button"
          style={styles.cancelButton}
          onClick={onCancel}
          disabled={isLoading}
        >
          Cancel
        </button>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
