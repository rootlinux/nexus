'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { LoaderCircle, MessageCircle, PencilLine, SendHorizonal, X } from 'lucide-react'

import Layout from '../../components/Layout'
import { useAuth } from '../../contexts/AuthContext'
import { getConversations, getMessages, searchUsers, sendMessage } from '../../lib/api'
import type { Conversation as ApiConversation, Message as ApiMessage } from '../../lib/api'
import { resolveMediaUrl } from '../../lib/media'
import { getProfileHref } from '../../lib/routes'
import { tokens, getAvatarColor } from '../../styles/tokens'

interface User {
  id: number
  username: string
  display_name?: string | null
  avatar_url?: string | null
}

type Conversation = ApiConversation

type Message = ApiMessage

function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null) {
    const maybeResponse = (error as { response?: { data?: { detail?: string; message?: string } } }).response
    if (typeof maybeResponse?.data?.detail === 'string') {
      return maybeResponse.data.detail
    }
    if (typeof maybeResponse?.data?.message === 'string') {
      return maybeResponse.data.message
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message
  }

  return fallback
}

function MessagesEmptyState({
  title,
  body,
  variant = 'thread',
}: {
  title: string
  body: string
  variant?: 'sidebar' | 'thread' | 'placeholder'
}) {
  return (
    <div className={`messages-empty-state messages-empty-state--${variant}`}>
      <div className="messages-empty-state__inner">
        <div className="messages-empty-state__icon" aria-hidden="true">
          <MessageCircle size={variant === 'sidebar' ? 18 : 20} />
        </div>
        <div className="messages-empty-state__title">{title}</div>
        <div className="messages-empty-state__body">{body}</div>
      </div>
    </div>
  )
}

function MessagesPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { token, user, isLoading: isAuthLoading } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedUser, setSelectedUser] = useState<string | null>(null)
  const [selectedUserProfile, setSelectedUserProfile] = useState<User | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [newMessage, setNewMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [threadLoading, setThreadLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [currentUser, setCurrentUser] = useState<{ username: string } | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const [showNewMessageModal, setShowNewMessageModal] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<User[]>([])
  const [searching, setSearching] = useState(false)
  const [searchTimeout, setSearchTimeout] = useState<ReturnType<typeof setTimeout> | null>(null)

  const [listError, setListError] = useState('')
  const [threadError, setThreadError] = useState('')
  const [composerError, setComposerError] = useState('')

  useEffect(() => {
    if (isAuthLoading) {
      return
    }

    if (!token) {
      router.push('/auth')
      return
    }

    setCurrentUser(user ? { username: user.username } : null)

    void fetchConversations()
  }, [isAuthLoading, router, token, user])

  useEffect(() => {
    const threadUsername = searchParams.get('with')
    setSelectedUser(threadUsername)
    if (!threadUsername) {
      setSelectedUserProfile(null)
      setMessages([])
      setThreadError('')
      setComposerError('')
    }
  }, [searchParams])

  useEffect(() => {
    if (!selectedUser) {
      return
    }

    const matchingConversation = conversations.find((conversation) => conversation.user.username === selectedUser)
    if (matchingConversation) {
      setSelectedUserProfile(matchingConversation.user)
    }
  }, [conversations, selectedUser])

  useEffect(() => {
    if (!selectedUser) {
      return
    }

    void fetchMessages(selectedUser)
  }, [selectedUser])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    return () => {
      if (searchTimeout) {
        clearTimeout(searchTimeout)
      }
    }
  }, [searchTimeout])

  async function fetchConversations() {
    try {
      setLoading(true)
      setListError('')
      const data = await getConversations()
      setConversations(data)
    } catch (error) {
      setConversations([])
      setListError(getErrorMessage(error, 'Could not load conversations.'))
    } finally {
      setLoading(false)
    }
  }

  async function fetchMessages(username: string) {
    try {
      setThreadLoading(true)
      setThreadError('')
      setComposerError('')
      const data = await getMessages(username)
      setMessages(data.messages || [])
    } catch (error) {
      setMessages([])
      setThreadError(getErrorMessage(error, 'Could not load messages.'))
    } finally {
      setThreadLoading(false)
    }
  }

  function openThread(user: User) {
    setSelectedUserProfile(user)
    setShowNewMessageModal(false)
    setSearchQuery('')
    setSearchResults([])
    setThreadError('')
    setComposerError('')
    router.replace(`/messages?with=${encodeURIComponent(user.username)}`)
  }

  async function handleSendMessage() {
    if (!selectedUser) {
      return
    }

    const trimmedMessage = newMessage.trim()
    if (!trimmedMessage) {
      setComposerError('Write a message before sending.')
      return
    }

    setSending(true)
    try {
      setComposerError('')
      const message = await sendMessage(selectedUser, trimmedMessage)
      setMessages((previous) => [...previous, message])
      setNewMessage('')
      await fetchConversations()
    } catch (error) {
      setComposerError(getErrorMessage(error, 'Could not send this message.'))
    } finally {
      setSending(false)
    }
  }

  function formatTime(dateStr: string | null) {
    if (!dateStr) return ''

    const date = new Date(dateStr)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const days = Math.floor(diff / (1000 * 60 * 60 * 24))

    if (days === 0) {
      return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
    }
    if (days === 1) {
      return 'Yesterday'
    }
    if (days < 7) {
      return date.toLocaleDateString('en-US', { weekday: 'short' })
    }

    return date.toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
  }

  function handleSearchChange(e: React.ChangeEvent<HTMLInputElement>) {
    const query = e.target.value
    setSearchQuery(query)

    if (searchTimeout) {
      clearTimeout(searchTimeout)
    }

    if (!query.trim()) {
      setSearchResults([])
      return
    }

    const timeout = setTimeout(async () => {
      setSearching(true)
      try {
        const data = await searchUsers(query.trim())
        setSearchResults(data.users || [])
      } catch (error) {
        setSearchResults([])
        setListError(getErrorMessage(error, 'Could not search right now.'))
      } finally {
        setSearching(false)
      }
    }, 300)

    setSearchTimeout(timeout)
  }

  function Avatar({ user, size = 40 }: { user: Pick<User, 'username' | 'avatar_url'>; size?: number }) {
    const avatarUrl = resolveMediaUrl(user.avatar_url)
    const initial = user.username?.charAt(0)?.toUpperCase() || '?'

    return (
      <div
        style={{
          width: `${size}px`,
          height: `${size}px`,
          borderRadius: '50%',
          backgroundColor: getAvatarColor(user.username || 'x'),
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: tokens.colors.textPrimary,
          fontWeight: Number(tokens.font.weightBold),
          fontSize: size > 35 ? tokens.font.md : tokens.font.sm,
          flexShrink: 0,
          overflow: 'hidden',
        }}
      >
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt={user.username}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          initial
        )}
      </div>
    )
  }

  const threadTitle = selectedUserProfile?.display_name || selectedUserProfile?.username || selectedUser || 'Conversation'
  const interactionsDisabled = /frozen|suspended|banned|not permitted/i.test(listError)
  const composerDisabled = sending || interactionsDisabled

  const pageContent = (
    <div
      className="messages-shell"
      data-has-thread={selectedUser ? 'true' : 'false'}
      style={{
        display: 'flex',
        minHeight: '100vh',
        backgroundColor: tokens.colors.bg,
      }}
    >
      {/* Left panel */}
      <div
        className="messages-sidebar"
        style={{
          width: '280px',
          display: 'flex',
          flexDirection: 'column',
          borderRight: `1px solid ${tokens.colors.borderSubtle}`,
          backgroundColor: tokens.colors.bg,
        }}
      >
        <div
          className="messages-sidebar-header"
          style={{
            padding: '16px',
            borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            position: 'sticky',
            top: 0,
            backgroundColor: tokens.colors.bg,
            zIndex: 1,
          }}
        >
          <span style={{ color: tokens.colors.textPrimary, fontSize: '16px', fontWeight: 500 }}>Messages</span>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setShowNewMessageModal(true)}
            aria-label="New message"
            style={{
              color: tokens.colors.textSecondary,
              padding: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <PencilLine size={18} />
          </button>
        </div>

        {listError ? (
          <div
            style={{
              margin: '12px',
              backgroundColor: `${tokens.colors.danger}12`,
              border: `1px solid ${tokens.colors.danger}`,
              borderRadius: '8px',
              color: tokens.colors.danger,
              padding: '10px 12px',
              fontSize: '13px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '12px',
            }}
          >
            <span>{listError}</span>
            <button
              onClick={() => setListError('')}
              style={{
                background: 'none',
                border: 'none',
                color: tokens.colors.danger,
                cursor: 'pointer',
                fontSize: '18px',
                padding: '2px',
              }}
            >
              ×
            </button>
          </div>
        ) : null}

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading ? (
            <div
              style={{
                padding: '40px 16px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px',
                color: tokens.colors.textSecondary,
                fontSize: '13px',
              }}
            >
              <LoaderCircle size={16} className="messages-spin" />
              Loading conversations…
            </div>
          ) : conversations.length === 0 ? (
            <MessagesEmptyState
              variant="sidebar"
              title="No conversations yet"
              body="Start a conversation when you&apos;re ready."
            />
          ) : (
            conversations.map((conversation) => {
              const isSelected = selectedUser === conversation.user.username
              const preview = conversation.last_message || 'No messages yet'
              const displayName = conversation.user.display_name || conversation.user.username

              return (
                <div
                  key={conversation.user.id}
                  onClick={() => openThread(conversation.user)}
                  style={{
                    padding: '14px 16px',
                    borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                    cursor: 'pointer',
                    backgroundColor: isSelected ? tokens.colors.surface : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                  }}
                  onMouseEnter={(event) => {
                    if (!isSelected) {
                      event.currentTarget.style.backgroundColor = tokens.colors.surface
                    }
                  }}
                  onMouseLeave={(event) => {
                    if (!isSelected) {
                      event.currentTarget.style.backgroundColor = 'transparent'
                    }
                  }}
                >
                  <Avatar user={conversation.user} size={36} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '2px',
                        gap: '8px',
                      }}
                    >
                      <span
                        style={{
                          color: tokens.colors.textPrimary,
                          fontSize: '14px',
                          fontWeight: conversation.unread_count > 0 ? 600 : 400,
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {displayName}
                      </span>
                      <span style={{ color: tokens.colors.textMuted, fontSize: '11px', flexShrink: 0 }}>
                        {formatTime(conversation.updated_at || null)}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: '13px',
                        color: tokens.colors.textSecondary,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {preview}
                    </div>
                  </div>
                  {conversation.unread_count > 0 ? (
                    <span
                      aria-label={`${conversation.unread_count} unread messages`}
                      style={{
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        backgroundColor: tokens.colors.textPrimary,
                        flexShrink: 0,
                      }}
                    />
                  ) : null}
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Right panel */}
      <div
        className="messages-thread"
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: tokens.colors.bg,
        }}
      >
        {selectedUser ? (
          <>
            <div
              className="messages-thread-header"
              style={{
                padding: '16px 20px',
                borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                position: 'sticky',
                top: 0,
                backgroundColor: tokens.colors.bg,
                zIndex: 1,
              }}
            >
              <button
                type="button"
                className="btn-ghost messages-mobile-back"
                onClick={() => router.replace('/messages')}
                aria-label="Back to conversations"
                style={{
                  width: '36px',
                  height: '36px',
                  padding: 0,
                  borderRadius: tokens.radius.full,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <X size={16} />
              </button>
              <Link href={getProfileHref(selectedUser)} style={{ textDecoration: 'none' }}>
                <Avatar
                  user={{
                    username: selectedUserProfile?.username || selectedUser,
                    avatar_url: selectedUserProfile?.avatar_url,
                  }}
                />
              </Link>
              <div style={{ minWidth: 0 }}>
                <Link
                  href={getProfileHref(selectedUser)}
                  style={{
                    display: 'block',
                    color: tokens.colors.textPrimary,
                    fontWeight: 500,
                    fontSize: '14px',
                    textDecoration: 'none',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {threadTitle}
                </Link>
                <div style={{ color: tokens.colors.textSecondary, fontSize: '13px' }}>@{selectedUser}</div>
              </div>
            </div>

            {threadError ? (
              <div
                style={{
                  margin: '12px',
                  border: `1px solid ${tokens.colors.danger}`,
                  borderRadius: '8px',
                  backgroundColor: `${tokens.colors.danger}12`,
                  color: tokens.colors.danger,
                  padding: '10px 12px',
                  fontSize: '13px',
                }}
              >
                {threadError}
              </div>
            ) : null}

            <div
              className="messages-thread-stream"
              style={{
                flex: 1,
                overflowY: 'auto',
                padding: '20px',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
              }}
            >
              {threadLoading ? (
                <div style={{ color: tokens.colors.textSecondary, textAlign: 'center', paddingTop: '32px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px', fontSize: '13px' }}>
                  <LoaderCircle size={16} className="messages-spin" />
                  Loading messages…
                </div>
              ) : messages.length === 0 ? (
                <MessagesEmptyState
                  variant="thread"
                  title="No messages yet"
                  body="Start the conversation when you&apos;re ready."
                />
              ) : (
                messages.map((message) => {
                  const isOwn = message.sender?.username === currentUser?.username
                  return (
                    <div
                      key={message.id}
                      className={`messages-bubble-wrap ${isOwn ? 'is-own' : 'is-other'}`}
                      style={{
                        alignSelf: isOwn ? 'flex-end' : 'flex-start',
                        maxWidth: '72%',
                      }}
                    >
                      <div
                        className={`messages-bubble ${isOwn ? 'is-own' : 'is-other'}`}
                        style={{
                          padding: '10px 14px',
                          borderRadius: isOwn ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                          backgroundColor: isOwn ? tokens.colors.surfaceElevated : tokens.colors.surface,
                          color: isOwn ? tokens.colors.textPrimary : tokens.colors.textSecondary,
                          fontSize: '14px',
                          lineHeight: 1.5,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                        }}
                      >
                        {message.content}
                      </div>
                      <div
                        style={{
                          fontSize: '11px',
                          color: tokens.colors.textMuted,
                          marginTop: '4px',
                          textAlign: isOwn ? 'right' : 'left',
                          padding: '0 4px',
                        }}
                      >
                        {new Date(message.created_at).toLocaleTimeString('en-US', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </div>
                    </div>
                  )
                })
              )}
              <div ref={messagesEndRef} />
            </div>

            <div
              className="messages-composer-shell messages-composer"
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                padding: '12px 16px',
                borderTop: `1px solid ${tokens.colors.borderSubtle}`,
                backgroundColor: tokens.colors.surface,
              }}
            >
              {composerError ? (
                <div
                  style={{
                    color: tokens.colors.danger,
                    fontSize: '13px',
                    padding: '8px 10px',
                    borderRadius: '8px',
                    border: `1px solid ${tokens.colors.danger}`,
                    backgroundColor: `${tokens.colors.danger}10`,
                  }}
                >
                  {composerError}
                </div>
              ) : null}
              <div
                className="messages-composer-row"
                style={{
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'center',
                }}
              >
                <input
                  type="text"
                  value={newMessage}
                  onChange={(event) => {
                    setNewMessage(event.target.value)
                    if (composerError) {
                      setComposerError('')
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      void handleSendMessage()
                    }
                  }}
                  placeholder="Write a message"
                  disabled={composerDisabled}
                  style={{
                    flex: 1,
                    padding: '10px 12px',
                    border: `1px solid ${composerError ? tokens.colors.danger : tokens.colors.border}`,
                    borderRadius: '8px',
                    fontSize: '14px',
                    backgroundColor: tokens.colors.bg,
                    color: tokens.colors.textPrimary,
                    outline: 'none',
                  }}
                />
                <button
                  className="messages-send-button btn-ghost"
                  onClick={() => void handleSendMessage()}
                  disabled={sending || interactionsDisabled}
                  style={{
                    color: sending ? tokens.colors.textMuted : tokens.colors.textSecondary,
                    cursor: composerDisabled ? 'not-allowed' : 'pointer',
                    padding: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    opacity: composerDisabled ? 0.5 : 1,
                  }}
                >
                  {sending ? (
                    <LoaderCircle size={18} className="messages-spin" />
                  ) : (
                    <SendHorizonal size={18} />
                  )}
                </button>
              </div>
            </div>
          </>
        ) : (
          <MessagesEmptyState
            variant="placeholder"
            title="Select a conversation"
            body="Open a thread from the left to read and continue it."
          />
        )}
      </div>
    </div>
  )

  const newMessageModal = showNewMessageModal ? (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(10, 10, 10, 0.74)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={() => setShowNewMessageModal(false)}
    >
      <div
        style={{
          backgroundColor: tokens.colors.bg,
          border: `1px solid ${tokens.colors.border}`,
          borderRadius: '12px',
          maxWidth: '480px',
          width: '90%',
          maxHeight: '70vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          style={{
            padding: '16px',
            borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span style={{ fontSize: '15px', fontWeight: 500, color: tokens.colors.textPrimary }}>
            Start conversation
          </span>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setShowNewMessageModal(false)}
            style={{
              padding: '4px',
              color: tokens.colors.textSecondary,
              display: 'flex',
            }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: '12px 16px', borderBottom: `1px solid ${tokens.colors.borderSubtle}` }}>
          <input
            type="text"
            value={searchQuery}
            onChange={handleSearchChange}
            placeholder="Search by name or username"
            autoFocus
            style={{
              width: '100%',
              padding: '10px 12px',
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: '8px',
              fontSize: '14px',
              backgroundColor: tokens.colors.surface,
              color: tokens.colors.textPrimary,
              outline: 'none',
            }}
          />
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {searching ? (
            <div style={{ padding: '24px', textAlign: 'center', color: tokens.colors.textSecondary, fontSize: '13px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
              <LoaderCircle size={16} className="messages-spin" />
              Searching…
            </div>
          ) : searchResults.length === 0 && searchQuery ? (
            <div style={{ padding: '24px', textAlign: 'center', color: tokens.colors.textSecondary, fontSize: '13px' }}>
              <div style={{ color: tokens.colors.textPrimary, fontWeight: 500, marginBottom: '4px' }}>No people found</div>
              <div>Try a different name or username.</div>
            </div>
          ) : (
            searchResults.map((user) => (
              <div
                key={user.id}
                onClick={() => openThread(user)}
                style={{
                  padding: '12px 16px',
                  borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                }}
                onMouseEnter={(event) => {
                  event.currentTarget.style.backgroundColor = tokens.colors.surface
                }}
                onMouseLeave={(event) => {
                  event.currentTarget.style.backgroundColor = 'transparent'
                }}
              >
                <Avatar user={user} size={36} />
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      color: tokens.colors.textPrimary,
                      fontSize: '14px',
                      fontWeight: 500,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {user.display_name || user.username}
                  </div>
                  <div style={{ color: tokens.colors.textSecondary, fontSize: '12px' }}>@{user.username}</div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  ) : null

  return (
    <Layout>
      {pageContent}
      {newMessageModal}
      <style jsx global>{`
        .messages-spin {
          animation: messages-spin 0.9s linear infinite;
        }

        @keyframes messages-spin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }

        @media (max-width: 720px) {
          .messages-sidebar {
            width: 100% !important;
            border-right: none !important;
            border-bottom: 1px solid ${tokens.colors.borderSubtle} !important;
          }

          .messages-thread {
            min-height: 60vh !important;
          }

          .messages-thread-stream {
            padding: 16px !important;
          }

          .messages-bubble-wrap {
            max-width: 100% !important;
          }

          .messages-bubble {
            max-width: min(100%, 320px);
          }

          .messages-composer-shell {
            position: sticky;
            bottom: 0;
            z-index: 2;
          }

          .messages-composer-row {
            flex-direction: row !important;
          }

          .messages-send-button {
            flex-shrink: 0;
          }
        }
      `}</style>
    </Layout>
  )
}

export default function MessagesPage() {
  return (
    <Suspense
      fallback={
        <Layout>
          <div style={{ padding: '32px 16px', color: tokens.colors.textSecondary }}>Loading messages...</div>
        </Layout>
      }
    >
      <MessagesPageContent />
    </Suspense>
  )
}
