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
