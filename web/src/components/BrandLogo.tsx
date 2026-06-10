import { tokens } from '../styles/tokens'

type BrandLogoProps = {
  variant?: 'lockup' | 'mark'
  width?: number
  className?: string
}

export function BrandLogo({
  variant = 'lockup',
  width,
  className,
}: BrandLogoProps) {
  if (variant === 'mark') {
    return (
      <picture className={className}>
        <source
          srcSet="/brand/nexus-mark-on-dark.png"
          media="(prefers-color-scheme: dark)"
        />
        <img
          src="/brand/nexus-mark-on-light.png"
          alt="Nexus mark"
          width={width ?? 40}
          style={{ height: 'auto', display: 'block', maxWidth: '100%' }}
        />
      </picture>
    )
  }

  return (
    <div
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '9px',
        maxWidth: '100%',
      }}
    >
      <picture style={{ display: 'block', flexShrink: 0, maxWidth: '100%' }}>
        <source
          srcSet="/brand/nexus-mark-on-dark.png"
          media="(prefers-color-scheme: dark)"
        />
        <img
          src="/brand/nexus-mark-on-light.png"
          alt="Nexus"
          width={width ?? 28}
          style={{ height: 'auto', display: 'block', maxWidth: '100%' }}
        />
      </picture>
      <span
        style={{
          color: tokens.colors.textPrimary,
          fontWeight: Number(tokens.font.weightBold),
          fontSize: tokens.font.md,
          letterSpacing: '-0.03em',
          lineHeight: 1,
        }}
      >
        Nexus
      </span>
      <span
        style={{
          padding: '2px 6px',
          backgroundColor: tokens.colors.accentMuted,
          color: tokens.colors.accent,
          fontSize: '9px',
          borderRadius: tokens.radius.full,
          fontWeight: Number(tokens.font.weightMedium),
          lineHeight: 1,
          letterSpacing: '0.05em',
          textTransform: 'uppercase',
        }}
      >
        beta
      </span>
    </div>
  )
}
