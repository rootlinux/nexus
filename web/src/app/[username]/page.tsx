'use client'

import { useEffect, useState, useRef, FormEvent } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { CalendarDays, Camera, Flag, Globe, LoaderCircle, MapPin, Pencil, Shield, TreePine, UserPlus, UserMinus, Upload, X } from 'lucide-react'

import Layout from '../../components/Layout'
import { useAuth } from '../../contexts/AuthContext'
import { getProfile, getUserTimeline, toggleFollow, getFollowers, getFollowing, updateMyProfile, uploadMyAvatar, uploadMyCover, reportUser } from '../../lib/api'
import { resolveMediaUrl } from '../../lib/media'
import { getProfileHref } from '../../lib/routes'
import { tokens } from '../../styles/tokens'
import type { User, Post } from '../../types'

type TimelineView = 'posts' | 'replies' | 'media' | 'likes' | 'reposts'

function formatMemberSince(dateStr: string) {
  return new Date(dateStr).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

function FollowersModal({
  username,
  initialUsers,
  title,
  onClose,
}: {
  username: string
  initialUsers: Array<{ id: number; username: string; display_name?: string | null; avatar_url: string | null }>
  title: string
  onClose: () => void
}) {
  const [users] = useState(initialUsers)

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.7)',
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: tokens.colors.surfaceElevated,
          borderRadius: 16,
          width: '90%',
          maxWidth: 400,
          maxHeight: '80vh',
          overflow: 'hidden',
          border: `1px solid ${tokens.colors.border}`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ padding: '16px 20px', borderBottom: `1px solid ${tokens.colors.borderSubtle}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 600, fontSize: tokens.font.md }}>{title}</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: tokens.colors.textMuted, cursor: 'pointer', padding: 4 }}>✕</button>
        </div>
        <div style={{ maxHeight: 400, overflowY: 'auto' }}>
          {users.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: tokens.colors.textMuted }}>No users yet</div>
          ) : (
            users.map((user) => (
              <Link
                key={user.id}
                href={getProfileHref(user.username)}
                onClick={onClose}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '12px 20px',
                  borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                  textDecoration: 'none',
                  color: 'inherit',
                }}
              >
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: '50%',
                    overflow: 'hidden',
                    backgroundColor: tokens.colors.surface,
                    flexShrink: 0,
                  }}
                >
                  {user.avatar_url ? (
                    <img src={resolveMediaUrl(user.avatar_url) ?? ''} alt={user.username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <UserPlus size={20} color={tokens.colors.textMuted} />
                    </div>
                  )}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: tokens.font.sm }}>{user.display_name || user.username}</div>
                  <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.xs }}>@{user.username}</div>
                </div>
              </Link>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Image Crop Helper ───────────────────────────────────────────────────────

type CropType = 'avatar' | 'cover'

type PendingCrop = {
  imageUrl: string
  aspectRatio: number
  onConfirm: (blob: Blob) => void
  onCancel: () => void
}

function CropOverlay({ imageUrl, aspectRatio, onConfirm, onCancel }: PendingCrop) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [cropRect, setCropRect] = useState<{ x: number; y: number; width: number; height: number } | null>(null)
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [cropOffset, setCropOffset] = useState<{ x: number; y: number } | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)

  // Load image and calculate initial crop rect
  useEffect(() => {
    const img = new Image()
    img.onload = () => {
      imageRef.current = img
      const container = containerRef.current
      if (!container) return

      const containerWidth = container.clientWidth
      const containerHeight = container.clientHeight

      // Scale image to fit container while maintaining aspect ratio
      const imgAspect = img.width / img.height
      let drawWidth = containerWidth
      let drawHeight = containerWidth / imgAspect
      if (drawHeight > containerHeight) {
        drawHeight = containerHeight
        drawWidth = containerHeight * imgAspect
      }

      const displayWidth = drawWidth
      const displayHeight = drawHeight

      setImageSize({ width: displayWidth, height: displayHeight })

      // Initial crop rect centered, respecting aspect ratio
      const maxCropWidth = displayWidth * 0.9
      let cropWidth = maxCropWidth
      let cropHeight = cropWidth / aspectRatio

      if (cropHeight > displayHeight * 0.9) {
        cropHeight = displayHeight * 0.9
        cropWidth = cropHeight * aspectRatio
      }

      const x = (displayWidth - cropWidth) / 2
      const y = (displayHeight - cropHeight) / 2

      setCropRect({ x, y, width: cropWidth, height: cropHeight })
    }
    img.src = imageUrl
  }, [imageUrl, aspectRatio])

  // Draw canvas
  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    const img = imageRef.current
    if (!canvas || !ctx || !img || !imageSize || !cropRect) return

    canvas.width = imageSize.width
    canvas.height = imageSize.height

    // Draw image
    const imgAspect = img.width / img.height
    let sx = 0, sy = 0, sWidth = img.width, sHeight = img.height
    if (imgAspect > imageSize.width / imageSize.height) {
      sHeight = img.width / (imageSize.width / imageSize.height)
      sy = (img.height - sHeight) / 2
    } else {
      sWidth = img.height * (imageSize.width / imageSize.height)
      sx = (img.width - sWidth) / 2
    }

    ctx.drawImage(img, sx, sy, sWidth, sHeight, 0, 0, imageSize.width, imageSize.height)

    // Draw dark overlay outside crop
    ctx.fillStyle = 'rgba(0, 0, 0, 0.6)'
    ctx.fillRect(0, 0, imageSize.width, cropRect.y)
    ctx.fillRect(0, cropRect.y, cropRect.x, cropRect.height)
    ctx.fillRect(cropRect.x + cropRect.width, cropRect.y, imageSize.width - cropRect.x - cropRect.width, cropRect.height)
    ctx.fillRect(0, cropRect.y + cropRect.height, imageSize.width, imageSize.height - cropRect.y - cropRect.height)

    // Draw crop border
    ctx.strokeStyle = '#c9a96e'
    ctx.lineWidth = 2
    ctx.strokeRect(cropRect.x, cropRect.y, cropRect.width, cropRect.height)

    // Draw grid lines (rule of thirds)
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)'
    ctx.lineWidth = 1
    const thirdW = cropRect.width / 3
    const thirdH = cropRect.height / 3
    for (let i = 1; i < 3; i++) {
      ctx.beginPath()
      ctx.moveTo(cropRect.x + thirdW * i, cropRect.y)
      ctx.lineTo(cropRect.x + thirdW * i, cropRect.y + cropRect.height)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(cropRect.x, cropRect.y + thirdH * i)
      ctx.lineTo(cropRect.x + cropRect.width, cropRect.y + thirdH * i)
      ctx.stroke()
    }
  }, [imageSize, cropRect])

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!cropRect || !imageSize) return
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    setDragStart({ x, y })
    setCropOffset({ x: x - cropRect.x, y: y - cropRect.y })
    setIsDragging(true)
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!isDragging || !cropRect || !imageSize || !dragStart || !cropOffset) return
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    let newX = x - cropOffset.x
    let newY = y - cropOffset.y

    // Clamp to image bounds
    newX = Math.max(0, Math.min(newX, imageSize.width - cropRect.width))
    newY = Math.max(0, Math.min(newY, imageSize.height - cropRect.height))

    setCropRect({ ...cropRect, x: newX, y: newY })
  }

  const handlePointerUp = () => {
    setIsDragging(false)
    setDragStart(null)
    setCropOffset(null)
  }

  const handleConfirm = () => {
    const canvas = document.createElement('canvas')
    const img = imageRef.current
    if (!img || !cropRect || !imageSize) return

    const cropPixelW = (cropRect.width / imageSize.width) * img.width
    const cropPixelH = (cropRect.height / imageSize.height) * img.height
    const cropPixelX = (cropRect.x / imageSize.width) * img.width
    const cropPixelY = (cropRect.y / imageSize.height) * img.height

    canvas.width = cropPixelW
    canvas.height = cropPixelH
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(img, cropPixelX, cropPixelY, cropPixelW, cropPixelH, 0, 0, cropPixelW, cropPixelH)

    canvas.toBlob(
      (blob) => {
        if (blob) onConfirm(blob)
      },
      'image/jpeg',
      0.92
    )
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.9)',
        padding: 20,
      }}
    >
      <div style={{ color: '#fff', fontSize: tokens.font.md, fontWeight: 600, marginBottom: 16, textAlign: 'center' }}>
        {aspectRatio === 1 ? 'Crop avatar' : 'Crop cover'}
      </div>

      <div
        ref={containerRef}
        style={{
          position: 'relative',
          maxWidth: '100%',
          maxHeight: '60vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          touchAction: 'none',
        }}
      >
        <canvas
          ref={canvasRef}
          style={{
            maxWidth: '100%',
            maxHeight: '60vh',
            cursor: isDragging ? 'grabbing' : 'grab',
            borderRadius: 4,
          }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        />
      </div>

      <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
        <button
          onClick={onCancel}
          style={{
            padding: '12px 24px',
            borderRadius: 8,
            border: `1px solid ${tokens.colors.border}`,
            backgroundColor: 'transparent',
            color: '#fff',
            fontWeight: 600,
            cursor: 'pointer',
            fontSize: tokens.font.base,
          }}
        >
          Cancel
        </button>
        <button
          onClick={handleConfirm}
          style={{
            padding: '12px 24px',
            borderRadius: 8,
            border: 'none',
            backgroundColor: tokens.colors.accent,
            color: '#fff',
            fontWeight: 600,
            cursor: 'pointer',
            fontSize: tokens.font.base,
          }}
        >
          Confirm
        </button>
      </div>
    </div>
  )
}

// ─── Edit Profile Modal ───────────────────────────────────────────────────────

function EditProfileModal({
  profile,
  onClose,
  onSave,
}: {
  profile: User
  onClose: () => void
  onSave: () => void
}) {
  const [displayName, setDisplayName] = useState(profile.display_name || '')
  const [bio, setBio] = useState(profile.bio || '')
  const [location, setLocation] = useState(profile.location || '')
  const [website, setWebsite] = useState(profile.website || '')
  const [avatarPreview, setAvatarPreview] = useState<string | null>(profile.avatar_url ? resolveMediaUrl(profile.avatar_url) : null)
  const [coverPreview, setCoverPreview] = useState<string | null>(profile.cover_url ? resolveMediaUrl(profile.cover_url) : null)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')

  // Store cropped blobs for upload (instead of original files)
  const [avatarCropBlob, setAvatarCropBlob] = useState<Blob | null>(null)
  const [coverCropBlob, setCoverCropBlob] = useState<Blob | null>(null)

  // Pending crop state
  const [pendingCrop, setPendingCrop] = useState<PendingCrop | null>(null)

  // Hidden file inputs
  const avatarInputRef = useRef<HTMLInputElement>(null)
  const coverInputRef = useRef<HTMLInputElement>(null)

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const objectUrl = URL.createObjectURL(file)
    setPendingCrop({
      imageUrl: objectUrl,
      aspectRatio: 1, // 1:1 square for avatar
      onConfirm: (blob: Blob) => {
        setAvatarCropBlob(blob)
        setAvatarPreview(URL.createObjectURL(blob))
        setPendingCrop(null)
      },
      onCancel: () => {
        URL.revokeObjectURL(objectUrl)
        setPendingCrop(null)
        // Reset file input
        if (avatarInputRef.current) avatarInputRef.current.value = ''
      },
    })
  }

  const handleCoverChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const objectUrl = URL.createObjectURL(file)
    setPendingCrop({
      imageUrl: objectUrl,
      aspectRatio: 4, // 4:1 wide banner for cover
      onConfirm: (blob: Blob) => {
        setCoverCropBlob(blob)
        setCoverPreview(URL.createObjectURL(blob))
        setPendingCrop(null)
      },
      onCancel: () => {
        URL.revokeObjectURL(objectUrl)
        setPendingCrop(null)
        // Reset file input
        if (coverInputRef.current) coverInputRef.current.value = ''
      },
    })
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setIsSaving(true)
    setError('')
    try {
      // Upload avatar if changed (convert Blob to File for API compatibility)
      if (avatarCropBlob) {
        const avatarFile = new File([avatarCropBlob], 'avatar.jpg', { type: 'image/jpeg' })
        await uploadMyAvatar(avatarFile)
      }

      // Upload cover if changed (convert Blob to File for API compatibility)
      if (coverCropBlob) {
        const coverFile = new File([coverCropBlob], 'cover.jpg', { type: 'image/jpeg' })
        await uploadMyCover(coverFile)
      }

      // Update profile fields
      await updateMyProfile({
        display_name: displayName || null,
        bio: bio || null,
        location: location || null,
        website: website || null,
      })

      onSave()
      onClose()
    } catch (err) {
      setError('Failed to save profile. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.7)',
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: tokens.colors.surfaceElevated,
          borderRadius: 16,
          width: '90%',
          maxWidth: 480,
          maxHeight: '90vh',
          overflow: 'hidden',
          border: `1px solid ${tokens.colors.border}`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ padding: '16px 20px', borderBottom: `1px solid ${tokens.colors.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 600, fontSize: tokens.font.md }}>Edit profile</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: tokens.colors.textMuted, cursor: 'pointer', padding: 4 }}>
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ overflow: 'auto', maxHeight: 'calc(90vh - 140px)' }}>
          {/* Cover image - full width, 160px height */}
          <div
            style={{
              height: 160,
              backgroundColor: tokens.colors.surface,
              backgroundImage: coverPreview ? `url(${coverPreview})` : undefined,
              backgroundSize: 'cover',
              backgroundPosition: 'center',
              position: 'relative',
            }}
          >
            <label
              htmlFor="cover-upload"
              style={{
                position: 'absolute',
                bottom: 12,
                right: 12,
                backgroundColor: 'rgba(0,0,0,0.7)',
                borderRadius: 8,
                padding: '8px 14px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                color: '#fff',
                fontSize: tokens.font.sm,
                fontWeight: 500,
              }}
            >
              <Upload size={16} />
              Cover
            </label>
            <input
              id="cover-upload"
              ref={coverInputRef}
              type="file"
              accept="image/*"
              onChange={handleCoverChange}
              style={{ display: 'none' }}
            />
          </div>

          {/* Avatar - separate section below cover */}
          <div style={{ padding: '0 20px', display: 'flex', alignItems: 'flex-start', marginTop: -40 }}>
            <div
              style={{
                position: 'relative',
                width: 80,
                height: 80,
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  width: 80,
                  height: 80,
                  borderRadius: '50%',
                  border: `4px solid ${tokens.colors.surfaceElevated}`,
                  overflow: 'hidden',
                  backgroundColor: tokens.colors.surface,
                }}
              >
                {avatarPreview ? (
                  <img src={avatarPreview} alt={profile.username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                ) : (
                  <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: tokens.colors.textMuted }}>
                    <UserPlus size={32} />
                  </div>
                )}
              </div>
              <label
                htmlFor="avatar-upload"
                style={{
                  position: 'absolute',
                  inset: 0,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: 'rgba(0,0,0,0.5)',
                  borderRadius: '50%',
                  opacity: 0,
                  transition: tokens.transition.fast,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                onMouseLeave={(e) => (e.currentTarget.style.opacity = '0')}
              >
                <Camera size={24} color="#fff" />
              </label>
              <input
                id="avatar-upload"
                ref={avatarInputRef}
                type="file"
                accept="image/*"
                onChange={handleAvatarChange}
                style={{ display: 'none' }}
              />
            </div>
          </div>

          <div style={{ padding: '20px 20px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
            {error && (
              <div style={{ padding: '10px 14px', borderRadius: 8, border: `1px solid ${tokens.colors.danger}`, color: tokens.colors.danger, fontSize: tokens.font.sm, backgroundColor: tokens.colors.dangerSurface }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: tokens.font.sm, color: tokens.colors.textSecondary }}>Display name</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Your display name"
                maxLength={80}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: tokens.colors.bg,
                  color: tokens.colors.textPrimary,
                  fontSize: tokens.font.base,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: tokens.font.sm, color: tokens.colors.textSecondary }}>Bio</label>
              <textarea
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                placeholder="Tell others about yourself"
                maxLength={500}
                rows={3}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: tokens.colors.bg,
                  color: tokens.colors.textPrimary,
                  fontSize: tokens.font.base,
                  outline: 'none',
                  resize: 'vertical',
                  fontFamily: 'inherit',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: tokens.font.sm, color: tokens.colors.textSecondary }}>Location</label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="City, country"
                maxLength={100}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: tokens.colors.bg,
                  color: tokens.colors.textPrimary,
                  fontSize: tokens.font.base,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ fontSize: tokens.font.sm, color: tokens.colors.textSecondary }}>Website</label>
              <input
                type="url"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                placeholder="https://yourwebsite.com"
                maxLength={200}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: tokens.colors.bg,
                  color: tokens.colors.textPrimary,
                  fontSize: tokens.font.base,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 8 }}>
              <button
                type="button"
                onClick={onClose}
                disabled={isSaving}
                style={{
                  padding: '10px 20px',
                  borderRadius: 8,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: 'transparent',
                  color: tokens.colors.textPrimary,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontSize: tokens.font.base,
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSaving}
                style={{
                  padding: '10px 20px',
                  borderRadius: 8,
                  border: 'none',
                  backgroundColor: isSaving ? tokens.colors.surfaceElevated : tokens.colors.accent,
                  color: '#fff',
                  fontWeight: 600,
                  cursor: isSaving ? 'not-allowed' : 'pointer',
                  fontSize: tokens.font.base,
                }}
              >
                {isSaving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </form>

        {/* Crop overlay */}
        {pendingCrop && (
          <CropOverlay
            imageUrl={pendingCrop.imageUrl}
            aspectRatio={pendingCrop.aspectRatio}
            onConfirm={pendingCrop.onConfirm}
            onCancel={pendingCrop.onCancel}
          />
        )}
      </div>
    </div>
  )
}

