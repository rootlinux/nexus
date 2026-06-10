# Obsidian Vault Entegrasyonu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/vault/` altında Nexus geliştirme ikinci beyni oluşturmak — vault yapısı, başlangıç içeriği ve CLAUDE.md entegrasyonu dahil.

**Architecture:** `docs/vault/` klasörü PARA-ilham yapısıyla oluşturulur. İçerik `özet.md`'den beslenir. CLAUDE.md hedefli okuma/yazma kurallarıyla güncellenir. Hiç ek bağımlılık yok.

**Tech Stack:** Markdown dosyaları, Obsidian (yerel), Git

---

## Dosya Haritası

**Oluşturulacak:**
- `docs/vault/.obsidian/app.json` — Obsidian temel ayarları
- `docs/vault/todo.md` — Açık işler
- `docs/vault/areas/backend.md` — Backend alan notu
- `docs/vault/areas/frontend.md` — Frontend alan notu
- `docs/vault/areas/infra.md` — Altyapı alan notu
- `docs/vault/areas/security.md` — Güvenlik alan notu
- `docs/vault/decisions/001-cloudflare-login-challenge-fix.md` — ADR
- `docs/vault/decisions/002-webauthn-admin-recovery.md` — ADR
- `docs/vault/decisions/003-nexus-rebrand.md` — ADR
- `docs/vault/inbox.md` — Hızlı yakalamalar
- `docs/vault/projects/active/.gitkeep`
- `docs/vault/projects/archive/.gitkeep`
- `docs/vault/bugs/.gitkeep`

**Değiştirilecek:**
- `CLAUDE.md` — "Açık İşler" ve "Önemli Notlar" bölümleri kaldırılır, vault kuralları eklenir

---

## Task 1: Vault Dizin Yapısını Oluştur

**Files:**
- Create: `docs/vault/.obsidian/app.json`
- Create: `docs/vault/projects/active/.gitkeep`
- Create: `docs/vault/projects/archive/.gitkeep`
- Create: `docs/vault/bugs/.gitkeep`
- Create: `docs/vault/inbox.md`

- [ ] **Step 1: Klasörleri oluştur**

```bash
mkdir -p docs/vault/.obsidian
mkdir -p docs/vault/projects/active
mkdir -p docs/vault/projects/archive
mkdir -p docs/vault/areas
mkdir -p docs/vault/decisions
mkdir -p docs/vault/bugs
```

- [ ] **Step 2: Obsidian ayar dosyasını yaz**

`docs/vault/.obsidian/app.json` içeriği:
```json
{
  "defaultViewMode": "source",
  "vimMode": false,
  "newFileLocation": "folder",
  "newFileFolderPath": "inbox",
  "attachmentFolderPath": "projects",
  "showLineNumber": true,
  "spellcheck": false
}
```

- [ ] **Step 3: Boş klasörler için gitkeep dosyaları yaz**

```bash
touch docs/vault/projects/active/.gitkeep
touch docs/vault/projects/archive/.gitkeep
touch docs/vault/bugs/.gitkeep
```

- [ ] **Step 4: inbox.md oluştur**

`docs/vault/inbox.md` içeriği:
```markdown
# Inbox

Henüz sınıflandırılmamış notlar buraya gelir.
İşlendikten sonra ilgili `areas/`, `decisions/` veya `projects/` altına taşı.

---
```

- [ ] **Step 5: Yapıyı doğrula**

```bash
find docs/vault -type f | sort
```

Beklenen çıktı:
```
docs/vault/.obsidian/app.json
docs/vault/bugs/.gitkeep
docs/vault/inbox.md
docs/vault/projects/active/.gitkeep
docs/vault/projects/archive/.gitkeep
```

- [ ] **Step 6: Commit**

```bash
git add docs/vault/
git commit -m "feat(vault): initialize obsidian vault structure"
```

---

## Task 2: todo.md — Açık İşler

**Files:**
- Create: `docs/vault/todo.md`

Kaynak: `özet.md` → "Açık İşler" bölümü

- [ ] **Step 1: todo.md yaz**

