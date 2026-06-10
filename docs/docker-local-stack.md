# Docker Local Stack

Bu doküman sadece yerel production-like smoke stack içindir.
Production deploy rehberi değildir.

Canonical path'ler:

- Compose stack: `deploy/docker-compose.yml`
- Local smoke env template: `deploy/.env.local-smoke.example`
- Local smoke runtime env: `deploy/.env.docker`
- Local smoke reverse proxy: `deploy/Caddyfile`
- Production reverse proxy template: `deploy/Caddyfile.prod`
- Canonical backend test env: `backend/.venv`

Not:

- Bu dokümandaki `app.x.localtest.me` / `api.x.localtest.me` host'ları production truth değildir; sadece local smoke için canonical'dır.
- Gerçek deploy env değerleri ayrıca ve açık şekilde sağlanmalıdır.
- Production için `deploy/Caddyfile` kullanılmamalıdır; bu dosya local smoke için `auto_https off` içerir.
- Her environment kendi `SECRET_KEY` değerini kullanmalıdır; smoke/local secret'ları staging veya production ile paylaştırılmamalıdır.

## İlk kurulum veya yerel veriyi yeniden Docker'a aktarma

`deploy/scripts/docker-reset-and-start.sh`

Bu script:

- host makinedeki `localhost:5432/xplatform` veritabanının güncel dump'ını alır
- dump'ı `deploy/initdb/010-xplatform.sql` içine yazar
- Docker stack'i sıfırdan kurar
- Docker Postgres'i bu dump ile ayağa kaldırır
- backend ve web'i build edip başlatır

## Sonraki açılışlar

`deploy/scripts/docker-start.sh`

Bu akış mevcut Docker volume'lerini korur. Yani bir kez import edildikten sonra `start` ile kaldığı yerden açılır.

## Durdurma

`deploy/scripts/docker-stop.sh`

## URL'ler

- Web: `http://app.x.localtest.me:3000`
- API: `http://api.x.localtest.me:8000`

## Notlar

- Host makinedeki Postgres ve Redis port çakışması olmaması için Docker içindeki `postgres` ve `redis` dışarı port publish etmez.
- Yüklenen medya dosyaları `backend/uploads` klasöründen bind mount edilir; bu yüzden mevcut upload'lar Docker içinde de görünür.
- Host verisi tekrar Docker'a alınacaksa yeniden `docker-reset-and-start.sh` çalıştırılmalıdır.
