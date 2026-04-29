# Frontend — Alan Notu

## Tech Stack
- Next.js App Router (TypeScript)
- Tailwind CSS
- PWA (service worker + manifest)

## Sayfa Yapısı
| Route | Sayfa |
|-------|-------|
| `/` | Ana akış (Composer + Feed) |
| `/@[username]` / `/u/[username]` | Profil |
| `/post/[id]` | Post detayı + reply zinciri |
| `/notifications` | Bildirimler |
| `/messages` | DM |
| `/search` | Arama |
| `/explore` | Keşfet |
| `/discover` | Giriş yapmamış keşif |
| `/bookmarks` | Kaydedilenler |
| `/invites` | Davetlerim |
| `/security` | WebAuthn yönetimi |
| `/admin` | Admin paneli |
| `/auth/*` | Giriş, kayıt, doğrulama, şifre sıfırlama |
| `/waitlist` | Waitlist başvurusu |
| `/compose/quote/[id]` | Alıntı post oluşturma |

## Önemli Bileşenler
- `BrandLogo.tsx` — sidebar logo, width=72
- `PwaBoot.tsx` — requestAnimationFrame + dedupe (icon cache riski var)
- `Sidebar.tsx` — ana navigasyon
- `sw.js` — service worker (push + notificationclick)

## Açık Sorunlar
- `sw.js` cache adı: `"lukeyz-shell"` → `"nexus-shell"` olmalı (TODO)
- PWA installed icon cache riski `PwaBoot.tsx`'te (düşük öncelik)