`docs/vault/todo.md` içeriği:
```markdown
# Açık İşler

## Kritik

- [ ] `ResendMailSender.send()` → `resend.api_key` set edilmiyor — mail gönderimleri çalışmıyor
  - Dosya: `backend/app/services/mail.py`
- [ ] `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` env'de boş → push bildirimler kapalı
  - Dosya: `deploy/.env.docker`

## Orta Öncelik

- [ ] `sw.js` cache adı hâlâ `"lukeyz-shell"` → `"nexus-shell"` olmalı
  - Dosya: `web/public/sw.js`
- [ ] `docs/`, `README`, `examples/` içinde eski Lukeyz referansları temizlenmeli
- [ ] Mail servisinde rebrand audit eksik
  - Dosya: `backend/app/services/mail.py`

## Düşük Öncelik

- [ ] PWA installed icon cache riski
  - Dosya: `web/src/components/PwaBoot.tsx`
- [ ] `deploy/.env.docker` secretlarını temizle / rotate et
```

- [ ] **Step 2: Doğrula**

```bash
cat docs/vault/todo.md
```

Dosyanın 3 öncelik bölümü ve 7 madde içerdiğini kontrol et.

- [ ] **Step 3: Commit**

```bash
git add docs/vault/todo.md
git commit -m "feat(vault): add todo.md with open issues from özet.md"
```

---

## Task 3: areas/backend.md

**Files:**
- Create: `docs/vault/areas/backend.md`

Kaynak: `özet.md` → Backend bölümleri + CLAUDE.md kritik notlar

- [ ] **Step 1: backend.md yaz**

`docs/vault/areas/backend.md` içeriği:
```markdown
# Backend — Alan Notu

## Tech Stack
- FastAPI (Python 3.11) + SQLAlchemy (async)
- PostgreSQL — 35+ Alembic migration
- Redis — rate limiting
- Resend — mail (API key sorunu var, bkz. todo.md)
- VAPID (pywebpush) — web push (keyler boş, bkz. todo.md)
- Storage: local varsayılan, S3 geçişe hazır

## Dizin Yapısı
```
backend/app/
├── api/routes/     # HTTP endpoint'leri (auth, posts, users, invites…)
├── models/         # SQLAlchemy ORM modelleri
├── schemas/        # Pydantic request/response şemaları
├── services/       # İş mantığı katmanı
├── core/           # Config, DB, güvenlik, rate limit
└── storage/        # Dosya depolama
```

## API Route'ları
| Prefix | İşlev |
|--------|-------|
| `/api/auth` | Kayıt, giriş, token yenileme, e-posta doğrulama, şifre sıfırlama |
| `/api/posts` | Post CRUD, beğeni, repost, bookmark, reply, görsel yükleme |
| `/api/users` | Profil, takip/takipçi, avatar/kapak yükleme |
| `/api/invites` | Davet listesi, kampanya yönetimi |
| `/api/notifications` | Bildirimler, push aboneliği |
| `/api/search` | Kullanıcı ve post arama |
| `/api/bookmarks` | Kaydedilen postlar |
| `/api/discover` | Keşif akışı |
| `/api/messages` | Direkt mesajlaşma |
| `/api/webauthn` | Passkey yönetimi |
| `/api/admin` | Kullanıcı yönetimi, moderasyon |
| `/api/admin/staff` | Staff izin yönetimi |
| `/api/feedback` | Kullanıcı geri bildirimleri |
| `/api/waitlist` | Waitlist başvuruları |

## Veri Modelleri
| Model | Açıklama |
|-------|----------|
| `User` | status (active/frozen/suspended/banned), davet izi |
| `Post` | reply + quote destekli, moderasyon sinyali |
| `Follow`, `Block` | Sosyal graf |
| `Like`, `Bookmark` | Etkileşimler |
| `InviteCode`, `InviteCampaign`, `InviteUsage` | Davet sistemi |
| `RefreshToken` | Device fingerprint + MFA flag |
| `WebAuthnCredential` | Passkey kayıtları |
| `Notification`, `NotificationSettings` | Bildirim sistemi |
| `PushSubscription` | Web push aboneliği |
| `DM` | Direkt mesajlar |
| `StaffPermission` | Granüler staff yetkileri |
| `AdminAuditLog` | Admin işlem kaydı |
| `ModerationSignal` | Raporlanan içerik |
| `WaitlistApplication` | Waitlist başvuruları |

## Migration Geçmişi
1. **001–005** — Kullanıcılar, postlar, invite, refresh token, display name
2. **006–012** — Invite audit, moderasyon, profil, invite kimlik backfill
3. **013–020** — Moderation queue, bookmark, quote, block, device fingerprint, staff
4. **021–032** — Kampanyalar, hesap güvenliği, WebAuthn, timezone fix, admin recovery
5. **033–035** — DM tabloları, waitlist, discover index

## Migration Komutları
```bash
alembic revision --autogenerate -m "açıklama"   # yeni migration
alembic upgrade head                             # uygula
alembic downgrade -1                             # geri al
```

## Önemli Notlar
- `main.py` title: "X Platform" → "Nexus" olmalı (orta öncelik TODO)
- Env değişkenleri `deploy/.env.docker`'dan gelir, asla commit'leme
```

