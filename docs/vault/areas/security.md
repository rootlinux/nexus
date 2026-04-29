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
