'use client'

import { useRef, useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'
import { Image as ImageIcon, Smile } from 'lucide-react'
import { tokens } from '../../styles/tokens'
import { Avatar } from './Avatar'

interface ComposerProps {
  username: string
  newPost: string
  posting: boolean
  uploadingImage: boolean
  selectedImage: File | null
  imagePreview: string | null
  imageError: string
  showEmojiPicker: boolean
  placeholder: string
  onPostChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void
  onImageSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
  onRemoveImage: () => void
  onCloseEmojiPicker: () => void
  onToggleEmojiPicker: () => void
}

export function Composer({
  username,
  newPost,
  posting,
  uploadingImage,
  selectedImage,
  imagePreview,
  imageError,
  showEmojiPicker,
  placeholder,
  onPostChange,
  onSubmit,
  onKeyDown,
  onImageSelect,
  onRemoveImage,
  onCloseEmojiPicker,
  onToggleEmojiPicker,
}: ComposerProps) {
  const emojiPickerRef = useRef<HTMLDivElement>(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!showEmojiPicker) return
    const handleClickOutside = (event: MouseEvent) => {
      if (emojiPickerRef.current && !emojiPickerRef.current.contains(event.target as Node)) {
        onCloseEmojiPicker()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showEmojiPicker, onCloseEmojiPicker])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'n' && (event.metaKey || event.ctrlKey) && !isExpanded) {
        event.preventDefault()
        setIsExpanded(true)
      }
    }
    document.addEventListener('keydown', handleKeyDown as unknown as EventListener)
    return () => document.removeEventListener('keydown', handleKeyDown as unknown as EventListener)
  }, [isExpanded])

  if (!isExpanded) {
    return (
      <div style={{
        backgroundColor: tokens.colors.surface,
        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
        padding: '16px 24px',
      }}>
        <button
          ref={triggerRef}
          onClick={() => setIsExpanded(true)}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '10px 14px',
            backgroundColor: 'transparent',
            border: `1px dashed ${tokens.colors.border}`,
            borderRadius: '10px',
            color: tokens.colors.textMuted,
            fontSize: '14px',
            cursor: 'pointer',
            textAlign: 'left',
          }}
        >
          <Avatar username={username || 'x'} />
          <span style={{ flex: 1 }}>Share something measured…</span>
          <span style={{
            color: tokens.colors.textMuted,
            fontSize: '11px',
            fontFamily: 'monospace',
          }}>
            ⌘N
          </span>
        </button>
      </div>
    )
  }

  return (
    <div style={{
      backgroundColor: tokens.colors.surface,
      borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
      padding: '20px 24px',
    }}>
      <div style={{ display: 'flex', gap: '12px' }}>
        <Avatar username={username || 'x'} />
        
        <form
          onSubmit={onSubmit}
          style={{ flex: 1, display: 'flex', flexDirection: 'column', margin: 0 }}
        >
          {imagePreview && (
            <div style={{
              position: 'relative',
              marginBottom: '12px',
              borderRadius: '12px',
              overflow: 'hidden',
              border: `1px solid ${tokens.colors.border}`,
            }}>
              <img
                src={imagePreview}
                alt="Preview"
                style={{
                  width: '100%',
                  maxHeight: '200px',
                  objectFit: 'cover',
                }}
              />
              <button
                type="button"
                onClick={onRemoveImage}
                style={{
                  position: 'absolute',
                  top: '8px',
                  right: '8px',
                  backgroundColor: tokens.colors.surface,
                  border: 'none',
                  borderRadius: '50%',
                  width: '28px',
                  height: '28px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  color: tokens.colors.textPrimary,
                  fontSize: '18px',
                }}
              >
                ×
              </button>
            </div>
          )}
          
          {imageError && (
            <div style={{
              color: tokens.colors.danger,
              fontSize: tokens.font.sm,
              marginBottom: '8px',
            }}>
              {imageError}
            </div>
          )}
          
          <textarea
            value={newPost}
            onChange={e => onPostChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            style={{
              width: '100%',
              minHeight: '60px',
              maxHeight: '200px',
              height: 'auto',
              resize: 'none',
              border: 'none',
              background: 'transparent',
              color: tokens.colors.textPrimary,
              fontSize: tokens.font.base,
              fontFamily: 'inherit',
              outline: 'none',
              lineHeight: 1.6,
              padding: '4px 0',
              caretColor: tokens.colors.accent,
            }}
            maxLength={280}
            rows={1}
            onInput={(event: FormEvent<HTMLTextAreaElement>) => {
              event.currentTarget.style.height = 'auto'
              event.currentTarget.style.height = `${event.currentTarget.scrollHeight}px`
            }}
            autoFocus
          />
          
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: '12px',
            paddingTop: '12px',
            borderTop: `1px solid ${tokens.colors.borderSubtle}`,
            position: 'relative',
          }}>
            <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
              <input
                type="file"
                accept="image/jpeg,image/png,image/gif,image/webp"
                onChange={onImageSelect}
                style={{ display: 'none' }}
                id="image-upload"
              />
              
              {[
                { Icon: ImageIcon, label: 'Media', action: 'upload' },
                { Icon: Smile, label: 'Emoji', action: 'emoji' },
              ].map(({ Icon, label, action }, i) => {
                if (action === 'upload') {
                  return (
                    <label
                      key={i}
                      htmlFor="image-upload"
                      aria-label={label}
                      style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        padding: '6px',
                        borderRadius: '50%',
                        transition: tokens.transition.fast,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: '32px',
                        height: '32px',
                        flexShrink: 0,
                        color: tokens.colors.textPrimary,
                        opacity: 0.72,
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.opacity = '1'
                        e.currentTarget.style.backgroundColor = tokens.colors.surfaceElevated
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.opacity = '0.72'
                        e.currentTarget.style.backgroundColor = 'transparent'
                      }}
                    >
                      <Icon size={18} strokeWidth={1.75} />
                    </label>
                  )
                }
                return (
                  <button
                    key={i}
                    type="button"
                    aria-label={label}
                    onClick={onToggleEmojiPicker}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      padding: '6px',
                      borderRadius: '50%',
                      transition: tokens.transition.fast,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: '32px',
                      height: '32px',
                      flexShrink: 0,
                      color: showEmojiPicker ? tokens.colors.textPrimary : tokens.colors.textSecondary,
                    }}
                    onMouseEnter={e => {
                      if (!showEmojiPicker) {
                        e.currentTarget.style.color = tokens.colors.textPrimary
                        e.currentTarget.style.backgroundColor = tokens.colors.surfaceElevated
                      }
                    }}
                    onMouseLeave={e => {
                      if (!showEmojiPicker) {
                        e.currentTarget.style.color = tokens.colors.textSecondary
                        e.currentTarget.style.backgroundColor = 'transparent'
                      }
                    }}
                  >
                    <Icon size={18} strokeWidth={1.75} />
                  </button>
                )
              })}
            </div>
            
            {showEmojiPicker && (
              <div
                ref={emojiPickerRef}
                style={{
                  position: 'absolute',
                  marginTop: '8px',
                  backgroundColor: tokens.colors.surface,
                  border: `1px solid ${tokens.colors.border}`,
                  borderRadius: tokens.radius.lg,
                  padding: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                  zIndex: 100,
                  display: 'grid',
                  gridTemplateColumns: 'repeat(8, 1fr)',
                  gap: '4px',
                  maxWidth: '320px',
                }}
              >
                {['😀', '😃', '😄', '😁', '😆', '😅', '🤣', '😂', '🙂', '🙃', '😉', '😊', '😇', '🥰', '😍', '🤩', '😘', '😗', '☺️', '😚', '😙', '🥲', '😋', '😛', '😜', '🤪', '😝', '🤑', '🤗', '🤭', '🤫', '🤔', '🤐', '🤨', '😐', '😑', '😶', '😏', '😒', '🙄', '😬', '🤥', '😌', '😔', '😪', '🤤', '😴', '😷', '🤒', '🤕', '🤢', '🤮', '🤧', '🥵', '🥶', '🥴', '😵', '🤯', '🤠', '🥳', '🥸', '😎', '🤓', '🧐'].map((emoji, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      onPostChange(newPost + emoji)
                      onCloseEmojiPicker()
                    }}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '20px',
                      padding: '4px',
                      borderRadius: '4px',
                      transition: tokens.transition.fast,
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.backgroundColor = tokens.colors.surfaceElevated
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.backgroundColor = 'transparent'
                    }}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            )}
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{
                color: newPost.length > 260 ? tokens.colors.danger : tokens.colors.textSecondary,
                fontSize: '13px',
                minWidth: '40px',
                textAlign: 'right',
              }}>
                {newPost.length}/280
              </span>
              <button
                type="submit"
                className="btn-ghost"
                disabled={posting || uploadingImage || (!newPost.trim() && !selectedImage)}
                style={{
                  color: (newPost.trim() || selectedImage) && !posting ? tokens.colors.textPrimary : tokens.colors.textMuted,
                  borderRadius: tokens.radius.md,
                  height: '32px',
                  minWidth: '64px',
                  padding: '0 16px',
                  fontWeight: Number(tokens.font.weightMedium),
                  fontSize: tokens.font.sm,
                  transition: tokens.transition.fast,
                }}
              >
                {posting || uploadingImage ? (
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{
                      width: '12px',
                      height: '12px',
                      border: `2px solid ${tokens.colors.border}`,
                      borderTopColor: tokens.colors.textPrimary,
                      borderRadius: '50%',
                      animation: 'spin 0.8s linear infinite',
                    }} />
                    Post
                  </span>
                ) : 'Post'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