- [ ] **Step 2: Doğrula**

```bash
wc -l docs/vault/areas/backend.md
```

60'tan fazla satır olmalı.

- [ ] **Step 3: Commit**

```bash
git add docs/vault/areas/backend.md
git commit -m "feat(vault): add areas/backend.md"
```

---

## Task 4: areas/frontend.md

**Files:**
- Create: `docs/vault/areas/frontend.md`

- [ ] **Step 1: frontend.md yaz**

`docs/vault/areas/frontend.md` içeriği:
```markdown
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
```

- [ ] **Step 2: Doğrula**

```bash
cat docs/vault/areas/frontend.md | grep "^##" | wc -l
```

En az 4 bölüm başlığı olmalı.

- [ ] **Step 3: Commit**

```bash
git add docs/vault/areas/frontend.md
git commit -m "feat(vault): add areas/frontend.md"
```

---

## Task 5: areas/infra.md

**Files:**
- Create: `docs/vault/areas/infra.md`

- [ ] **Step 1: infra.md yaz**

`docs/vault/areas/infra.md` içeriği:
```markdown
# Altyapı — Alan Notu

## Servis Domainleri
| Servis | Domain |
|--------|--------|
| Web (Next.js) | linusx.xyz |
| API (FastAPI) | api.linusx.xyz |
| Mail | mail.linusx.xyz |

## Stack
```
Cloudflare CDN
    └── Caddy (reverse proxy + TLS)
            ├── Next.js (web)
            └── FastAPI (api)
                    ├── PostgreSQL
                    └── Redis
```

- **VPS:** 173.212.227.3
- **Deploy path (VPS):** `/home/berke/X/`

## Deploy Komutu
```bash
rsync ... && docker compose --env-file deploy/.env.docker \
  -f deploy/docker-compose.yml up --build -d
```

## Dosya Yapısı
```
deploy/
├── docker-compose.yml
├── .env.docker          # Secretlar — asla commit'leme
├── Caddyfile.prod
└── scripts/
    ├── docker-start.sh
    ├── docker-stop.sh
    └── docker-reset-and-start.sh
```

## Kritik Env Değişkenleri
```
DATABASE_URL=...
JWT_SECRET=...
RESEND_API_KEY=...       # mail için zorunlu
VAPID_PUBLIC_KEY=...     # push için zorunlu
VAPID_PRIVATE_KEY=...    # push için zorunlu
```

## Önemli Notlar
- Cloudflare `/api/auth/login` için challenge fix uygulandı — dokunurken dikkat
- `.env.docker` secretlarını rotate etmek düşük öncelik TODO listesinde
```

- [ ] **Step 2: Commit**

```bash
git add docs/vault/areas/infra.md
git commit -m "feat(vault): add areas/infra.md"
```

---

## Task 6: areas/security.md

**Files:**
- Create: `docs/vault/areas/security.md`

- [ ] **Step 1: security.md yaz**

