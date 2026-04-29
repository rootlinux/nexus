# Nexus

Invite-only sosyal ağ platformu. Eski adı: Lukeyz.

## Domains

| Servis | Domain |
|--------|--------|
| Web (Next.js) | linusx.xyz |
| API (FastAPI) | api.linusx.xyz |
| Mail (Resend) | mail.linusx.xyz |

## Tech Stack

- **Backend:** FastAPI + PostgreSQL + Alembic (migrations)
- **Frontend:** Next.js App Router
- **Auth:** JWT + refresh token + WebAuthn
- **Mail:** Resend
- **Infra:** Docker Compose + Caddy + Cloudflare
- **VPS:** 173.212.227.3

## Dizin Yapısı

```
/
├── backend/
│   ├── app/
│   │   ├── core/config.py          # Tüm env config buradan
│   │   ├── models/
│   │   │   └── push_subscription.py
│   │   ├── routes/
│   │   │   ├── auth.py
│   │   │   └── notifications.py
│   │   ├── services/
│   │   │   ├── mail.py             # ResendMailSender
│   │   │   └── push_notifications.py
│   │   └── alembic/
│   │       └── versions/           # Migration dosyaları
├── web/
│   ├── src/app/
│   │   ├── layout.tsx
│   │   ├── manifest.ts
│   │   └── notifications/page.tsx
│   ├── src/components/
│   │   ├── BrandLogo.tsx           # sidebar logo, width=72
│   │   ├── Sidebar.tsx
│   │   └── PwaBoot.tsx             # requestAnimationFrame + dedupe
│   └── public/
│       ├── sw.js                   # Service worker (push + notificationclick)
│       └── brand/                  # nexus-* brand assets
└── deploy/
    ├── docker-compose.yml
    ├── .env.docker                 # Secretlar — asla commit'leme
    └── .rsyncignore
```

## Deploy

```bash
# Tam deploy (rsync + docker rebuild)
rsync ... && docker compose --env-file deploy/.env.docker \
  -f deploy/docker-compose.yml up --build -d

# Deploy path (VPS)
/home/berke/X/
```

## Migration

```bash
# Yeni migration oluştur
alembic revision --autogenerate -m "açıklama"

# Uygula
alembic upgrade head

# Geri al
alembic downgrade -1
```

## Vault

Mimari kararlar, açık işler ve alan notları → `docs/vault/`

| Dosya | Ne zaman oku | Ne zaman yaz |
|-------|-------------|--------------|
| `todo.md` | Açık işleri görmek istediğinde | TODO açılır/kapanır |
| `areas/backend.md` | Migration veya servis değişikliği öncesi | Değişiklik tamamlanınca |
| `areas/frontend.md` | Bileşen veya sayfa değişikliği öncesi | Değişiklik tamamlanınca |
| `areas/infra.md` | Deploy veya Docker/Caddy değişikliği öncesi | Değişiklik tamamlanınca |
| `areas/security.md` | Auth, WebAuthn, rate limit değişikliği öncesi | Karar alınca |
| `decisions/NNN-*.md` | Bir kararın geçmişi sorulduğunda | Yeni mimari karar alınca |
| `bugs/` | Aynı alanda tekrar eden sorun | Bug çözülünce |

**Kural:** Tek dosya, tek okuma. Vault'u tarama.

## Env Değişkenleri (Kritikler)

```
# deploy/.env.docker içinde bulunmalı
DATABASE_URL=...
JWT_SECRET=...
RESEND_API_KEY=...          # mail için zorunlu
VAPID_PUBLIC_KEY=...        # push için zorunlu
VAPID_PRIVATE_KEY=...       # push için zorunlu
```
