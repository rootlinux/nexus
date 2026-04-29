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