`docs/vault/areas/security.md` içeriği:
```markdown
# Güvenlik — Alan Notu

## Auth Mimarisi
- **JWT** erişim tokeni (kısa ömürlü) + **refresh token** (HTTP-only cookie veya header)
- **WebAuthn / passkey** — 2. faktör ve admin kurtarma mekanizması
- **Device fingerprint** refresh token'lara bağlı
- **MFA satisfied** flag oturum başına saklanıyor
- **Rate limiting** — Redis üzerinde endpoint bazlı politikalar

## Middleware Güvenlik Başlıkları
Her response'a otomatik eklenen başlıklar (`main.py`):
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security: max-age=31536000`
- `Content-Security-Policy` — `unsafe-inline` style-src için kabul edildi (React inline styles)

## Production Guard
Config validation (`core/config.py`) production başlangıcında kontrol eder:
- SECRET_KEY gücü (min 64 karakter, bilinen zayıf değerler reddedilir)
- CORS_ALLOWED_ORIGINS boş olamaz
- ALLOWED_HOSTS wildcard/localhost kabul edilmez
- DEBUG=True production'da başlamayı engeller

## Kritik Kararlar
- Cloudflare `/api/auth/login` challenge fix → bkz. `decisions/001`
- WebAuthn admin + staff recovery → bkz. `decisions/002`
```

- [ ] **Step 2: Commit**

```bash
git add docs/vault/areas/security.md
git commit -m "feat(vault): add areas/security.md"
```

---

## Task 7: ADR Dosyaları

**Files:**
- Create: `docs/vault/decisions/001-cloudflare-login-challenge-fix.md`
- Create: `docs/vault/decisions/002-webauthn-admin-recovery.md`
- Create: `docs/vault/decisions/003-nexus-rebrand.md`

- [ ] **Step 1: ADR 001 yaz**

`docs/vault/decisions/001-cloudflare-login-challenge-fix.md` içeriği:
```markdown
# 001 — Cloudflare Login Challenge Fix

**Tarih:** 2026-04-29  
**Durum:** aktif

## Bağlam
`/api/auth/login` endpoint'i Cloudflare challenge'ı tetikliyordu. Bu, kullanıcıların giriş yapmasını engelleyen bir sorundu.

## Karar
Endpoint için Cloudflare tarafında özel bir kural uygulandı (challenge bypass).

## Sonuçlar
- Login akışı sorunsuz çalışıyor
- Bu endpoint'e dokunurken Cloudflare kural setini kontrol etmek gerekiyor
- Kural değişikliği Cloudflare dashboard'unda yapılmalı, kodda iz yok
```

- [ ] **Step 2: ADR 002 yaz**

`docs/vault/decisions/002-webauthn-admin-recovery.md` içeriği:
```markdown
# 002 — WebAuthn Admin & Staff Recovery

**Tarih:** 2026-04-29  
**Durum:** aktif

## Bağlam
Admin ve staff kullanıcıların WebAuthn credential'larını kaybetmesi durumunda platforma erişimleri kesilebilir.

## Karar
Admin WebAuthn recovery mekanizması eklendi. `core/config.py` üzerinden recovery identifier yapılandırılabiliyor. `auth.py`'de `_admin_webauthn_recovery_is_eligible()` ile uygunluk kontrolü yapılıyor.

## Sonuçlar
- Admin erişim kaybı riski minimize edildi
- Recovery flow yalnızca uygun kullanıcılar için tetikleniyor
- Staff permissions da bu süreçten geçiyor
```

- [ ] **Step 3: ADR 003 yaz**

`docs/vault/decisions/003-nexus-rebrand.md` içeriği:
```markdown
# 003 — Nexus Rebrand (eski adı: Lukeyz)

**Tarih:** 2026-04-29  
**Durum:** kısmen tamamlandı

## Bağlam
Platform Lukeyz adıyla başladı. Nexus olarak rebranding yapıldı.

## Karar
Runtime rebrand tamamlandı: layout, manifest, BrandLogo, mail servisi güncellendi.

