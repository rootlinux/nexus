'use client'

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from 'react'

import { submitFeedbackReport } from '../../lib/api'
import { tokens } from '../../styles/tokens'
import type { User } from '../../types'

type ReportProblemModalProps = {
  isOpen: boolean
  onClose: () => void
  user: User | null
}

type FormState = {
  title: string
  description: string
  currentPath: string
  username: string
  deviceInfo: string
  contactEmail: string
}

const MAX_ATTACHMENT_SIZE_BYTES = 5 * 1024 * 1024
const ALLOWED_ATTACHMENT_TYPES = ['image/png', 'image/jpeg', 'image/webp']

function formatAttachmentSize(sizeBytes: number) {
  if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`
  }
  if (sizeBytes >= 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`
  }
  return `${sizeBytes} bytes`
}

function getErrorMessage(error: unknown, fallback: string) {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: unknown }).response === 'object'
  ) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response
    if (typeof response?.data?.detail === 'string') {
      return response.data.detail
    }
  }
  return fallback
}

function detectStandaloneMode() {
  if (typeof window === 'undefined') {
    return null
  }

  const nav = navigator as Navigator & { standalone?: boolean }
  if (typeof nav.standalone === 'boolean') {
    return nav.standalone
  }

  return window.matchMedia('(display-mode: standalone)').matches
}

function buildDeviceInfo() {
  if (typeof navigator === 'undefined') {
    return ''
  }

  const standalone = detectStandaloneMode()
  const parts = [navigator.userAgent]
  if (standalone === true) {
    parts.push('standalone PWA')
  } else if (standalone === false) {
    parts.push('browser tab')
  }
  return parts.join(' • ')
}

function clampText(value: string | undefined, maxLength: number) {
  if (!value) {
    return undefined
  }

  const trimmed = value.trim()
  if (!trimmed) {
    return undefined
  }

  return trimmed.slice(0, maxLength)
}

