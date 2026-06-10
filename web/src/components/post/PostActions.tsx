'use client'

import { useState } from 'react'
import type { CSSProperties, MouseEvent } from 'react'
import Link from 'next/link'
import type { LucideIcon } from 'lucide-react'

import { tokens } from '../../styles/tokens'

export type PostActionItem = {
  icon: LucideIcon
  label: string
  count?: number
  active?: boolean
  activeColor?: string
  onClick?: (event: MouseEvent<HTMLElement>) => void
  href?: string
  alwaysShowLabel?: boolean
}

function PostActionControl({
  icon: Icon,
  label,
  count = 0,
  active = false,
  activeColor,
  onClick,
  href,
  alwaysShowLabel = false,
}: PostActionItem) {
  const [hovered, setHovered] = useState(false)

  const color = active
    ? (activeColor ?? tokens.colors.textPrimary)
    : hovered
      ? tokens.colors.textPrimary
      : tokens.colors.textSecondary

  const countLabel = count > 0 ? (count >= 1000 ? `${(count / 1000).toFixed(1)}K` : String(count)) : ''
  const text = alwaysShowLabel ? label : countLabel

  const content = (
    <>
      <Icon
        size={15}
        strokeWidth={1.75}
        fill={active && (label === 'Like' || label === 'Bookmark') ? color : 'none'}
      />
      {text ? <span>{text}</span> : null}
    </>
  )

  const sharedStyle: CSSProperties = {
    background: 'none',
    border: 'none',
    color,
    cursor: onClick || href ? 'pointer' : 'default',
    padding: 0,
    display: 'inline-flex',
    gap: '5px',
    alignItems: 'center',
    fontSize: tokens.font.sm,
    textDecoration: 'none',
    minHeight: '20px',
    transition: tokens.transition.fast,
    borderRadius: tokens.radius.sm,
  }

  const hoverHandlers = {
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => setHovered(false),
  }

  if (href) {
    return (
      <Link href={href} aria-label={label} style={sharedStyle} {...hoverHandlers}>
        {content}
      </Link>
    )
  }

  if (onClick) {
    return (
      <button type="button" onClick={onClick} aria-label={label} style={sharedStyle} {...hoverHandlers}>
        {content}
      </button>
    )
  }

  return (
    <div aria-label={label} style={sharedStyle} {...hoverHandlers}>
      {content}
    </div>
  )
}

export function PostActionRow({ items }: { items: PostActionItem[] }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: '24px',
        marginTop: '14px',
        color: tokens.colors.textSecondary,
        flexWrap: 'wrap',
      }}
    >
      {items.map((item) => (
        <PostActionControl key={item.label} {...item} />
      ))}
    </div>
  )
}
