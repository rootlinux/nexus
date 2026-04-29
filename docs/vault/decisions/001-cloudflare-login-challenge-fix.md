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
