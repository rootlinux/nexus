# Obsidian Vault Entegrasyonu — Tasarım Dokümanı

**Tarih:** 2026-04-29  
**Durum:** Onaylandı  
**Referans:** https://github.com/heyitsnoah/claudesidian

---

## Amaç

Nexus geliştirme sürecini yönetmek için `X/docs/vault/` altında bir Obsidian vault oluşturmak. Bu vault; açık TODO'ları, mimari kararları, alan notlarını ve bug araştırmalarını barındırır. Claude Code ihtiyaç duyduğunda doğrudan ilgili dosyayı okur, bir iş tamamlandığında ilgili dosyayı günceller.

**Temel kısıt:** Token kullanımını minimize et — Claude vault'u taramaz, her seferinde tek bir dosyayı hedefli açar.

---

## Yaklaşım

Claudesidian'dan ilham alan ama Nexus'a özgün tasarlanmış hafif bir dosya sistemi entegrasyonu. Ek bağımlılık yok, MCP server gerekmez. Vault git'e dahildir, Obsidian ile görsel arayüz sağlanır, CLAUDE.md ile Claude Code'a kurallar iletilir.

---

## Vault Yapısı

```
X/docs/vault/
├── .obsidian/              # Obsidian ayarları (git'e dahil)
├── projects/
│   ├── active/             # Aktif geliştirme girişimleri
│   └── archive/            # Tamamlanan projeler
├── areas/
│   ├── backend.md          # FastAPI, servisler, migration özeti, kritik notlar
│   ├── frontend.md         # Next.js, bileşenler, sw.js, PWA notları
│   ├── infra.md            # Docker, Caddy, Cloudflare, deploy komutu, env listesi
│   └── security.md         # Auth, WebAuthn, rate limit, Cloudflare fix kararları
├── decisions/              # ADR — Mimari Karar Kayıtları
│   ├── 001-cloudflare-login-challenge-fix.md
│   ├── 002-webauthn-admin-recovery.md
│   └── 003-nexus-rebrand.md
├── bugs/                   # Bug araştırmaları ve post-mortemler
├── todo.md                 # Açık işler (CLAUDE.md TODO bölümünün taşındığı yer)
└── inbox.md                # Hızlı yakalamalar, henüz sınıflandırılmamış
```

---

## Okuma / Yazma Kuralları

### Ne zaman oku

| Durum | Oku |
|-------|-----|
| Migration veya servis değişikliği | `areas/backend.md` |
| Bileşen veya sayfa değişikliği | `areas/frontend.md` |
| Deploy, Docker, Caddy değişikliği | `areas/infra.md` |
| Auth, WebAuthn, rate limit değişikliği | `areas/security.md` |
| Bir kararın geçmişi sorulduğunda | İlgili `decisions/NNN-*.md` |
| Aynı alanda tekrar eden sorun | İlgili `bugs/` dosyası |
| Açık işleri görmek gerektiğinde | `todo.md` |

### Ne zaman yaz

| Durum | Yaz |
|-------|-----|
| Migration tamamlandı | `areas/backend.md` güncelle |
| Mimari karar alındı | `decisions/` altına yeni ADR oluştur |
| Bug çözüldü | `bugs/` altına post-mortem ekle |
| Frontend değişikliği tamamlandı | `areas/frontend.md` güncelle |
| Yeni TODO açıldı / kapatıldı | `todo.md` güncelle |

**Kural:** Tek dosya, tek okuma. Vault'u tarama.

---

## ADR Formatı

```markdown
# NNN — Karar Başlığı
**Tarih:** YYYY-MM-DD  
**Durum:** aktif | değiştirildi | iptal edildi

## Bağlam
Neden bu karar gerekti?

## Karar
Ne yapıldı?

## Sonuçlar
Ne kazandık, ne kaybettik?
```

---

## CLAUDE.md Değişiklikleri

Mevcut "Açık İşler" ve "Önemli Notlar" bölümleri kaldırılır, yerlerine kısa bir pointer eklenir:

```markdown
## Vault
Mimari kararlar, açık işler ve alan notları → `docs/vault/`
Okuma/yazma kuralları bu dosyanın içinde tanımlıdır.
```

CLAUDE.md'ye ayrıca okuma/yazma tablosu (yukarıdaki) eklenir.

---

## Başlangıç İçeriği Kaynağı

Vault ilk kurulumda `özet.md` dosyasından beslenir:

- `özet.md` → `areas/*.md` dosyalarına ilgili bölümler dağıtılır
- `özet.md` → `todo.md` (Açık İşler bölümü)
- `özet.md` → `decisions/` (Önemli Notlar → ADR'a dönüştürme)

`özet.md` kurulumdan sonra silinmez — genel proje özeti olarak `docs/` altında kalır.

---

## Kapsam Dışı

- MCP server entegrasyonu
- Otomatik vault senkronizasyonu
- Obsidian plugin kurulumu
- Mobile erişim (SSH/Tailscale)
- Claudesidian skill'leri (inbox-processor, de-ai-ify vb.)
