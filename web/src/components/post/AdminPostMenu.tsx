'use client'

import { useEffect, useRef, useState } from 'react'
import { Ellipsis, Shield, Trash2 } from 'lucide-react'

import { tokens } from '../../styles/tokens'

interface AdminPostMenuProps {
  postId: number
  onDeleteAsAdmin: (postId: number) => Promise<boolean>
  isDeleting?: boolean
}

export function AdminPostMenu({
  postId,
  onDeleteAsAdmin,
  isDeleting = false,
}: AdminPostMenuProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
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
        if (confirmOpen && !isDeleting) {
          setConfirmOpen(false)
        } else {
          setMenuOpen(false)
        }
      }
    }

    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [menuOpen, confirmOpen, isDeleting])

  const handleDeleteAsAdmin = async () => {
    const deleted = await onDeleteAsAdmin(postId)
    if (deleted) {
      setConfirmOpen(false)
      setMenuOpen(false)
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
              minWidth: '200px',
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
                color: tokens.colors.danger,
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
              <Shield size={15} strokeWidth={1.9} />
              Delete as admin
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
            if (!isDeleting) setConfirmOpen(false)
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
              <Shield size={20} color={tokens.colors.danger} strokeWidth={1.9} />
              <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.lg, fontWeight: Number(tokens.font.weightSemibold) }}>
                Admin Delete
              </div>
            </div>
            <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.55 }}>
              Bu postu kaldırmak istediğinizden emin misiniz? Bu işlem geri alınamaz.
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                type="button"
                className="btn-ghost"
                disabled={isDeleting}
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
                disabled={isDeleting}
                onClick={() => void handleDeleteAsAdmin()}
                style={{
                  border: `1px solid ${tokens.colors.dangerMuted}`,
                  backgroundColor: tokens.colors.dangerSurface,
                  color: tokens.colors.danger,
                  borderRadius: tokens.radius.full,
                  padding: '10px 16px',
                  fontWeight: Number(tokens.font.weightSemibold),
                  cursor: isDeleting ? 'default' : 'pointer',
                }}
              >
                {isDeleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}