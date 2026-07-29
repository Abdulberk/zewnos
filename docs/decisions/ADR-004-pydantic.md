# ADR-004 — Pydantic v2 (msgspec elendi)

**Durum:** Kabul edildi

## Bağlam

Üç yerde şema/doğrulama gerekiyor: API request/response DTO'ları, uygulama
ayarları, ve AI çıktı sözleşmesi.

2026 benchmark'ları msgspec'i öne çıkarıyor: Pydantic v2'den 2-5x hızlı
decode/encode, tip doğrulamada ~3x. Pydantic v2 Rust çekirdeğiyle overhead'i
~%50 kesmiş ama hâlâ dataclass'ların 5-7 katı yavaş.

## Karar

**Pydantic v2.** Hız gerekçesiyle değil, iki yapısal zorunluluk nedeniyle.

## Gerekçe

1. **FastAPI'nin kendisi Pydantic üzerine kurulu.** Request/response
   validasyonu, otomatik OpenAPI şeması, oradan Next.js'e ürettiğimiz TS client
   — hepsi Pydantic modellerinden geliyor. msgspec'e geçmek FastAPI'yi seçme
   sebebimizi iptal eder.
2. **Anthropic SDK'sının structured output'u Pydantic modeli alıyor:**
   `client.messages.parse(output_format=PeriodAnalysis)` → `parsed_output`
   doğrudan tipli nesne. msgspec ile bunu kullanamaz, JSON Schema'yı elle yazıp
   parse etmeyi üstlenirdik. AI çıktısının şemaya uyma garantisi %20'lik kalemin
   kalbi — burada risk almanın anlamı yok.

Ek olarak msgspec yalnızca **tip** doğruluyor; iş kuralları ayrı `.validate()`
çağrılarına kalıyor. Pydantic tip + kural + formatı tek yerde tutuyor —
`Field(min_length=1)` ile "kanıtsız aksiyon reddedilir" kuralını şemaya
gömebiliyoruz ([ADR-007](ADR-007-ai-sayi-hesaplamaz.md)).

Hız tarafı: 91 satır ve 7 AI yanıtı doğruluyoruz. Mikrosaniyelerde 3x fark
ölçülemez.

## Pydantic *nerede kullanılmıyor*

Bu ayrım kasıtlı: CSV'nin 91 satırını satır satır Pydantic'ten geçirmiyoruz.
Hem yavaş hem anlamsız olurdu — Polars zaten tipli kolon şeması veriyor. Satır
seviyesi doğrulama Polars şeması + kendi kalite kurallarımızın işi.

Pydantic'in işi üç yerde:

| Yer | Ne için |
|---|---|
| `app/schemas/` | API sözleşmesi (DTO) |
| `app/core/config.py` | `BaseSettings` — env okuma, tipli config, açılışta doğrulama |
| `app/ai/ai_schemas.py` | **AI çıktı sözleşmesi** — asıl kritik yer |

## Sonuçları

- Yanlış yapılandırma çalışma zamanında değil, uygulama açılışında patlıyor.
- AI çıktısı API katmanında şemaya zorlanıyor; şema uymazsa model yeniden
  deniyor.
- Ödün: satır bazlı kütle doğrulama gerekirse (milyonlarca satır) msgspec veya
  doğrudan Polars şeması tercih edilmeli. Bu projede o yol zaten Polars'ta.
