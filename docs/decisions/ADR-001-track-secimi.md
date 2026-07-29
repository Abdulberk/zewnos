# ADR-001 — Track B (Sonart Tekstil) seçildi

**Durum:** Kabul edildi

## Bağlam

Ödevde iki track var. Track A (Zewnos, Meta/Instagram reklam) daha kolay ve
demo tarafı daha gösterişli. Track B (Sonart, ERP stok/satış) daha yoğun bir
domain ve zorunlu olarak zaman serisi analizi gerektiriyor.

Puan tablosuna karşı dürüst bir karşılaştırma yaptığımda ikisi birbirine çok
yakın çıktı. A'nın iki gerçek avantajı vardı:

- **Video anlaşılırlığı (%10):** "ROAS 0,33'e düşmüş, bu kampanyayı durdur"
  cümlesini teknik olmayan biri 15 saniyede anlar. B'de "marj erozyonu"nu
  anlatmak için önce marj kavramını kurmak gerekiyor.
- **Bonuslar daha kolay:** bütçe dağıtım algoritması matematiksel ve temiz;
  caption üretimi demoda parlıyor. B'nin bonusu (serbest soru-cevap)
  güvenilir yapmak daha zor.

Ayrıca "dönemsel farklılaşma" (%10) kalemi *puan tablosunda her iki track için
de* var ama *zorunlular listesinde yalnızca B için* yazılmış. Yani A'da bunu
yapmak beklentiyi aşmak, B'de sadece barı geçmek olurdu.

## Karar

**Track B**, ve mimari her iki track'i de kaldıracak şekilde kurulacak.

## Gerekçe

1. **Ödev metni asıl önceliği açıkça söylüyor:** *"300+ farklı raporu 'Yönetici
   dashboard'u' halinde sunabilmek nihai hedefimiz — bu ödev bunun küçük
   ölçekli bir simülasyonudur."* Bu cümle Track A bölümünde yok. B'yi seçmek
   "verilen ödevi iyi yaptım" değil, "asıl problemi anladım" demek.
2. **Veri, zaman serisi olmadan çözülemeyecek üç sinyal içeriyor:** arz kısıtı
   (U005), sessiz stok birikimi (U002), marj erozyonu (U007). Ödev de bunu
   istiyor: *"Statik, tek dönemlik bir özet yeterli değildir."*
3. **Ayrışma:** çoğu aday A'yı seçecek.

## Değerlendirilen alternatifler

| Alternatif | Neden seçilmedi |
|---|---|
| Yalnızca Track A | Stratejik hizalanma kaybı; "300 rapor" hedefine cevap vermiyor |
| Yalnızca Track B | Jeneriklik iddiası README'de kalır, kanıtlanmaz |
| **Track B ana + A ikincil pack** | **Seçilen** — jenerikliği kanıtlıyor |

## Sonuçları

- `zewnos-ads` pack'i yazıldı (~330 satır). Motor, endpoint'ler, kalite hattı ve
  AI katmanı değişmedi.
- "301. rapor için ne yapman gerekir?" sorusuna gösterilebilir bir cevap var.
- Ödün: ~%25 ekstra iş, ve B'nin domain'i videoda biraz daha fazla anlatım
  gerektiriyor.
