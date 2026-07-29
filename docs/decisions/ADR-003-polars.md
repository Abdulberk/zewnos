# ADR-003 — Polars (pandas elendi)

**Durum:** Kabul edildi

## Bağlam

Projenin kalbi zaman serisi hesapları: dönemsel gruplama, `pct_change`,
hareketli ortalama, stok mutabakatı, kapama ayı, tükenme projeksiyonu. Veri
küçük (91 satır) — performans tamamen alakasız. Dolayısıyla hız argümanı bu
projede **sahte** olurdu.

2026 karşılaştırmaları Polars'ı yeni pipeline'lar için önerilen varsayılan
olarak konumlandırıyor (H2O.ai benchmark'ında 10M satırda ~15x, production'da
GitHub/JPMorgan/Databricks). Ama bizim gerekçemiz bu değil.

## Karar

**Polars 1.x.**

## Gerekçe (hız değil, üç somut sebep)

1. **Null modeli.** Veride U010/2026-04 satırı tamamen boş. pandas'ta eksik
   tamsayı kolonu `float64`'e kayar ve `NaN` gelir; nullable dtype'larla
   (`Int64`) dikkatli oynamak gerekir. Polars'ta null birinci sınıf vatandaş ve
   `NaN`'dan **ayrı** bir kavram; tamsayı kolonu tamsayı kalır. Puan
   tablosundaki %10'luk kalem tam olarak "eksik/bozuk satır" hakkında —
   pandas'ın sessiz tip dönüşümleri burada gerçek bir risk.
2. **`.over()` ile grup sınırı güvenliği.** 15 SKU × 6 dönem var. Zaman serisi
   analizinin 1 numaralı hatası, `shift(1)` yaparken bir ürünün son ayından bir
   sonraki ürünün ilk ayına değer taşımak. Hata **sessizdir**: sonuç üretilir
   ama yanlıştır. Polars'ta grup bağlamı ifadenin içinde yazılıyor:
   ```python
   pl.col("donem_sonu_stok").shift(1).over(ctx.entity_key)
   ```
   pandas'ta `groupby(...).transform(...)` ile aynısı yapılır ama grup bağlamı
   ifadeden ayrı durur — unutmak kolay. Mutabakat kontrolümüz tam olarak bu
   mekanizmaya dayanıyor ve bir testle sabitlendi
   (`test_pencere_hesaplari_urun_sinirini_asmaz`).
3. **Lazy API ile gerçek ölçekleme cevabı.** *"300 rapora nasıl ölçeklenir?"*
   sorusuna el sallamak yerine: pipeline `pl.scan_csv()` ile lazy'ye geçer,
   `collect()` noktası streaming olur, kod aynı kalır.

Ek fayda: Polars belirsiz işlemlerde **hata verir**, pandas sessizce bir şey
yapar. Doğruluk kritik bir işte bu iyi.

## Değerlendirilen alternatifler

| Alternatif | Neden elendi |
|---|---|
| **pandas** | Evrensel aşinalık ve 50x büyük StackOverflow arşivi. Karşılığında: sessiz dtype dönüşümleri, grup sınırı hatalarına açıklık, zayıf ölçekleme hikâyesi |
| **DuckDB** | Analitik için doğru araç ama satır verisini kalıcılaştırmıyoruz, sorgulayacağı bir şey yok. Ayrıca mantığı Polars ile SQL arasında bölerdi (bkz. [ADR-005](ADR-005-sqlite.md)) |
| **Elle TypeScript** | groupby, pct_change, rolling, reindex'i sıfırdan yazmak. ~3-4x kod ve test yükü |
| **Narwhals** (dataframe-agnostik katman) | Bu ölçekte gereksiz soyutlama |

## Sonuçları

- Tüm türetilmiş metrikler pack içinde `Callable[[PackContext], pl.Expr]`
  olarak tanımlı; grup bağlamı ifadenin parçası.
- Metrikler **tek tek** ekleniyor (hepsi birden değil), çünkü Polars aynı
  `with_columns` çağrısındaki ifadeleri bağımsız değerlendirir. Pack'teki tanım
  sırası = bağımlılık sırası. Bu tuzağa geliştirme sırasında düştük ve
  `series.py` içinde belgelendi.
- Kaçış kapısı açık: bir işlem zorlarsa `.to_pandas()` tek satır.