## Sonuçlar
**Tamamlanan:**
- `layout.tsx`, `manifest.ts`, `BrandLogo.tsx` güncellendi
- Mail şablonları güncellendi
- `main.py` title: "Nexus API" ✓

**Bekleyen (bkz. todo.md):**
- `sw.js` cache adı: `"lukeyz-shell"` → `"nexus-shell"`
- `docs/`, `README`, `examples/` içinde eski referanslar
- Mail servisinde tam rebrand audit
```

- [ ] **Step 4: Doğrula**

```bash
ls docs/vault/decisions/
```

3 ADR dosyası görünmeli.

- [ ] **Step 5: Commit**

```bash
git add docs/vault/decisions/
git commit -m "feat(vault): add initial ADRs (cloudflare, webauthn, rebrand)"
```

---

## Task 8: CLAUDE.md Güncellemesi

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Mevcut CLAUDE.md'yi oku**

`CLAUDE.md` dosyasını oku ve "Açık İşler" ile "Önemli Notlar" bölümlerini tespit et.

- [ ] **Step 2: "Açık İşler" ve "Önemli Notlar" bölümlerini kaldır, vault bölümü ekle**

CLAUDE.md'de bu iki bölümü tamamen sil. Yerine şunu ekle (Migration bölümünden önce):

```markdown
## Vault

Tüm mimari kararlar, açık işler ve alan notları → `docs/vault/`

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
```

- [ ] **Step 3: Doğrula**

```bash
grep -n "Açık İşler\|Önemli Notlar\|Vault" CLAUDE.md
```

"Açık İşler" ve "Önemli Notlar" başlıkları görünmemeli, "Vault" başlığı görünmeli.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "feat(vault): update CLAUDE.md with vault rules, remove inline todos/notes"
```

---

## Task 9: .gitignore Kontrolü

**Files:**
- Modify: `.gitignore` (gerekirse)

- [ ] **Step 1: .obsidian klasörünün git durumunu kontrol et**

```bash
git status docs/vault/.obsidian/
```

- [ ] **Step 2: .gitignore durumunu kontrol et**

```bash
cat .gitignore | grep obsidian
```

Eğer `.obsidian` gitignore'da varsa bir sonraki adıma geç, yoksa işlem gerekmez.

- [ ] **Step 3: Gerekirse .gitignore'dan çıkar**

`.obsidian` gitignore'a eklenmiş olabilir. Bu vault'ta `.obsidian/` git'e dahil olmalı (paylaşılan Obsidian ayarları). Eğer ignore ediliyorsa:

`.gitignore`'a şunu ekle:
```
# Obsidian vault ayarları git'e dahil
!docs/vault/.obsidian/
```

- [ ] **Step 4: Commit (değişiklik olduysa)**

```bash
git add .gitignore
git commit -m "chore: include docs/vault/.obsidian in git"
```

---

## Task 10: Son Doğrulama

- [ ] **Step 1: Vault yapısını doğrula**

```bash
find docs/vault -type f | sort
```

Beklenen dosyalar:
```
docs/vault/.obsidian/app.json
docs/vault/areas/backend.md
docs/vault/areas/frontend.md
docs/vault/areas/infra.md
docs/vault/areas/security.md
docs/vault/bugs/.gitkeep
docs/vault/decisions/001-cloudflare-login-challenge-fix.md
docs/vault/decisions/002-webauthn-admin-recovery.md
docs/vault/decisions/003-nexus-rebrand.md
docs/vault/inbox.md
docs/vault/projects/active/.gitkeep
docs/vault/projects/archive/.gitkeep
docs/vault/todo.md
```

- [ ] **Step 2: CLAUDE.md vault bölümünü doğrula**

```bash
grep -A 20 "## Vault" CLAUDE.md
```

Okuma/yazma tablosu görünmeli.

- [ ] **Step 3: Git log'u doğrula**

```bash
git log --oneline -10
```

10 commit görünmeli (vault kurulum commit'leri).

- [ ] **Step 4: Obsidian'da vault'u aç**

`docs/vault/` klasörünü Obsidian'da "Open folder as vault" ile aç. Dosyaların sol panelde göründüğünü doğrula.
