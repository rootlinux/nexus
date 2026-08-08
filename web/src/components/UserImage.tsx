import type { ImgHTMLAttributes } from 'react'

/**
 * Renders user-supplied media (avatars, covers, post images, local upload previews).
 *
 * This is the project's single, deliberate exception to `@next/next/no-img-element`, kept
 * in one component rather than scattered as inline disables — and emphatically not turned
 * off globally, so a genuinely optimisable `<img>` elsewhere still gets flagged.
 *
 * Why these cannot go through `next/image`:
 *
 * 1. **The optimiser fetches the URL server-side.** `resolveMediaUrl()` passes through any
 *    absolute `http(s)` URL the API returns, so the host is influenced by stored data, not
 *    by us. Permitting that through `images.remotePatterns` means either enumerating every
 *    possible media host or opening a `https://**` wildcard — the latter turns the image
 *    endpoint into a server-side fetcher for attacker-influenceable URLs. Declining to
 *    optimise is the cheaper answer than defending an SSRF surface for an avatar.
 * 2. **Upload previews are `blob:` object URLs.** They exist only in the browser tab that
 *    created them; there is nothing for a server-side optimiser to fetch at all.
 *
 * Static, first-party art (brand marks, illustrations) is *not* user media — use
 * `next/image` for those.
 */
type UserImageProps = ImgHTMLAttributes<HTMLImageElement> & {
  /** Required, unlike the DOM default: pass `""` for purely decorative media. */
  alt: string
}

export function UserImage({ alt, ...rest }: UserImageProps) {
  // eslint-disable-next-line @next/next/no-img-element -- see the component docblock above
  return <img alt={alt} {...rest} />
}
