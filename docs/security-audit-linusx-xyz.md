# Güvenlik Denetim Raporu — linusx.xyz
**Tarih:** 13 Nisan 2026  
**Kapsam:** https://linusx.xyz, https://api.linusx.xyz, https://app.linusx.xyz  
**Yöntem:** Pasif & yarı-aktif analiz (HTTP header inceleme, DNS/TLS analizi, path keşfi, CORS testi)

---

## Özet Puanlama

| Kategori | Puan | Durum |
|---|---|---|
| TLS/SSL | 9/10 | Çok İyi |
| HTTP Güvenlik Başlıkları | 7/10 | İyi |
| CORS Yapılandırması | 7/10 | İyi |
| Subdomain Yüzeyi | 8/10 | İyi |
| Bilgi Açıklama | 8/10 | İyi |
| **Genel** | **7.8/10** | **İyi** |

---

## 1. Altyapı & Port Analizi

**Not:** Site Cloudflare CDN arkasında olduğu için gerçek sunucu IP'leri gizlenmektedir. Nmap ile port taraması Cloudflare'in IP'lerini tarar, gerçek backend'e ulaşamaz.

| Özellik | Değer |
|---|---|
| Cloudflare IP (IPv4) | `104.21.79.142`, `172.67.146.15` |
| Cloudflare IP (IPv6) | `2606:4700:3037::ac43:920f`, `2606:4700:3031::6815:4f8e` |
| CDN | Cloudflare (AS13335) |
| Reverse Proxy | Caddy (`Via: 1.1 Caddy` header) |
| Frontend | Next.js (App Router, Turbopack) |
| Backend | FastAPI (`{"message":"X Platform API","status":"running"}`) |
| DNS Kayıtları | NS: Cloudflare (`zoe.ns.cloudflare.com`, `jose.ns.cloudflare.com`) |

Cloudflare koruması gerçek sunucu IP'sini başarıyla gizlemektedir. Bu DDoS ve doğrudan saldırılar için önemli bir koruma katmanıdır.

---

## 2. SSL/TLS Analizi

