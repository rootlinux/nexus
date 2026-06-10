import { tokens } from '../../styles/tokens'

export default function DiscoverLoading() {
  return (
    <div style={{ minHeight: '100vh', backgroundColor: tokens.colors.bg }}>
      {/* Header skeleton */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: tokens.colors.bg,
        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
        padding: '16px 24px 12px',
      }}>
        <div style={{ width: '120px', height: '20px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface, marginBottom: '6px' }} />
        <div style={{ width: '200px', height: '14px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface, marginBottom: '12px' }} />
        <div style={{ height: '42px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
      </div>

      {/* People section skeleton */}
      <div style={{ padding: '20px 16px 0' }}>
        <div style={{ width: '200px', height: '16px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface, marginBottom: '12px' }} />
        <div style={{ display: 'flex', gap: '10px', overflowX: 'hidden' }}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              style={{
                flexShrink: 0,
                width: '140px',
                padding: '14px',
                borderRadius: tokens.radius.lg,
                border: `1px solid ${tokens.colors.border}`,
                backgroundColor: tokens.colors.surface,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: tokens.colors.surfaceElevated }} />
              <div style={{ width: '80px', height: '13px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surfaceElevated }} />
              <div style={{ width: '60px', height: '11px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surfaceElevated }} />
              <div style={{ width: '100%', height: '30px', borderRadius: tokens.radius.full, backgroundColor: tokens.colors.surfaceElevated, marginTop: '4px' }} />
            </div>
          ))}
        </div>
      </div>

      {/* Posts section skeleton */}
      <div style={{ padding: '24px 16px 0' }}>
        <div style={{ width: '140px', height: '16px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface, marginBottom: '12px' }} />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} style={{
            borderBottom: `1px solid ${tokens.colors.border}`,
            padding: '18px 0',
            display: 'flex',
            gap: '14px',
          }}>
            <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: tokens.colors.surface, flexShrink: 0 }} />
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ width: '140px', height: '14px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
              <div style={{ width: '100%', height: '13px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
              <div style={{ width: '75%', height: '13px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
