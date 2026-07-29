# ADR-005 — SQLite + SQLAlchemy (DuckDB ve Postgres elendi)

**Durum:** Kabul edildi

## Bağlam

Neyi kalıcılaştırmak gerekiyor? Soruyu net yanıtlamak kararı belirledi:

| Ne | Nerede | Neden |
|---|---|---|
| Ham CSV | Disk (`storage/uploads/`) | Değişmez kaynak; içerik hash'i önbellek anahtarı |
| Dataset kaydı (id, dosya, pack, hash, satır sayıları, kalite raporu) | **SQLite** | İşlemsel metadata — klasik OLTP |
| AI analiz önbelleği | **SQLite** | İşlemsel KV |
| **Satır verisi** | *Hiçbir yerde* | Her istekte CSV'den Polars ile yeniden hesaplanıyor |

2026 çerçevesi net: SQLite OLTP (satır tabanlı, işlemsel), DuckDB OLAP (kolon
tabanlı, analitik) — ve *rakip değil, tamamlayıcı*. DuckDB ayrıca Polars
DataFrame'lerini Arrow üzerinden zero-copy okuyor, yani teknik olarak çekici bir
aday.

## Karar

**SQLite + SQLAlchemy 2.0 async (aiosqlite).** Satır verisi kalıcılaştırılmıyor.

## Gerekçe

**Neden DuckDB eklenmedi:**

1. **Analitik mantık tek yerde kalsın.** Tüm hesaplar Polars ifadeleri olarak
   `domain/` katmanında yaşıyor: test edilebilir, sürümlenebilir, pack'in
   parçası. DuckDB eklersek mantık Polars ile SQL string'leri arasında bölünür.
   *"301. rapor için ne yapman gerekir?"* cevabı **"bir Python config nesnesi
   yaz"** olmalı, "yeni SQL sorguları yaz" değil.
2. **Açıklanabilirlik.** İki sorgu motoru = mülakatta iki kez "neden burada
   Polars, neden orada SQL" sorusu.
3. **Q&A bonusunda text-to-SQL kullanmıyoruz.** DuckDB'nin en cazip kullanımı
   LLM'e SQL yazdırmak olurdu — bu "AI sayı hesaplamaz" kuralını
   ([ADR-007](ADR-007-ai-sayi-hesaplamaz.md)) doğrudan ihlal ederdi.

**DuckDB'nin kazanacağı koşul** (bilmediğimiz için değil, gerekmediği için
kullanmadık): veri bellekte rahat durmayı bıraktığında veya raporlar arası
ad-hoc SQL gerektiğinde. Geçiş maliyeti düşük — Polars'ı zero-copy okuyor.

**Neden Postgres değil:** kurulum sürtünmesi. Reviewer `pip install -r
requirements.txt && uvicorn app.main:app` yazıp çalıştırıyor; Docker veya DB
sunucusu kurmuyor. Bu doğrudan "kurulum adımları" kalemine yarıyor.

**Neden SQLAlchemy, iki tablo için fazla değil mi?** Biraz. Karşılığında
Postgres'e geçiş tek satır: `sqlite+aiosqlite://` → `postgresql+asyncpg://`.
Repository katmanı da servisleri sorgu detaylarından ayırıyor.

## AI önbelleği neden gerekli (süs değil)

Önbellek olmadan her dashboard yenilemesi 7 Claude çağrısı demek: demo yavaş,
maliyet boşa, ve ekran görüntüleri arası çıktı değişken olur. Önbellek anahtarı:

```
sha256(içerik_hash | pack | prompt_sürümü | model | effort | çağrı_tipi | ekstra)
```

Model ve prompt sürümü anahtara dahil — Sonnet ile üretilmiş bir analizi Opus'a
geçtikten sonra servis etmek yanıltıcı olurdu.

## Sonuçları

- Uçtan uca async (`aiosqlite`), event loop hiçbir yerde bloklanmıyor.
- Satır verisi yeniden hesaplandığı için süreç içi bir LRU (16 girdi) eklendi.
- Ödün: veri büyürse yeniden hesaplama maliyeti artar. O noktada satır verisi
  kalıcılaştırılıp DuckDB/Postgres'e geçilmeli — mimari buna açık.
