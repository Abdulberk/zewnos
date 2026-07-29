# ADR-009 — Dataset Pack soyutlaması

**Durum:** Kabul edildi

## Bağlam

Ödevin nihai hedefi: *"Üretim/Sevkiyat/ARGE/Muhasebe gibi çeşitli
departmanlardan alınan 300+ farklı raporu 'Yönetici dashboard'u' halinde grafik
ve analizler ile sunabilmek."*

İki uç yaklaşım var:

1. **Her rapor için ayrı kod.** 300 rapor = 300 modül. Bakımı imkânsız.
2. **Tam otomatik şema çıkarımı.** Kolonlara bakıp ne yapılacağını tahmin etmek.
   Kulağa hoş geliyor ama "hangi kolon stok, hangisi maliyet, ne risk sayılır"
   sorularını veri kendi başına yanıtlayamıyor — domain bilgisi gerekiyor.

## Karar

Arada bir yer: **boru hattı domain-agnostik, domain bilgisi tek bir
yapılandırma nesnesinde.**

```python
@dataclass(frozen=True, slots=True)
class DatasetPack:
    key: str
    entity_key: str                    # "stok_kodu"  /  "kampanya_id"
    entity_label_key: str
    period_key: str
    dimensions: tuple[str, ...]
    columns: tuple[ColumnDef, ...]              # ham kolon → kanonik + tip + alias
    derived_metrics: tuple[DerivedMetric, ...]  # satır içi ve pencere metrikleri
    integrity_rules: tuple[IntegrityRule, ...]
    imputation_rules: tuple[ImputationRule, ...]
    risk_rules: tuple[RiskRule, ...]
    period_aggregates / entity_aggregates / dimension_aggregates
    prompt_profile: PromptProfile               # AI'ın dili ve departmanları
    entity_trend_column: str
```

Boru hattının tamamı — okuma, kodlama onarımı, kalite kontrolü, imputasyon,
zaman serisi motoru, risk değerlendirmesi, AI orkestrasyonu, tüm API uçları —
bu nesneyi okuyarak çalışıyor.

## Neden Protocol/ABC değil de frozen dataclass?

Pack bir **davranış** değil, **yapılandırma**. Python'da veri taşıyan bir
soyutlama için Protocol veya ABC yazmak gereksiz tören olur ve NestJS/Java
alışkanlığını Python'a taşımak demektir.

`Protocol` gerçekten takas edilebilir davranış için saklandı:

| Soyutlama | Tip | Neden |
|---|---|---|
| `DatasetPack` | `frozen dataclass` | Veri. Farklı "implementasyonu" yok, farklı *örneği* var |
| `LLMClient` | `Protocol` | Gerçek davranış: test sahtesi, farklı sağlayıcı, ileride bir orkestrasyon katmanı |

İfadeler `pl.Expr` olarak değil, `Callable[[PackContext], pl.Expr]` olarak
saklanıyor. Sebep: pencere fonksiyonlarının `.over(entity_key)` demesi gerekiyor
ve `entity_key` pack'ten pack'e değişiyor.

## Kanıt: aynı motor, iki farklı rapor

`sonart-erp` (ERP stok) ve `zewnos-ads` (Meta reklam) pack'leri yazıldı. İkinci
pack ~330 satır ve motora, endpoint'lere, AI katmanına hiç dokunmadı.

Aynı motorun reklam verisinde bulduğu şeyler:

| Kampanya | Bulgu |
|---|---|
| K011 | `AD_FATIGUE` — frekans 1,6→4,3, CTR %1,50→%0,46, ROAS 1,17→0,33 |
| K006 | `SCALING_INEFFICIENCY` — harcama +%200, ROAS 0,80→0,49 |
| K005 | `STAR_SCALE_UP` — ROAS sabit 5,0, kitle doymamış |
| K001 | `EFFICIENT_GROWTH` — harcama 4,25x arttı, ROAS 3,28'de sabit |

Son satır jenerikliğin kalitesini gösteriyor: motor *"her harcama artışı
kötüdür"* demiyor; K006'nın artışını verimsiz sayarken K001'in artışını sağlıklı
büyüme olarak ayırıyor.

Ayrıca dosya yüklenirken pack belirtmek zorunlu değil — başlıklardan tespit
ediliyor (`registry.detect_pack`).

## "301. rapor için ne yapmak gerekir?"

1. Yeni bir `DatasetPack` örneği yaz (kolonlar, metrikler, kurallar, prompt
   profili).
2. `app/services/registry.py` içine kaydet.

Motor, endpoint'ler, AI katmanı, testler değişmez.

## Değerlendirilen alternatifler

| Alternatif | Neden elendi |
|---|---|
| Rapor başına ayrı modül | 300 rapor ölçeğinde bakımı imkânsız |
| Tam otomatik şema çıkarımı | "Ne risk sayılır" sorusu domain bilgisi gerektiriyor; veri kendi başına yanıtlayamaz |
| YAML/JSON ile yapılandırma | Metrikler ve kurallar Polars ifadeleri — kod olarak kalmalı ki tip güvenli ve test edilebilir olsun. YAML'da ifade yazmak DSL icat etmek olurdu |
| Pack'i Protocol yapmak | Veri taşıyan bir soyutlama için gereksiz tören |

## Sonuçları

- Yeni rapor eklemek yapılandırma işi, mühendislik işi değil.
- Pack'ler tek başına test edilebiliyor; motorun jenerikliği ayrı bir testle
  sabitlendi (`test_ayni_motor_iki_pack_ile_calisir`).
- Ödün: pack sözleşmesi (`base.py`) öğrenilmesi gereken bir soyutlama. Yeni
  gelen biri önce bu dosyayı okumalı. Karşılığında 300 modül okumaktan
  kurtuluyor.
- **Sınır:** çok farklı yapıdaki raporlar (örneğin dönem kavramı olmayan,
  hiyerarşik veya olay bazlı) mevcut sözleşmeye sığmaz. O noktada pack tipi
  ailelere ayrılmalı.
