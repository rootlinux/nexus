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
