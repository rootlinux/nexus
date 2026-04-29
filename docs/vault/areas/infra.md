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