function ProfileHeader({
  profile,
  isOwnProfile,
  isFollowing,
  isAdmin,
  onFollowToggle,
  followingLoading,
  onFollowersClick,
  onFollowingClick,
  onEditProfileClick,
  onReportClick,
}: {
  profile: User
  isOwnProfile: boolean
  isFollowing: boolean
  isAdmin: boolean
  onFollowToggle: () => void
  followingLoading: boolean
  onFollowersClick: () => void
  onFollowingClick: () => void
  onEditProfileClick: () => void
  onReportClick?: () => void
}) {
  const coverUrl = resolveMediaUrl(profile.cover_url)
  const avatarUrl = resolveMediaUrl(profile.avatar_url)

  return (
    <div>
      <div className="profile-cover">
        {coverUrl ? (
          <div className="profile-cover-media">
            <img src={coverUrl} alt="" />
          </div>
        ) : (
          <div className="profile-cover-base" />
        )}
        <div className="profile-cover-overlay" />
      </div>

      <div className="profile-summary-shell">
        <div className="profile-hero-row">
          <div className="profile-avatar-anchor">
            <div
              style={{
                width: 80,
                height: 80,
                borderRadius: '50%',
                overflow: 'hidden',
                border: `3px solid ${tokens.colors.surface}`,
                backgroundColor: tokens.colors.surface,
              }}
            >
              {avatarUrl ? (
                <img src={avatarUrl} alt={profile.username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ) : (
                <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <UserPlus size={32} color={tokens.colors.textMuted} />
                </div>
              )}
            </div>
          </div>

          <div className="profile-actions">
            {isOwnProfile ? (
              <>
                <Link href="/invites">
                  <button
                    style={{
                      padding: '8px 16px',
                      borderRadius: 9999,
                      border: `1px solid ${tokens.colors.border}`,
                      backgroundColor: 'transparent',
                      color: tokens.colors.textPrimary,
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <TreePine size={14} />
                    View membership access
                  </button>
                </Link>
                <button
                  onClick={onEditProfileClick}
                  style={{
                    padding: '8px 16px',
                    borderRadius: 9999,
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: 'transparent',
                    color: tokens.colors.textPrimary,
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  <Pencil size={14} />
                  Edit profile
                </button>
              </>
            ) : (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button
                  onClick={onFollowToggle}
                  disabled={followingLoading}
                  style={{
                    padding: '8px 16px',
                    borderRadius: 9999,
                    border: 'none',
                    backgroundColor: isFollowing ? 'transparent' : '#c9a84c',
                    color: isFollowing ? tokens.colors.textPrimary : '#0d0e12',
                    fontWeight: 600,
                    cursor: followingLoading ? 'not-allowed' : 'pointer',
                    opacity: followingLoading ? 0.6 : 1,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  {followingLoading ? (
                    <LoaderCircle size={14} style={{ animation: 'spin 1s linear infinite' }} />
                  ) : isFollowing ? (
                    <UserMinus size={14} />
                  ) : (
                    <UserPlus size={14} />
                  )}
                  {isFollowing ? 'Following' : 'Follow'}
                </button>
                {onReportClick && (
                  <button
                    onClick={onReportClick}
                    style={{
                      padding: '8px 16px',
                      borderRadius: 9999,
                      border: `1px solid ${tokens.colors.border}`,
                      backgroundColor: 'transparent',
                      color: tokens.colors.textSecondary,
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <Flag size={14} />
                    Report
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="profile-identity">
          <div style={{ fontWeight: 700, fontSize: tokens.font.xl, color: tokens.colors.textPrimary }}>
            {profile.display_name || profile.username}
          </div>
          <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sm }}>
            @{profile.username}
          </div>
          {profile.bio && (
            <div style={{ marginTop: 12, color: tokens.colors.textSecondary, fontSize: tokens.font.base, lineHeight: 1.5, fontStyle: 'italic' }}>
              {profile.bio}
            </div>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginTop: 12, color: tokens.colors.textMuted, fontSize: tokens.font.sm }}>
            {profile.location && (
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <MapPin size={14} />
                {profile.location}
              </span>
            )}
            {profile.website && (
              <a href={profile.website} target="_blank" rel="noopener noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 4, color: tokens.colors.accent }}>
                <Globe size={14} />
                {profile.website.replace(/^https?:\/\//, '')}
              </a>
            )}
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <CalendarDays size={14} />
              Joined {formatMemberSince(profile.created_at)}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 20, marginTop: 12 }}>
            <button
              onClick={onFollowingClick}
              style={{ background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 }}
            >
              <span style={{ fontWeight: 600, color: tokens.colors.textPrimary }}>{profile.following_count ?? 0}</span>{' '}
              <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sm }}>Following</span>
            </button>
            <button
              onClick={onFollowersClick}
              style={{ background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: 0 }}
            >
              <span style={{ fontWeight: 600, color: tokens.colors.textPrimary }}>{profile.followers_count ?? 0}</span>{' '}
              <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sm }}>Followers</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function TimelineTab({
  view,
  activeView,
  onClick,
}: {
  view: TimelineView
  activeView: TimelineView
  onClick: () => void
}) {
  const labels: Record<TimelineView, string> = {
    posts: 'Posts',
    replies: 'Replies',
    media: 'Media',
    likes: 'Likes',
    reposts: 'Reposts',
  }
  const isActive = view === activeView
  return (
    <button
      onClick={onClick}
      style={{
        padding: '12px 16px',
        color: isActive ? tokens.colors.accent : tokens.colors.textMuted,
        fontWeight: isActive ? 600 : 400,
        background: 'none',
        border: 'none',
        borderBottom: isActive ? `2px solid ${tokens.colors.accent}` : '2px solid transparent',
        cursor: 'pointer',
        fontSize: tokens.font.base,
      }}
    >
      {labels[view]}
    </button>
  )
}

function PostCard({ post }: { post: Post }) {
  const avatarUrl = resolveMediaUrl(post.author.avatar_url)
  const mediaUrl = resolveMediaUrl(post.media_url)

  return (
    <div
      style={{
        backgroundColor: tokens.colors.surface,
        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
        padding: '16px 24px',
      }}
    >
      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flexShrink: 0 }}>
          <Link href={getProfileHref(post.author.username)}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: '50%',
                overflow: 'hidden',
                backgroundColor: tokens.colors.surface,
              }}
            >
              {avatarUrl ? (
                <img src={avatarUrl ?? ''} alt={post.author.username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ) : (
                <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <UserPlus size={20} color={tokens.colors.textMuted} />
                </div>
              )}
            </div>
          </Link>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <Link href={getProfileHref(post.author.username)} style={{ fontWeight: 600, color: tokens.colors.textPrimary }}>
              {post.author.display_name || post.author.username}
            </Link>
            <span style={{ color: tokens.colors.textMuted, fontSize: tokens.font.sm }}>
              @{post.author.username}
            </span>
          </div>
          <div style={{ marginTop: 4, color: tokens.colors.textPrimary, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {post.content}
          </div>
          {mediaUrl && (
            <div style={{ marginTop: 12, borderRadius: 12, overflow: 'hidden', maxHeight: 300 }}>
              <img src={mediaUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

type ModalType = 'followers' | 'following' | 'report' | null

const REPORT_REASONS = [
  { value: 'Spam', label: 'Spam' },
  { value: 'Harassment', label: 'Harassment' },
  { value: 'Impersonation', label: 'Impersonation' },
  { value: 'Inappropriate content', label: 'Inappropriate content' },
  { value: 'Other', label: 'Other' },
]

export default function ProfilePage() {
  const params = useParams()
  const username = params.username as string
  const { user: currentUser, isLoading: isAuthLoading } = useAuth()

  const [profile, setProfile] = useState<User | null>(null)
  const [posts, setPosts] = useState<Post[]>([])
  const [timelineView, setTimelineView] = useState<TimelineView>('posts')
  const [loading, setLoading] = useState(true)
  const [timelineLoading, setTimelineLoading] = useState(true)
  const [error, setError] = useState('')
  const [followingLoading, setFollowingLoading] = useState(false)
  const [modalType, setModalType] = useState<ModalType>(null)
  const [followersList, setFollowersList] = useState<Array<{ id: number; username: string; display_name?: string | null; avatar_url: string | null }>>([])
  const [followingList, setFollowingList] = useState<Array<{ id: number; username: string; display_name?: string | null; avatar_url: string | null }>>([])
  const [isEditingProfile, setIsEditingProfile] = useState(false)
  const [reportReason, setReportReason] = useState('')
  const [reportSubmitting, setReportSubmitting] = useState(false)
  const [reportError, setReportError] = useState('')
  const [reportSuccess, setReportSuccess] = useState(false)

  const isOwnProfile = currentUser?.username === username
  const isAdmin = Boolean(currentUser?.is_admin)

  useEffect(() => {
    if (!username) return
    setLoading(true)
    setError('')
    getProfile(username)
      .then((data) => setProfile(data))
      .catch(() => setError('Failed to load profile'))
      .finally(() => setLoading(false))
  }, [username])

  useEffect(() => {
    if (!username || loading) return
    setTimelineLoading(true)
    getUserTimeline(username, timelineView)
      .then((data) => setPosts(data.posts || []))
      .catch(() => setPosts([]))
      .finally(() => setTimelineLoading(false))
  }, [username, timelineView, loading])

  const handleFollowToggle = async () => {
    if (!currentUser || followingLoading) return
    setFollowingLoading(true)
    try {
      const result = await toggleFollow(username) as { is_following: boolean }
      setProfile((prev) => prev ? { ...prev, is_following: result.is_following, followers_count: (prev.followers_count || 0) + (result.is_following ? 1 : -1) } : null)
    } catch {
    } finally {
      setFollowingLoading(false)
    }
  }

  const handleFollowersClick = async () => {
    try {
      const data = await getFollowers(username) as { users: Array<{ id: number; username: string; display_name?: string | null; avatar_url: string | null }> }
      setFollowersList(data.users || [])
      setModalType('followers')
    } catch {
      setFollowersList([])
      setModalType('followers')
    }
  }

  const handleFollowingClick = async () => {
    try {
      const data = await getFollowing(username) as { users: Array<{ id: number; username: string; display_name?: string | null; avatar_url: string | null }> }
      setFollowingList(data.users || [])
      setModalType('following')
    } catch {
      setFollowingList([])
      setModalType('following')
    }
  }

  const handleReportClick = () => {
    setReportReason('')
    setReportError('')
    setReportSuccess(false)
    setModalType('report')
  }

  const handleReportSubmit = async () => {
    if (!reportReason) return
    setReportSubmitting(true)
    setReportError('')
    try {
      await reportUser(username, reportReason)
      setReportSuccess(true)
      setTimeout(() => setModalType(null), 1500)
    } catch (err) {
      setReportError(err instanceof Error ? err.message : 'Failed to submit report')
    } finally {
      setReportSubmitting(false)
    }
  }

  const closeModal = () => setModalType(null)

  const handleProfileSaved = async () => {
    // Refresh profile data after save
    try {
      const data = await getProfile(username)
      setProfile(data)
    } catch {
      // Silently fail, profile will show stale data
    }
  }

  const openEditProfile = () => setIsEditingProfile(true)
  const closeEditProfile = () => setIsEditingProfile(false)

  if (isAuthLoading || loading) {
    return (
      <Layout>
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <LoaderCircle size={24} style={{ animation: 'spin 1s linear infinite', color: tokens.colors.textMuted }} />
        </div>
      </Layout>
    )
  }

  if (error || !profile) {
    return (
      <Layout>
        <div style={{ padding: 24, textAlign: 'center', color: tokens.colors.textMuted }}>
          {error || 'Profile not found'}
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
      <div className="profile-page">
        {isOwnProfile && isAdmin && (
          <div style={{ padding: '8px 24px', backgroundColor: tokens.colors.surfaceElevated, borderBottom: `1px solid ${tokens.colors.borderSubtle}` }}>
            <Link href="/admin">
              <button
                style={{
                  padding: '6px 12px',
                  borderRadius: 6,
                  border: `1px solid ${tokens.colors.accent}`,
                  backgroundColor: 'transparent',
                  color: tokens.colors.accent,
                  fontWeight: 600,
                  fontSize: tokens.font.xs,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Shield size={12} />
                Admin panel
              </button>
            </Link>
          </div>
        )}

        <ProfileHeader
          profile={profile}
          isOwnProfile={isOwnProfile}
          isFollowing={profile.is_following || false}
          isAdmin={isAdmin}
          onFollowToggle={handleFollowToggle}
          followingLoading={followingLoading}
          onFollowersClick={handleFollowersClick}
          onFollowingClick={handleFollowingClick}
          onEditProfileClick={openEditProfile}
          onReportClick={!isOwnProfile ? handleReportClick : undefined}
        />

        <div className="profile-tabs" style={{ display: 'flex', borderBottom: `1px solid ${tokens.colors.borderSubtle}` }}>
          {(['posts', 'replies', 'media', 'likes', 'reposts'] as TimelineView[]).map((view) => (
            <TimelineTab
              key={view}
              view={view}
              activeView={timelineView}
              onClick={() => setTimelineView(view)}
            />
          ))}
        </div>

        {timelineLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
            <LoaderCircle size={24} style={{ animation: 'spin 1s linear infinite', color: tokens.colors.textMuted }} />
          </div>
        ) : posts.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: tokens.colors.textMuted }}>
            No posts yet
          </div>
        ) : (
          posts.map((post) => <PostCard key={post.id} post={post} />)
        )}

        {modalType === 'followers' && (
          <FollowersModal
            username={username}
            initialUsers={followersList}
            title={`${profile.followers_count ?? 0} Followers`}
            onClose={closeModal}
          />
        )}

        {modalType === 'following' && (
          <FollowersModal
            username={username}
            initialUsers={followingList}
            title={`${profile.following_count ?? 0} Following`}
            onClose={closeModal}
          />
        )}

        {modalType === 'report' && (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 50,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: 'rgba(0,0,0,0.7)',
            }}
            onClick={closeModal}
          >
            <div
              style={{
                backgroundColor: tokens.colors.surfaceElevated,
                borderRadius: 16,
                width: '90%',
                maxWidth: 400,
                overflow: 'hidden',
                border: `1px solid ${tokens.colors.border}`,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ padding: '16px 20px', borderBottom: `1px solid ${tokens.colors.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: tokens.font.md }}>Report user</span>
                <button onClick={closeModal} style={{ background: 'none', border: 'none', color: tokens.colors.textMuted, cursor: 'pointer', padding: 4 }}>
                  <X size={20} />
                </button>
              </div>
              <div style={{ padding: '20px' }}>
                {reportSuccess ? (
                  <div style={{ textAlign: 'center', padding: '20px 0' }}>
                    <div style={{ color: tokens.colors.success, fontSize: tokens.font.md, fontWeight: 600, marginBottom: 8 }}>Report submitted</div>
                    <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Thank you for helping keep the community safe.</div>
                  </div>
                ) : (
                  <>
                    <p style={{ margin: '0 0 16px 0', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                      Why are you reporting @{username}?
                    </p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {REPORT_REASONS.map((reason) => (
                        <button
                          key={reason.value}
                          onClick={() => setReportReason(reason.value)}
                          style={{
                            padding: '12px 16px',
                            borderRadius: 8,
                            border: `1px solid ${reportReason === reason.value ? tokens.colors.accent : tokens.colors.border}`,
                            backgroundColor: reportReason === reason.value ? 'rgba(201, 169, 108, 0.1)' : 'transparent',
                            color: tokens.colors.textPrimary,
                            fontSize: tokens.font.sm,
                            cursor: 'pointer',
                            textAlign: 'left',
                          }}
                        >
                          {reason.label}
                        </button>
                      ))}
                    </div>
                    {reportError && (
                      <div style={{ marginTop: 12, padding: '10px 14px', borderRadius: 8, border: `1px solid ${tokens.colors.danger}`, color: tokens.colors.danger, fontSize: tokens.font.sm }}>
                        {reportError}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', marginTop: 20 }}>
                      <button
                        onClick={closeModal}
                        disabled={reportSubmitting}
                        style={{
                          padding: '10px 20px',
                          borderRadius: 8,
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: 'transparent',
                          color: tokens.colors.textPrimary,
                          fontWeight: 600,
                          cursor: 'pointer',
                          fontSize: tokens.font.base,
                        }}
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleReportSubmit}
                        disabled={!reportReason || reportSubmitting}
                        style={{
                          padding: '10px 20px',
                          borderRadius: 8,
                          border: 'none',
                          backgroundColor: !reportReason || reportSubmitting ? tokens.colors.surfaceElevated : tokens.colors.danger,
                          color: '#fff',
                          fontWeight: 600,
                          cursor: !reportReason || reportSubmitting ? 'not-allowed' : 'pointer',
                          fontSize: tokens.font.base,
                        }}
                      >
                        {reportSubmitting ? 'Submitting...' : 'Submit report'}
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {isEditingProfile && profile && (
          <EditProfileModal
            profile={profile}
            onClose={closeEditProfile}
            onSave={handleProfileSaved}
          />
        )}
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      ` }} />
    </Layout>
  )
}