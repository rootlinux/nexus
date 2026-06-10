'use client'

import { FormEvent, Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import Layout from '../../components/Layout'
import { SearchPeopleResults, SearchPostResults } from '../../components/SearchResults'
import { getActivationStage, isMemberActivationActive } from '../../lib/activation'
import { searchEverything } from '../../lib/api'
import { useAuth } from '../../contexts/AuthContext'
import { getSearchHref } from '../../lib/routes'
import { tokens } from '../../styles/tokens'
import type { SearchResponse, SearchTab, SearchUserProfile } from '../../types'

const SEARCH_TABS: Array<{ id: SearchTab; label: string }> = [
  { id: 'top', label: 'Posts' },
  { id: 'people', label: 'People' },
]

function getValidTab(value: string | null): SearchTab {
  if (value === 'people') {
    return value
  }
  if (value === 'latest') {
    return 'top'
  }
  return 'top'
}

function createEmptyResponse(query: string, type: SearchTab): SearchResponse {
  return {
    query,
    type,
    posts: [],
    users: [],
  }
}

function SearchPageContent() {
  const router = useRouter()
  const { token, user, isLoading: isAuthLoading, memberActivationState, completeActivationAction } = useAuth()
  const searchParams = useSearchParams()
  const query = (searchParams.get('q') || '').trim()
  const activeTab = getValidTab(searchParams.get('type'))
  const activationActive = isMemberActivationActive(memberActivationState)
  const activationStage = getActivationStage(memberActivationState)

  const [inputValue, setInputValue] = useState(query)
  const [inputFocused, setInputFocused] = useState(false)
  const [result, setResult] = useState<SearchResponse>(createEmptyResponse(query, activeTab))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const currentUsername = user?.username || ''

  useEffect(() => {
    setInputValue(query)
  }, [query])

  useEffect(() => {
    let cancelled = false

    if (isAuthLoading) {
      return
    }

    if (!token) {
      router.push('/auth')
      return
    }

    if (!query) {
      setResult(createEmptyResponse('', activeTab))
      setLoading(false)
      setError('')
      return
    }

    const loadResults = async () => {
      try {
        setLoading(true)
        setError('')
        const data = await searchEverything(query, activeTab)
        if (!cancelled) {
          setResult(data)
          completeActivationAction('ran_search')
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Search is unavailable right now.')
          setResult(createEmptyResponse(query, activeTab))
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadResults()
    return () => {
      cancelled = true
    }
  }, [activeTab, completeActivationAction, isAuthLoading, query, router, token])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    router.push(getSearchHref(inputValue, activeTab))
  }

  function handleTabChange(tab: SearchTab) {
    router.push(getSearchHref(query || inputValue, tab))
  }

  const hasAnyResults = result.posts.length > 0 || result.users.length > 0

  return (
    <Layout>
      <div className="search-page" style={{ minHeight: '100vh', backgroundColor: tokens.colors.bg }}>
        <header
          className="app-sticky-header search-page-header"
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            backdropFilter: 'blur(14px)',
            backgroundColor: 'rgba(10, 10, 10, 0.88)',
            borderBottom: `1px solid #1c1c1c`,
          }}
        >
          <div style={{ padding: '16px 24px' }}>
            <div style={{ color: '#f0f0f0', fontSize: '18px', fontWeight: 500, marginBottom: '12px' }}>Search</div>
            <form onSubmit={handleSubmit}>
              <input
                value={inputValue}
                onChange={(event) => setInputValue(event.target.value)}
                onFocus={() => setInputFocused(true)}
                onBlur={() => setInputFocused(false)}
                placeholder="Search people and posts"
                style={{
                  width: '100%',
                  backgroundColor: '#141414',
                  border: `1px solid ${inputFocused ? '#555' : '#242424'}`,
                  borderRadius: '8px',
                  padding: '10px 14px',
                  color: tokens.colors.textPrimary,
                  fontSize: tokens.font.base,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </form>
          </div>

          <div style={{ display: 'flex', padding: '0 24px' }}>
            {SEARCH_TABS.map((tab) => {
              const isActive = activeTab === tab.id

              return (
                <button
                  key={tab.id}
                  onClick={() => handleTabChange(tab.id)}
                  style={{
                    flex: 1,
                    padding: '0 0 14px',
                    background: 'transparent',
                    border: 'none',
                    borderBottom: isActive ? `2px solid ${tokens.colors.textPrimary}` : '2px solid transparent',
                    color: isActive ? tokens.colors.textPrimary : tokens.colors.textSecondary,
                    fontSize: tokens.font.sm,
                    fontWeight: Number(tokens.font.weightMedium),
                    cursor: 'pointer',
                  }}
                >
                  {tab.label}
                </button>
              )
            })}
          </div>

          {activationActive && !query ? (
            <div style={{
              margin: '0 24px 16px',
              padding: '14px 16px',
              borderRadius: '18px',
              border: `1px solid ${tokens.colors.border}`,
              backgroundColor: tokens.colors.surface,
            }}>
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px' }}>
                {activationStage === 'first_session' ? 'Best way to begin' : 'Pick the thread back up'}
              </div>
              <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.base, fontWeight: Number(tokens.font.weightSemibold), marginBottom: '6px' }}>
                Start with a name, a phrase you remember, or a thread you want back.
              </div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.55 }}>
                Search works best once the network has already given you a clue. If you&apos;re still getting your bearings, Explore is usually the better first stop.
              </div>
            </div>
          ) : null}
        </header>

        {!query ? (
          <div className="search-page-empty" style={{ padding: '48px 24px', textAlign: 'center', color: '#404040', fontSize: '14px', lineHeight: 1.6 }}>
            {activationActive ? 'Search once you have a clue' : 'Start with a name, phrase, or thread'}
          </div>
        ) : loading ? (
          <div style={{ padding: '16px 0' }}>
            <style>{`
              @keyframes shimmer {
                0% { background-position: -400px 0; }
                100% { background-position: 400px 0; }
              }
              .skeleton-shimmer {
                background: linear-gradient(90deg, #141414 25%, #1c1c1c 50%, #141414 75%);
                background-size: 800px 100%;
                animation: shimmer 1.4s infinite linear;
                border-radius: 4px;
              }
            `}</style>
            {[1, 2, 3].map((i) => (
              <div key={i} style={{ padding: '20px 24px', borderBottom: '1px solid #1c1c1c', display: 'flex', gap: '12px' }}>
                <div className="skeleton-shimmer" style={{ width: 44, height: 44, borderRadius: '50%', flexShrink: 0 }} />
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div className="skeleton-shimmer" style={{ width: '40%', height: 14 }} />
                  <div className="skeleton-shimmer" style={{ width: '90%', height: 14 }} />
                  <div className="skeleton-shimmer" style={{ width: '70%', height: 14 }} />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="search-page-feedback" style={{ padding: '32px 24px' }}>
            <div
              style={{
                border: `1px solid ${tokens.colors.border}`,
                borderRadius: '18px',
                padding: '20px',
                backgroundColor: tokens.colors.surface,
              }}
            >
              <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.lg, fontWeight: Number(tokens.font.weightBold), marginBottom: '6px' }}>
                Search is unavailable right now
              </div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                {error}
              </div>
            </div>
          </div>
        ) : !hasAnyResults ? (
          <div className="search-page-empty" style={{ padding: '48px 24px', textAlign: 'center', color: '#404040', fontSize: '14px', lineHeight: 1.6 }}>
            No results for &lsquo;{query}&rsquo;
          </div>
        ) : (
          <>
            {activeTab === 'people' ? (
              <SearchPeopleResults
                users={result.users}
                currentUsername={currentUsername}
                onUsersChange={(nextUsers: SearchUserProfile[]) => setResult((prev) => ({ ...prev, users: nextUsers }))}
              />
            ) : activeTab === 'latest' ? (
              <SearchPostResults posts={result.posts} />
            ) : (
              <>
                {result.users.length > 0 ? (
                  <section>
                    <div
                      style={{
                        padding: '14px 24px',
                        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                        color: tokens.colors.textSecondary,
                        fontSize: tokens.font.xs,
                        fontWeight: Number(tokens.font.weightMedium),
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                      }}
                    >
                      People
                    </div>
                    <SearchPeopleResults
                      users={result.users}
                      currentUsername={currentUsername}
                      onUsersChange={(nextUsers: SearchUserProfile[]) => setResult((prev) => ({ ...prev, users: nextUsers }))}
                    />
                  </section>
                ) : null}

                {result.posts.length > 0 ? (
                  <section>
                    <div
                      style={{
                        padding: '14px 24px',
                        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                        color: tokens.colors.textSecondary,
                        fontSize: tokens.font.xs,
                        fontWeight: Number(tokens.font.weightMedium),
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                      }}
                    >
                      Conversations in view
                    </div>
                    <SearchPostResults posts={result.posts} />
                  </section>
                ) : null}
              </>
            )}
          </>
        )}
      </div>
    </Layout>
  )
}

export default function SearchPage() {
  return (
    <Suspense fallback={<Layout><div style={{ minHeight: '100vh', backgroundColor: tokens.colors.bg, padding: '44px 16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Loading search...</div></Layout>}>
      <SearchPageContent />
    </Suspense>
  )
}
