'use client'

import { useState } from 'react'
import { Search } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { useAuth } from '../../contexts/AuthContext'
import { isMemberActivationActive } from '../../lib/activation'
import { getSearchHref } from '../../lib/routes'
import { tokens } from '../../styles/tokens'

export function SearchSection() {
  const [focused, setFocused] = useState(false)
  const [query, setQuery] = useState('')
  const router = useRouter()
  const { memberActivationState } = useAuth()
  const activationActive = isMemberActivationActive(memberActivationState)

  return (
    <div style={{ marginBottom: '20px' }}>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          router.push(getSearchHref(query))
          setFocused(false)
        }}
        style={{ margin: 0 }}
      >
        <div
          style={{
            backgroundColor: tokens.colors.surface,
            border: `1px solid ${focused ? tokens.colors.accent : tokens.colors.border}`,
            borderRadius: tokens.radius.md,
            padding: '10px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            transition: tokens.transition.fast,
          }}
        >
          <Search size={15} strokeWidth={1.75} style={{ color: tokens.colors.textMuted, flexShrink: 0 }} />
          <input
            type="text"
            value={query}
            placeholder={activationActive ? 'Search a name, phrase, or thread' : 'Search Nexus'}
            onFocus={() => setFocused(true)}
            onBlur={() => window.setTimeout(() => setFocused(false), 120)}
            onChange={(event) => setQuery(event.target.value)}
            style={{
              width: '100%',
              background: 'transparent',
              border: 'none',
              color: tokens.colors.textPrimary,
              fontSize: tokens.font.sm,
              outline: 'none',
              caretColor: tokens.colors.accent,
            }}
          />
        </div>
      </form>
    </div>
  )
}
