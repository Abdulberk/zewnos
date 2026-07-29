# ADR-006 — Claude API; model ve effort yapılandırılabilir

**Durum:** Kabul edildi

## Bağlam

Ödev OpenAI, Gemini veya Claude'dan birini seçmeyi ve gerekçelendirmeyi
istiyor. Ayrıca geliştirme bütçesi sınırlıydı, bu yüzden model seçimi
ölçülerek yapıldı.

## Karar

**Claude API.** Varsayılan `claude-sonnet-5` + `effort=medium`; teslim
edilecek nihai analiz için `claude-opus-5`. İkisi de `.env` üzerinden
değişiyor.

## Neden Claude

Üç sebep, üçü de "AI entegrasyonunun kalitesi (prompt tasarımı, çıktı
tutarlılığı)" kalemine çalışıyor:

1. **Structured outputs.** `client.messages.parse(output_format=PydanticModel)`
   ile çıktı JSON şemaya zorlanıyor; şema uymazsa yeniden deneniyor. Bu, "bazen
   düzgün JSON döndü bazen dönmedi" probleminin yapısal çözümü.
2. **Prompt caching.** 6 dönem çağrısı aynı ~13K token'lık bağlamı paylaşıyor.
   `cache_control` ile sabit prefix cache'lenip tekrar okumalar ~%10 fiyata
   düşüyor. Ölçülen etki: %45 maliyet tasarrufu
   ([ADR-008](ADR-008-no-orchestration-framework.md) içinde detay).
3. **Türkçe kalitesi ve 1M context.** Tüm rapor seti tek prompt'a sığıyor;
   "300+ rapor" senaryosunda önemli.

## Ölçülen karşılaştırma

Aynı dönem (2026-03), aynı bağlam, `effort=medium`, tek değişken model:

| | Opus 5 | Sonnet 5 |
|---|---|---|
| Çıktı token | 3.279 | 2.197 |
| Süre | 53 sn | **24 sn** |
| Tek çağrı maliyeti | $0,167 | **$0,056** |
| Tam analiz (7 çağrı) | ~$0,72 | **~$0,22** |
| Grounding | %100 | %100 |
| Aksiyon sayısı | 7 | 6 |

**Sonnet 5 ~3x ucuz, 2x hızlı.** Ama ölçülebilir bir kalite farkı var:

**Sonnet dönemsel atıf hatası yaptı.** 2026-03 analizinde U003 için *"3
dönemdir stok sıfır"* dedi. Oysa U003'ün Mart stoğu **30**; sıfıra Nisan'da
düştü. Tüm seriye ait toplam değeri (`sifir_stok_donem=3`) tek bir döneme
yapıştırdı — yani aggregate/period karışması.

Opus aynı ürün için dikkatliydi: *"U003'ün çıkışı 80'den 40'a inmiş ve sıfır
stok dönemleri birikiyor"* — henüz sıfır olduğunu iddia etmedi. Ayrıca
aksiyonlar arasında bağ kurdu: *"fiyat kararı verilirken stok da bitiyor, ikisi
aynı sipariş dalgasında ele alınmalı."*

Bu fark tam olarak puan tablosundaki **%10'luk "dönemsel farklılaşma"**
kalemine denk geliyor.

## Değerlendirilen alternatifler

| Alternatif | Neden seçilmedi |
|---|---|
| OpenAI | Structured outputs var, mimari aynı kalır. Claude'un prompt caching + Türkçe kalitesi tercih edildi |
| Gemini | Response schema desteği var. Aynı gerekçe |
| Yalnızca Opus | Geliştirme sırasında 3x maliyet; bütçe sınırlıydı |
| Yalnızca Sonnet | Dönemsel atıf hatası, teslim edilecek çıktı için kabul edilemez |
| Haiku 4.5 | Denenmedi; bu görev çok adımlı akıl yürütme gerektiriyor |

## Sonuçları

- `AI_MODEL` ve `AI_EFFORT` ortam değişkeni. Önbellek anahtarı ikisini de
  içeriyor, yani model değişince eski analiz servis edilmiyor.
- Maliyet her yanıtta raporlanıyor (`telemetry.total_cost_usd`) ve
  `telemetry.py` içinde model bazlı fiyatlandırma var — ilk sürümde fiyatlar
  Opus'a sabit yazılmıştı ve Sonnet'in maliyetini yanlış gösteriyordu; düzeltildi.
- Ödün: iki modelin çıktısı birebir aynı değil. Ekran görüntüleri ve video
  hangi modelle üretildiyse onunla tutarlı olmalı.