export function ReportProblemModal({ isOpen, onClose, user }: ReportProblemModalProps) {
  const attachmentInputRef = useRef<HTMLInputElement | null>(null)
  const [form, setForm] = useState<FormState>({
    title: '',
    description: '',
    currentPath: '',
    username: user?.username ?? '',
    deviceInfo: '',
    contactEmail: user?.email ?? '',
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [attachment, setAttachment] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (!isOpen) {
      return
    }

    const nextPath = typeof window !== 'undefined' ? `${window.location.pathname}${window.location.search}${window.location.hash}` : ''
    setForm({
      title: '',
      description: '',
      currentPath: nextPath,
      username: user?.username ?? '',
      deviceInfo: buildDeviceInfo(),
      contactEmail: user?.email ?? '',
    })
    setAttachment(null)
    setError('')
    setSuccess('')
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = ''
    }
  }, [isOpen, user?.email, user?.username])

  useEffect(() => {
    if (!isOpen) {
      return
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSubmitting) {
        onClose()
      }
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, isSubmitting, onClose])

  if (!isOpen) {
    return null
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setIsSubmitting(true)
    setError('')
    setSuccess('')

    try {
      const currentUrl = typeof window !== 'undefined' ? window.location.origin + window.location.pathname : ''
      const response = await submitFeedbackReport({
        title: form.title.trim(),
        description: form.description.trim(),
        current_path: clampText(form.currentPath, 300),
        username: clampText(form.username, 64),
        device_info: clampText(form.deviceInfo, 500),
        contact_email: clampText(form.contactEmail, 255),
        current_url: clampText(currentUrl, 500),
        user_agent: clampText(typeof navigator !== 'undefined' ? navigator.userAgent : undefined, 500),
        standalone_mode: detectStandaloneMode() ?? undefined,
        occurred_at: clampText(new Date().toISOString(), 64),
        app_version: clampText(process.env.NEXT_PUBLIC_APP_VERSION ?? process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA, 120),
      }, attachment)
      setSuccess(response.message)
    } catch (submitError) {
      setError(getErrorMessage(submitError, 'Couldn’t send your report right now.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  const clearAttachment = () => {
    setAttachment(null)
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = ''
    }
  }

  const handleAttachmentChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null
    if (!nextFile) {
      clearAttachment()
      return
    }

    if (!ALLOWED_ATTACHMENT_TYPES.includes(nextFile.type)) {
      clearAttachment()
      setError('Attach a PNG, JPEG, or WebP image.')
      return
    }

    if (nextFile.size > MAX_ATTACHMENT_SIZE_BYTES) {
      clearAttachment()
      setError('Attachment must be 5 MB or smaller.')
      return
    }

    setAttachment(nextFile)
    setError('')
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="reportProblemTitle"
      onClick={() => {
        if (!isSubmitting) {
          onClose()
        }
      }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
        backgroundColor: 'rgba(15, 11, 8, 0.72)',
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        style={{
          width: '100%',
          maxWidth: '520px',
          borderRadius: '24px',
          border: `1px solid ${tokens.colors.border}`,
          backgroundColor: tokens.colors.bg,
          padding: '24px',
          display: 'grid',
          gap: '16px',
          boxShadow: '0 28px 72px rgba(0, 0, 0, 0.38)',
        }}
      >
        <div style={{ display: 'grid', gap: '6px' }}>
          <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.1em', color: tokens.colors.textSecondary }}>
            Report a problem
          </div>
          <h2 id="reportProblemTitle" style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '24px', lineHeight: 1.15 }}>
            Found something off?
          </h2>
          <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '14px', lineHeight: 1.6 }}>
            Send the details.
          </p>
        </div>

        {success ? (
          <div style={{ display: 'grid', gap: '14px' }}>
            <div style={{ padding: '12px 14px', borderRadius: '12px', border: `1px solid ${tokens.colors.success}`, color: tokens.colors.success, backgroundColor: 'rgba(0, 186, 124, 0.08)', fontSize: '13px' }}>
              {success}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  border: 'none',
                  borderRadius: '999px',
                  padding: '11px 18px',
                  backgroundColor: tokens.colors.accent,
                  color: tokens.colors.bg,
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '13px',
                }}
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: 'grid', gap: '12px' }}>
            <label htmlFor="reportProblemTitleInput" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
              Short issue title
              <input
                id="reportProblemTitleInput"
                value={form.title}
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                maxLength={120}
                required
                style={{ width: '100%', padding: '10px 14px', borderRadius: '10px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </label>

            <label htmlFor="reportProblemDescriptionInput" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
              What happened
              <textarea
                id="reportProblemDescriptionInput"
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
                minLength={10}
                maxLength={4000}
                rows={5}
                required
                style={{ width: '100%', padding: '12px 14px', borderRadius: '12px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', lineHeight: 1.6, resize: 'vertical', boxSizing: 'border-box' }}
              />
            </label>

            <label htmlFor="reportProblemPathInput" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
              Current page or path
              <input
                id="reportProblemPathInput"
                value={form.currentPath}
                onChange={(event) => setForm((current) => ({ ...current, currentPath: event.target.value }))}
                maxLength={300}
                style={{ width: '100%', padding: '10px 14px', borderRadius: '10px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </label>

            <div style={{ display: 'grid', gap: '12px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
              <label htmlFor="reportProblemUsernameInput" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
                Username
                <input
                  id="reportProblemUsernameInput"
                  value={form.username}
                  onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
                  maxLength={64}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: '10px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
                />
              </label>

              <label htmlFor="reportProblemEmailInput" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
                Contact email
                <input
                  id="reportProblemEmailInput"
                  type="email"
                  value={form.contactEmail}
                  onChange={(event) => setForm((current) => ({ ...current, contactEmail: event.target.value }))}
                  maxLength={255}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: '10px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
                />
              </label>
            </div>

            <label htmlFor="reportProblemDeviceInput" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
              Device and browser
              <input
                id="reportProblemDeviceInput"
                value={form.deviceInfo}
                onChange={(event) => setForm((current) => ({ ...current, deviceInfo: event.target.value }))}
                maxLength={500}
                style={{ width: '100%', padding: '10px 14px', borderRadius: '10px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </label>

            <div style={{ display: 'grid', gap: '8px' }}>
              <div style={{ display: 'grid', gap: '4px' }}>
                <span style={{ color: tokens.colors.textPrimary, fontSize: '13px' }}>Screenshot</span>
                <span style={{ color: tokens.colors.textSecondary, fontSize: '12px', lineHeight: 1.5 }}>
                  Optional. One PNG, JPEG, or WebP image up to 5 MB.
                </span>
              </div>
              <input
                ref={attachmentInputRef}
                id="reportProblemAttachmentInput"
                type="file"
                accept={ALLOWED_ATTACHMENT_TYPES.join(',')}
                onChange={handleAttachmentChange}
                style={{ display: 'none' }}
              />
              <div style={{ borderRadius: '12px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, padding: '12px 14px', display: 'grid', gap: '10px' }}>
                <div style={{ color: attachment ? tokens.colors.textPrimary : tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.5, wordBreak: 'break-word' }}>
                  {attachment ? `${attachment.name} • ${formatAttachmentSize(attachment.size)}` : 'No attachment selected'}
                </div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <label
                    htmlFor="reportProblemAttachmentInput"
                    style={{
                      width: 'fit-content',
                      borderRadius: '999px',
                      border: `1px solid ${tokens.colors.border}`,
                      padding: '9px 14px',
                      backgroundColor: tokens.colors.bg,
                      color: tokens.colors.textPrimary,
                      cursor: 'pointer',
                      fontSize: '12px',
                      fontWeight: 600,
                    }}
                  >
                    {attachment ? 'Replace image' : 'Add image'}
                  </label>
                  {attachment ? (
                    <button
                      type="button"
                      onClick={clearAttachment}
                      style={{
                        width: 'fit-content',
                        borderRadius: '999px',
                        border: `1px solid ${tokens.colors.border}`,
                        padding: '9px 14px',
                        backgroundColor: tokens.colors.surface,
                        color: tokens.colors.textSecondary,
                        cursor: 'pointer',
                        fontSize: '12px',
                        fontWeight: 600,
                      }}
                    >
                      Remove
                    </button>
                  ) : null}
                </div>
              </div>
            </div>

            {error ? (
              <div style={{ padding: '12px 14px', borderRadius: '12px', border: `1px solid ${tokens.colors.danger}`, color: tokens.colors.danger, backgroundColor: 'rgba(244, 33, 46, 0.08)', fontSize: '13px' }}>
                {error}
              </div>
            ) : null}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                type="button"
                onClick={onClose}
                disabled={isSubmitting}
                style={{
                  border: `1px solid ${tokens.colors.border}`,
                  borderRadius: '999px',
                  padding: '11px 16px',
                  backgroundColor: tokens.colors.surface,
                  color: tokens.colors.textPrimary,
                  cursor: isSubmitting ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: '13px',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                style={{
                  border: 'none',
                  borderRadius: '999px',
                  padding: '11px 18px',
                  backgroundColor: isSubmitting ? tokens.colors.surfaceElevated : tokens.colors.accent,
                  color: tokens.colors.bg,
                  cursor: isSubmitting ? 'not-allowed' : 'pointer',
                  fontWeight: 600,
                  fontSize: '13px',
                }}
              >
                {isSubmitting ? 'Sending…' : 'Send report'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