### Sertifika Bilgileri
| Alan | Değer |
|---|---|
| Sertifika Otoritesi | Let's Encrypt (E7) |
| Algoritma | ECDSA P-256 + SHA-384 |
| Kapsam | `*.linusx.xyz`, `linusx.xyz` |
| Geçerlilik | 6 Nisan 2026 → 5 Temmuz 2026 |
| Yenileme | Otomatik (Let's Encrypt) |

### TLS Protokol Desteği
| Protokol | Durum |
|---|---|
| TLS 1.0 | **DEVRE DIŞI** ✅ |
| TLS 1.1 | **DEVRE DIŞI** ✅ |
| TLS 1.2 | **DEVRE DIŞI** ✅ |
| TLS 1.3 | **AKTİF** ✅ |
| Cipher Suite | `CHACHA20-POLY1305-SHA256` |

> **Mükemmel.** Yalnızca TLS 1.3 desteklenmektedir. TLS 1.0/1.1/1.2 tamamen devre dışıdır — POODLE, BEAST, SWEET32 gibi eski protokol açıklarına karşı tam koruma sağlanmaktadır.

---

## 3. HTTP Güvenlik Header Analizi

### linusx.xyz (Frontend)

```
strict-transport-security: max-age=31536000; includeSubDomains; preload  ✅
x-frame-options: DENY                                                      ✅
x-content-type-options: nosniff                                            ✅
referrer-policy: strict-origin-when-cross-origin                           ✅
permissions-policy: camera=(), microphone=(), geolocation=(), payment=()   ✅
content-security-policy: [mevcut, detay aşağıda]                           ⚠️
```

### Content Security Policy (CSP) Detayı

```
default-src 'self'
script-src  'self' 'unsafe-inline' 'unsafe-eval'    ← SORUN
style-src   'self' 'unsafe-inline'                   ← Orta risk
img-src     'self' data: blob: https://api.linusx.xyz
connect-src 'self' https://api.linusx.xyz
frame-ancestors 'none'
object-src 'none'
```

**Eksik Header:**
- `/.well-known/security.txt` → 404 (güvenlik açığı bildirimi için iletişim bilgisi yok)

---

## 4. CORS Analizi

### api.linusx.xyz CORS Davranışı

| Test | Sonuç |
|---|---|
| `Origin: https://linusx.xyz` | `access-control-allow-origin: https://linusx.xyz` ✅ |
| `Origin: https://evil.com` | ACAO header YOK (istek reddedildi) ✅ |
| `access-control-allow-credentials` | `true` ⚠️ |
| İzin verilen metodlar | `GET, POST, PUT, PATCH, DELETE, OPTIONS` |
| İzin verilen headerlar | `Authorization, Content-Type, X-Request-Id, X-Session-Transport, X-Skip-Auth-Refresh` |

**Durum:** CORS konfigürasyonu doğru çalışıyor. Arbitrary origin yansıtması yok. Credential izni yalnızca izin verilen origin için geçerli.

---

## 5. Subdomain Keşfi

### Certificate Transparency Logs (crt.sh) ve DNS

| Subdomain | IP | Durum |
|---|---|---|
| `linusx.xyz` | CF: `104.21.79.142` | AKTİF |
| `www.linusx.xyz` | CF: `172.67.146.15` | AKTİF |
| `app.linusx.xyz` | CF: `104.21.79.142` | AKTİF |
| `api.linusx.xyz` | CF: `172.67.146.15` | AKTİF |
| `*.linusx.xyz` | (wildcard cert) | — |

Tüm subdomainler Cloudflare üzerinden proxy'leniyor. Stagining/dev/test ortamları public DNS'de görünmüyor — iyi.

---

## 6. Path & Endpoint Keşfi

### Bulgular

| Path | HTTP Kodu | Yorum |
|---|---|---|
| `/.env` | **403** | Cloudflare/Caddy tarafından engelleniyor ✅ |
| `/.git/config` | **403** | Engelleniyor ✅ |
| `/wp-admin` | **403** | Engelleniyor ✅ |
| `/phpinfo.php` | **403** | Engelleniyor ✅ |
| `/admin` | 200 | Next.js catch-all route (kullanıcı profil sayfası) — gerçek admin değil |
| `/swagger` | 200 | Next.js catch-all route — gerçek Swagger değil |
| `/graphql` | 200 | Next.js catch-all route — gerçek GraphQL değil |
| `/openapi.json` | 200 | Next.js catch-all route — gerçek spec değil |
| `/robots.txt` | 200 | Cloudflare yönetimli içerik (AI bot engelleme dahil) |
| `/sitemap.xml` | 200 | Mevcut |
| `/.well-known/security.txt` | **404** | Eksik ⚠️ |

**Önemli Not:** Next.js'in `[username]` catch-all route yapısı nedeniyle `/admin`, `/swagger`, `/graphql` gibi path'ler 200 döndürüyor ancak bunlar gerçek admin/API endpoint'leri değil, kullanıcı profil sayfalarıdır. Bu otomatik tarayıcılarda false positive üretir.

---

## 7. E-posta Güvenliği (SPF/DMARC)

| Kayıt | Değer | Değerlendirme |
|---|---|---|
| SPF | `v=spf1 include:_spf.mx.cloudflare.net ~all` | `~all` softfail — zayıf ⚠️ |
| MX | Cloudflare MX (route1/2/3.mx.cloudflare.net) | ✅ |
| DMARC | Sorgulanmadı | Kontrol edilmeli |

---

## 8. Bulgular & Öneriler

### ORTA Şiddet

#### M-1: CSP'de `unsafe-eval` Direktifi
**Etki:** `eval()`, `new Function()`, `setTimeout(string)` gibi dinamik kod çalıştırmaya izin verir. Başka bir XSS vektörüyle birleştiğinde sömürülebilir.  
**Çözüm:** `unsafe-eval`'i kaldır. Eğer JSON parse veya dynamic import için gerekiyorsa, Next.js'de `nonce` veya `hash` tabanlı CSP kullan.

```
# Mevcut (riskli)
script-src 'self' 'unsafe-inline' 'unsafe-eval'

# Hedef
script-src 'self' 'nonce-{random}' 'strict-dynamic'
```

#### M-2: CSP'de `unsafe-inline` Script Direktifi
**Etki:** Inline `<script>` etiketlerinin çalışmasına izin verir. DOM-based XSS senaryolarında CSP'yi devre dışı bırakır.  
**Çözüm:** Next.js `nonce` desteğiyle `unsafe-inline` kaldırılabilir (`next.config.js`'de CSP nonce middleware).

#### M-3: SPF `~all` Softfail
**Etki:** Yetkisiz gönderenler e-posta gönderebildiğinde softfail olarak işaretlenir ama genellikle teslim edilir. Phishing saldırılarında domain sahteciliği kolaylaşır.  
**Çözüm:** SPF kaydını `-all` (hardfail) olarak güncelle:
```
v=spf1 include:_spf.mx.cloudflare.net -all
```

---

### DÜŞÜK Şiddet

#### D-1: HSTS Preload Listesinde Değil
**Etki:** `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` header'ı doğru ayarlanmış ancak domain henüz preload listesine eklenmemiş (durum: `unknown`). İlk ziyarette SSL stripping saldırısına açık.  
**Çözüm:** https://hstspreload.org adresine başvur.

#### D-2: `/.well-known/security.txt` Eksik
**Etki:** Güvenlik araştırmacıları açık nasıl bildireceğini bilemiyor.  
**Çözüm:** RFC 9116 uyumlu bir `security.txt` oluştur:
```
Contact: mailto:security@linusx.xyz
Expires: 2027-04-13T00:00:00.000Z
Preferred-Languages: tr, en
```

#### D-3: Caddy Sunucu Versiyonu Açıklanıyor
**Etki:** `Via: 1.1 Caddy` header'ı reverse proxy teknolojisini açıklıyor. Cloudflare üzerinden geçmesine rağmen `Via` header'ı iletiliyor.  
**Çözüm:** Caddy konfigürasyonunda `header` direktifiyle `Via` header'ını kaldır:
```caddyfile
header -Via
```

---

### BİLGİSEL

#### B-1: `x-request-id` Header (api.linusx.xyz)
İç istek takip ID'si (`x-request-id: 0ea11c244fc94140b4c12fac70919184`) response'da görünüyor. Minimal bilgi açıklama — log korelasyonu için faydalı ama istenirse kaldırılabilir.

#### B-2: Next.js Catch-All Route Semantiği
`/admin`, `/swagger`, `/graphql` gibi path'lerin 200 dönmesi gerçek bir zafiyet değil, ancak otomatik güvenlik tarayıcılarında false positive oluşturuyor. Bunu önlemek için kritik path'leri explicit 404'e yönlendir:
```typescript
// next.config.ts - redirects
{ source: '/swagger', destination: '/404', permanent: false },
{ source: '/graphql', destination: '/404', permanent: false },
```

#### B-3: `app.linusx.xyz` Subdomaini
`app.linusx.xyz` de aynı uygulamayı sunuyor (`www.linusx.xyz` ve `linusx.xyz` ile aynı). Eğer kullanılmıyorsa DNS kaydını kaldır, kullanılıyorsa canonical URL'yi standartlaştır.

---

## 9. OWASP Top 10 Değerlendirmesi

| # | Başlık | Durum |
|---|---|---|
| A01 | Broken Access Control | Değerlendirilemedi (auth gerekli) |
| A02 | Cryptographic Failures | **✅ İyi** — TLS 1.3, HSTS aktif |
| A03 | Injection | Değerlendirilemedi (auth gerekli) |
| A04 | Insecure Design | Değerlendirilemedi |
| A05 | Security Misconfiguration | **⚠️ Orta** — CSP `unsafe-eval/inline` |
| A06 | Vulnerable Components | Değerlendirilemedi (bağımlılık listesi yok) |
| A07 | Auth & Session Failures | Değerlendirilemedi (auth gerekli) |
| A08 | Software Integrity Failures | Değerlendirilemedi |
| A09 | Logging & Monitoring | `x-request-id` var, detay bilinmiyor |
| A10 | SSRF | Değerlendirilemedi |

---

## 10. Olumlu Bulgular

- TLS 1.3 zorunlu, eski protokoller tamamen devre dışı
- HSTS `includeSubDomains` + `preload` directive
- `X-Frame-Options: DENY` — Clickjacking koruması
- `X-Content-Type-Options: nosniff` — MIME sniffing koruması
- `Permissions-Policy` — Kamera/mikrofon/konum erişimi kısıtlı
- `object-src: none` — Flash/plugin yükleme engeli
- `frame-ancestors: none` — Ek clickjacking koruması
- CORS arbitrary origin yansıtması yok
- `.env`, `.git/config` 403 ile engelleniyor
- Cloudflare CDN ile gerçek IP gizleniyor
- Let's Encrypt wildcard sertifikası (otomatik yenileme)
- HTTP → HTTPS redirect çalışıyor

---

## 11. Öncelik Sırası

| Öncelik | Görev | Çaba |
|---|---|---|
| 1 | CSP `unsafe-eval` kaldır | Orta |
| 2 | CSP `unsafe-inline` kaldır, nonce ekle | Yüksek |
| 3 | SPF `-all` hardfail'e geç | Düşük |
| 4 | `security.txt` oluştur | Düşük |
| 5 | HSTS preload başvurusu yap | Düşük |
| 6 | Caddy `Via` header'ını kaldır | Düşük |
| 7 | DMARC kaydı kontrol et/ekle | Orta |

---

## Analiz Kapsamı & Sınırlamalar

Bu analiz aşağıdaki araçlarla gerçekleştirildi:
- `curl` — HTTP header ve path analizi
- `openssl` — TLS/SSL analizi
- `dig` — DNS kayıt analizi
- `crt.sh` API — Certificate Transparency log taraması

**Kapsam dışı (ek araç gerektirir):**
- Nmap port taraması (Cloudflare arkasında anlamsız; gerçek IP bilinmeden yapılamaz)
- Nikto web taraması
- testssl.sh TLS detay analizi
- OWASP ZAP aktif tarama (auth gerekli endpoint'ler)
- Kaynak kod analizi
- Kimlik doğrulama gerektiren endpoint'ler

*Bu rapor yetkili güvenlik testi kapsamında hazırlanmıştır.*
