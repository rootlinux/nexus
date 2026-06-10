'use client'

import { useEffect, useRef, useState } from 'react'
import { Ellipsis, Flag } from 'lucide-react'

import { tokens } from '../../styles/tokens'
import { reportPost } from '../../lib/api'

const REPORT_REASONS = [
  { value: 'spam', label: 'Spam' },
  { value: 'harassment', label: 'Harassment' },
  { value: 'inappropriate', label: 'Inappropriate content' },
  { value: 'other', label: 'Other' },
] as const

interface ReportPostMenuProps {
  postId: number
}

export function ReportPostMenu({ postId }: ReportPostMenuProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [selectedReason, setSelectedReason] = useState<string>('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!menuOpen) return

    const handlePointerDown = (event: MouseEvent | globalThis.MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [menuOpen])

  useEffect(() => {
    if (!menuOpen && !confirmOpen) return

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (confirmOpen && !isSubmitting) {
          setConfirmOpen(false)
        } else {
          setMenuOpen(false)
        }
      }
    }

    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [menuOpen, confirmOpen, isSubmitting])

  const handleReport = async () => {
    if (!selectedReason) return
    setIsSubmitting(true)
    try {
      await reportPost(postId, selectedReason)
      setSubmitted(true)
      setTimeout(() => {
        setConfirmOpen(false)
        setMenuOpen(false)
        setSubmitted(false)
        setSelectedReason('')
      }, 2000)
    } catch {
      setIsSubmitting(false)
    }
  }

  return (
    <>
      <div ref={containerRef} style={{ position: 'relative' }}>
        <button
          type="button"
          aria-label="Post actions"
          aria-expanded={menuOpen}
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            setMenuOpen((current) => !current)
          }}
          style={{
            width: '30px',
            height: '30px',
            borderRadius: tokens.radius.full,
            border: `1px solid ${menuOpen ? tokens.colors.border : 'transparent'}`,
            backgroundColor: menuOpen ? tokens.colors.surface : 'transparent',
            color: tokens.colors.textSecondary,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: tokens.transition.fast,
          }}
        >
          <Ellipsis size={16} strokeWidth={2} />
        </button>

        {menuOpen ? (
          <div
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
            }}
            style={{
              position: 'absolute',
              top: 'calc(100% + 8px)',
              right: 0,
              minWidth: '180px',
              padding: '6px',
              borderRadius: '14px',
              border: `1px solid ${tokens.colors.border}`,
              backgroundColor: tokens.colors.surface,
              boxShadow: '0 16px 40px rgba(0, 0, 0, 0.35)',
              zIndex: 40,
            }}
          >
            <button
              type="button"
              onClick={() => {
                setConfirmOpen(true)
                setMenuOpen(false)
              }}
              style={{
                width: '100%',
                border: 'none',
                background: 'transparent',
                color: tokens.colors.textSecondary,
                padding: '10px 12px',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                fontSize: tokens.font.sm,
                fontWeight: Number(tokens.font.weightMedium),
                cursor: 'pointer',
              }}
            >
              <Flag size={15} strokeWidth={1.9} />
              Report post
            </button>
          </div>
        ) : null}
      </div>

      {confirmOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
            backgroundColor: 'rgba(0, 0, 0, 0.68)',
          }}
          onClick={() => {
            if (!isSubmitting) setConfirmOpen(false)
          }}
        >
          <div
            onClick={(event) => event.stopPropagation()}
            style={{
              width: '100%',
              maxWidth: '380px',
              borderRadius: '22px',
              border: `1px solid ${tokens.colors.border}`,
              backgroundColor: tokens.colors.bg,
              padding: '22px',
              display: 'grid',
              gap: '14px',
              boxShadow: '0 24px 64px rgba(0, 0, 0, 0.42)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Flag size={20} color={tokens.colors.accent} strokeWidth={1.9} />
              <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.lg, fontWeight: Number(tokens.font.weightSemibold) }}>
                Report post
              </div>
            </div>
            {submitted ? (
              <div style={{ color: tokens.colors.success, fontSize: tokens.font.sm }}>
                Report submitted. Thank you for helping keep the community safe.
              </div>
            ) : (
              <>
                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.55 }}>
                  Why are you reporting this post?
                </div>
                <div style={{ display: 'grid', gap: '8px' }}>
                  {REPORT_REASONS.map((reason) => (
                    <button
                      key={reason.value}
                      type="button"
                      onClick={() => setSelectedReason(reason.value)}
                      style={{
                        width: '100%',
                        border: `1px solid ${selectedReason === reason.value ? tokens.colors.accent : tokens.colors.border}`,
                        backgroundColor: selectedReason === reason.value ? `${tokens.colors.accent}15` : 'transparent',
                        color: tokens.colors.textPrimary,
                        padding: '10px 12px',
                        borderRadius: '10px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '10px',
                        fontSize: tokens.font.sm,
                        fontWeight: Number(tokens.font.weightMedium),
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                    >
                      {reason.label}
                    </button>
                  ))}
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                  <button
                    type="button"
                    className="btn-ghost"
                    disabled={isSubmitting}
                    onClick={() => setConfirmOpen(false)}
                    style={{
                      borderRadius: tokens.radius.full,
                      color: tokens.colors.textPrimary,
                      padding: '10px 16px',
                      fontWeight: Number(tokens.font.weightMedium),
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={!selectedReason || isSubmitting}
                    onClick={() => void handleReport()}
                    style={{
                      border: `1px solid ${tokens.colors.dangerMuted}`,
                      backgroundColor: tokens.colors.dangerSurface,
                      color: tokens.colors.danger,
                      borderRadius: tokens.radius.full,
                      padding: '10px 16px',
                      fontWeight: Number(tokens.font.weightSemibold),
                      cursor: !selectedReason || isSubmitting ? 'default' : 'pointer',
                      opacity: !selectedReason || isSubmitting ? 0.6 : 1,
                    }}
                  >
                    {isSubmitting ? 'Submitting...' : 'Submit report'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}
    </>
  )
}
