'use client'

import type { LucideIcon } from 'lucide-react'

export interface LayoutNavItem {
  id: string
  href: string
  label: string
  icon: LucideIcon
  badge?: string
}

export interface LayoutProfileSummary {
  username: string
  displayName: string
  avatarUrl: string | null
}
