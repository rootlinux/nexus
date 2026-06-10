'use client'

import { startTransition, useEffect, useState } from 'react'
import type { ReadonlyURLSearchParams } from 'next/navigation'

export function useCapturedToken(searchParams: ReadonlyURLSearchParams): string | null {
  const [token, setToken] = useState<string | null>(() => searchParams.get('token'))
  const tokenFromUrl = searchParams.get('token')

  useEffect(() => {
    if (!tokenFromUrl) {
      return
    }

    if (token !== tokenFromUrl) {
      startTransition(() => {
        setToken(tokenFromUrl)
      })
      return
    }

    window.history.replaceState({}, '', window.location.pathname)
  }, [token, tokenFromUrl])

  return token
}
