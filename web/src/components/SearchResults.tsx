'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Bookmark, Heart, MessageCircle, Repeat2 } from 'lucide-react'

import { PostBody, PostCard, PostPreviewLink, formatRelativeTime, getDisplayPost, PostActionRow, PostAvatar, PostContextLine, PostHeader, PostMediaBlock, getPostContext } from './PostSurface'
import { QuotedPostEmbed } from './QuotedPostEmbed'
import { ReplyContext } from './ReplyContext'
import { toggleFollow } from '../lib/api'
import { getPostHref, getProfileHref } from '../lib/routes'
import { tokens } from '../styles/tokens'
import type { Post, SearchUserProfile } from '../types'

function getErrorMessage(error: unknown, fallback: string) {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: unknown }).response === 'object' &&
    (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail === 'string'
  ) {
    return (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || fallback
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return fallback
}

export function SearchPostResults({ posts }: { posts: Post[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {posts.map((post) => {
        const displayPost = getDisplayPost(post)
        const context = getPostContext(post)

        return (
          <PostCard
            key={post.id}
            style={{
              padding: '20px 24px',
              display: 'flex',
              gap: '14px',
            }}
          >
            <Link href={getProfileHref(displayPost.author.username)} style={{ textDecoration: 'none' }}>
              <PostAvatar user={displayPost.author} size={48} />
            </Link>

            <div style={{ flex: 1, minWidth: 0 }}>
              {context ? <PostContextLine icon={context.icon} text={context.text} style={{ marginBottom: '8px' }} /> : null}
              <PostHeader
                author={displayPost.author}
                timestamp={formatRelativeTime(displayPost.created_at)}
                timestampHref={getPostHref(displayPost.id, {
                  entry: 'search',
                  focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                })}
              />

              <PostPreviewLink post={displayPost} entry="search">
                <ReplyContext post={displayPost} entry="search" />
                {displayPost.content ? (
                  <PostBody style={{ marginBottom: 0 }}>
                    {displayPost.content}
                  </PostBody>
                ) : null}
              </PostPreviewLink>
              <PostMediaBlock postId={displayPost.id} mediaUrl={displayPost.media_url} maxHeight={380} />

              {displayPost.quoted_post || displayPost.quoted_post_unavailable ? (
                <QuotedPostEmbed
                  post={displayPost.quoted_post}
                  unavailable={displayPost.quoted_post_unavailable}
                  placeholder={displayPost.quoted_post_placeholder}
                />
              ) : null}

              <PostActionRow
                items={[
                  {
                    icon: MessageCircle,
                    label: 'Reply',
                    count: displayPost.replies_count,
                    href: getPostHref(displayPost.id, {
                      entry: 'search',
                      focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                    }),
                  },
                  { icon: Repeat2, label: 'Repost', count: displayPost.reposts_count },
                  { icon: Heart, label: 'Like', count: displayPost.likes_count },
                  {
                    icon: Bookmark,
                    label: 'Bookmark',
                    alwaysShowLabel: true,
                    href: getPostHref(displayPost.id, {
                      entry: 'search',
                      focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                    }),
                  },
                ]}
              />
            </div>
          </PostCard>
        )
      })}
    </div>
  )
}

export function SearchPeopleResults({
  users,
  currentUsername,
  onUsersChange,
}: {
  users: SearchUserProfile[]
  currentUsername: string
  onUsersChange: (nextUsers: SearchUserProfile[]) => void
}) {
  const [pendingUsername, setPendingUsername] = useState<string | null>(null)
  const [errorByUsername, setErrorByUsername] = useState<Record<string, string>>({})

  async function handleFollow(username: string) {
    try {
      setErrorByUsername((prev) => ({ ...prev, [username]: '' }))
      setPendingUsername(username)
      const data = await toggleFollow(username)
      onUsersChange(
        users.map((user) =>
          user.username === username
            ? {
                ...user,
                is_following: data.following,
                followers_count: data.followers_count,
                following_count: data.following_count,
              }
            : user
        )
      )
    } catch (error: unknown) {
      setErrorByUsername((prev) => ({
        ...prev,
        [username]: getErrorMessage(error, 'Could not update follow status.'),
      }))
    } finally {
      setPendingUsername(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '12px 16px' }}>
      {users.map((user) => {
        const isSelf = user.username === currentUsername

        return (
          <article
            key={user.id}
            style={{
              backgroundColor: '#141414',
              border: '1px solid #242424',
              borderRadius: '10px',
              padding: '14px 16px',
              display: 'flex',
              gap: '12px',
              alignItems: 'flex-start',
            }}
          >
            <Link href={getProfileHref(user.username)} style={{ textDecoration: 'none' }}>
              <PostAvatar user={user} size={40} />
            </Link>

            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <Link
                    href={getProfileHref(user.username)}
                    style={{
                      display: 'inline-block',
                      color: '#f0f0f0',
                      fontSize: tokens.font.base,
                      fontWeight: Number(tokens.font.weightMedium),
                      textDecoration: 'none',
                    }}
                  >
                    {user.display_name || user.username}
                  </Link>
                  <div style={{ color: '#555', fontSize: tokens.font.sm }}>
                    @{user.username}
                  </div>
                </div>

                {isSelf ? (
                  <div
                    className="btn-ghost"
                    style={{
                      padding: '8px 12px',
                      borderRadius: tokens.radius.full,
                      fontSize: tokens.font.xs,
                      fontWeight: Number(tokens.font.weightSemibold),
                      cursor: 'default',
                    }}
                  >
                    You
                  </div>
                ) : (
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => void handleFollow(user.username)}
                    disabled={pendingUsername === user.username}
                    style={{
                      borderRadius: tokens.radius.full,
                      color: tokens.colors.textPrimary,
                      padding: '8px 14px',
                      fontSize: tokens.font.xs,
                      fontWeight: Number(tokens.font.weightSemibold),
                      flexShrink: 0,
                    }}
                  >
                    {pendingUsername === user.username ? '...' : user.is_following ? 'Following' : 'Follow'}
                  </button>
                )}
              </div>

              {user.bio ? (
                <div style={{ marginTop: '8px', color: '#666', fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                  {user.bio}
                </div>
              ) : null}

              <div style={{ marginTop: '10px', color: tokens.colors.textMuted, fontSize: tokens.font.xs }}>
                {user.followers_count || 0} followers · following {user.following_count || 0}
              </div>

              {errorByUsername[user.username] ? (
                <div style={{ marginTop: '8px', color: tokens.colors.danger, fontSize: tokens.font.xs }}>
                  {errorByUsername[user.username]}
                </div>
              ) : null}
            </div>
          </article>
        )
      })}
    </div>
  )
}
