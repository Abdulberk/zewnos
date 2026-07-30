# Sonart Insight — ERP Raporundan Yönetim Dashboard'una

> **Teknik olmayan okuyucu için özet.** Bu uygulama, Logo Netsis gibi bir ERP sisteminden alınan aylık stok/satış raporunu (CSV) alıp yönetime hitap eden bir analize çeviriyor. Önce veriyi temizliyor — bozuk Türkçe karakterleri onarıyor, kopya satırları siliyor, eksik satırları veri setinin kendi mantığından hesaplayıp tamamlıyor. Sonra 6 ayın tamamına bakarak tek bir aya bakınca **görünmesi imkânsız** olan sorunları buluyor: 5 aydır tükenmiş ama kârlı bir ürün, sessizce her ay 40 adet biriken bir stok, maliyeti %22 artınca marjı yarıya inen bir kalem. En sonunda yapay zekâ bu bulguları her ay için ayrı ayrı yorumlayıp "kim, ne zaman, ne yapmalı" diye somut aksiyona çeviriyor.
>
> **Ekranlarda ne görüyoruz:** üstte son dönemin KPI'ları, altında 6 aylık trend grafikleri, yanında sıralanmış risk sicili ve her riskin parasal etkisi, ayrıca "veri kalitesi" paneli — hangi sorunun bulunduğu *ve ne yapıldığı*.
>
> **İş tarafına ne söylüyor:** örnek veride motor 18 risk buldu. En büyük üç kalem: U005 Barcelona'da 5 aydır süren tükenme nedeniyle **~33.500 TL kaçırılan ciro**, U004 Marbella'da **~36.300 TL ölü stokta bağlı sermaye**, ve U007 Cortina'da maliyet şoku sonucu **12,4 puan eriyen marj**. Üçü de tek dönemlik bir rapora bakarak görülemezdi.

---

## Depolar ve çıktılar

| | |
|---|---|
| **Backend (bu depo)** | <https://github.com/Abdulberk/zewnos> |
| **Frontend** | <https://github.com/Abdulberk/erp-fe> — Next.js dashboard |
| **Örnek çıktı** | [`docs/ornek-rapor.pdf`](docs/ornek-rapor.pdf) — gerçek veriyle üretilmiş yönetici raporu |
| **API arayüzü** | Kurulumdan sonra <http://localhost:8000/docs> — 14 ucun tamamı denenebilir |

### Ekran görüntüleri

Aşağıdaki kareler örnek veriyle (`sonart_erp_bozuk_encoding.csv`) çalışan
uygulamadan alınmıştır.

**Genel bakış** — son dönemin KPI'ları, 6 aylık trend grafikleri ve en kritik
riskler. Ciro (TL) ile marj (%) farklı ölçekler olduğu için bilerek ayrı
grafiklerde, ortak x ekseniyle.

![Dashboard: KPI kartları ve 6 aylık trend grafikleri](docs/screenshots/01-dashboard.png)

**Veri kalitesi** — her bulgu, *ne yapıldığı* rozetiyle birlikte. Bozuk
karakter kodlaması onarımının öncesi/sonrası örnekleri burada görünüyor.

![Veri kalitesi paneli: bulgular ve yapılan işlemler](docs/screenshots/02-veri-kalitesi.png)

**Risk sicili** — parasal etkiye göre sıralı 18 risk. Açılan kayıtta gerekçe,
öneri ve her iddianın dayandığı hesaplanmış sayılar.

![Risk sicili: parasal etki grafiği ve kanıtlar](docs/screenshots/03-risk-sicili.png)

**Dönemsel AI analizi** — altı dönemin her biri için ayrı hikâye ve aksiyonlar.
`delta_vs_prev` şemada zorunlu olduğu için model her dönemde *ne değiştiğini*
söylemek zorunda; dönemsel farklılaşma bu sayede görünür.

![Dönemsel AI analizi: yönetici özeti ve döneme özgü aksiyonlar](docs/screenshots/04-donemsel-analiz.png)

**Soru-cevap** — serbest soru, kanıtlı yanıt, güven rozeti ve kanıt doğrulama
oranı.

![Soru-cevap: kanıtlı yanıt ve doğrulama oranı](docs/screenshots/05-soru-cevap.png)

---

## Kurulum

Gereken: **Python 3.12+**. Docker, veritabanı sunucusu veya başka bir servis gerekmiyor.

```bash
# 1. Depoyu alın
git clone https://github.com/Abdulberk/zewnos.git && cd zewnos

# 2. Sanal ortam
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# 3. Bağımlılıklar
pip install -r requirements.txt

# 4. Yapılandırma — .env.example'ı kopyalayıp API anahtarınızı girin
copy .env.example .env          # Windows
cp .env.example .env            # macOS / Linux

# 5. Çalıştırın
uvicorn app.main:app --reload
```

Ardından <http://localhost:8000/docs> → `POST /api/v1/datasets` ile
`data/samples/` altındaki örnek CSV'lerden birini yükleyin.

`.env` içinde tek zorunlu alan `ANTHROPIC_API_KEY`. Anahtar olmadan da uygulama
açılır; veri işleme, dashboard ve PDF export çalışır, yalnızca AI uçları
`503 ai_not_configured` döner.

### Örnek veriler

| Dosya | İçerik |
|---|---|
| `sonart_erp_cok_donemli.csv` | ERP stok/satış raporu (15 ürün × 6 dönem) |
| `sonart_erp_bozuk_encoding.csv` | Aynı veri, bozuk karakter kodlamasıyla |
| `zewnos_meta_ads_cok_donemli.csv` | Meta/Instagram reklam raporu (Track A verisi) |

### Testler

```bash
pip install -r requirements-dev.txt
pytest              # 106 test
lint-imports        # katman sınırı sözleşmeleri
ruff check app tests
```

---

## Hangi track ve neden

**Track B — Sonart Tekstil.** Üç sebep:

1. **Ödev metni asıl önceliği söylüyor:** *"300+ farklı raporu 'Yönetici
   dashboard'u' halinde sunabilmek nihai hedefimiz — bu ödev bunun küçük
   ölçekli bir simülasyonudur."* Bu cümle Track A için yazılmamış. B'yi seçmek
   verilen ödevi yapmak değil, asıl problemi anlamak demek.
2. **Verinin kendisi zaman serisi analizini zorunlu kılıyor.** Örnek veride tek
   dönemlik bakışla görülemeyecek üç ayrı sinyal var (arz kısıtı, sessiz stok
   birikimi, marj erozyonu). Ödev de bunu istiyor: *"Statik, tek dönemlik bir
   özet yeterli değildir."*
3. **Veri kalitesi tarafı daha zengin:** karakter kodlaması bozukluğu, kopya
   kayıt, eksik satır ve stok mutabakatı ihlali — dördü birlikte.

**Ama mimari her iki track'i de kaldırıyor.** `zewnos-ads` pack'i de yazıldı ve
Track A'nın CSV'si aynı motorla, tek satır kod değişikliği olmadan işleniyor —
aşağıdaki "Jeneriklik kanıtı" bölümünde.

---

## Mimarinin iki taşıyıcı fikri

### 1. Dataset Pack — motor rapordan bağımsız

Boru hattının tamamı rapor tipini bilmiyor:

```
CSV baytları
  → kodlama tespiti + mojibake onarımı
  → başlık eşleme + tip dönüşümü
  → veri kalitesi (kopya / eksik / bütünlük)
  → eksik değer tamamlama
  → zaman serisi motoru (türetilmiş metrikler, özetler, deltalar)
  → risk değerlendirmesi
  → AI orkestrasyonu (dönem analizleri → yönetici sentezi)
```

Bir rapora özgü olan **her şey** tek bir yapılandırma nesnesinde toplanıyor
([`app/domain/packs/base.py`](app/domain/packs/base.py)):

```python
@dataclass(frozen=True, slots=True)
class DatasetPack:
    key: str
    entity_key: str                    # "stok_kodu"  /  "kampanya_id"
    period_key: str                    # "donem"
    dimensions: tuple[str, ...]        # kategori, depo  /  platform, kategori
    columns: tuple[ColumnDef, ...]     # ham kolon → kanonik ad + tip
    derived_metrics: ...               # marj_yuzde, kapama_ay  /  roas, ctr
    integrity_rules: ...               # stok mutabakatı  /  tıklama ≤ gösterim
    imputation_rules: ...              # eksik değeri nereden türeteceğiz
    risk_rules: ...                    # stockout, ölü stok  /  kitle yorulması
    period_aggregates / entity_aggregates / dimension_aggregates: ...
    prompt_profile: PromptProfile      # AI'ın konuşacağı dil ve departmanlar
```

**"301. rapor için ne yapmak gerekir?"** → Bir Python nesnesi yazmak. Motora,
endpoint'lere, AI katmanına dokunmak gerekmiyor.

Pack neden `Protocol` değil de `dataclass`? Çünkü pack bir *davranış* değil,
*yapılandırma*. Python'da veri taşıyan bir soyutlama için Protocol/ABC yazmak
gereksiz tören olur. `Protocol` gerçekten takas edilebilir davranış için
saklandı: `LLMClient` (test sahtesi, farklı sağlayıcı) — bkz.
[ADR-009](docs/decisions/ADR-009-dataset-pack.md).

### 2. Sayıyı Polars hesaplar, AI yorumlar

Modele **ham CSV asla verilmiyor**. AI'ın gördüğü her sayı Polars tarafından
hesaplanmış ve `app/ai/context.py` üzerinden geçmiş durumda. Model hesaplayamaz,
çünkü hesaplayacağı ham veriye erişimi yok.

Üstüne **iki katman zorlama** var:

1. **Şema seviyesinde** — her aksiyon en az bir kanıt taşımak zorunda:
   ```python
   class Action(BaseModel):
       evidence: list[Evidence] = Field(min_length=1)   # boş liste reddedilir
   ```
2. **Doğrulama seviyesinde** — modelin yazdığı her `(metrik, kayıt, dönem, değer)`
   dörtlüsü hesaplanmış tablolarda aranıp karşılaştırılıyor. Sonuç bir
   **grounding oranı** olarak API yanıtında dönüyor.

Örnek veride ölçülen: **%100 (127/127 kanıt doğrulandı).**

---

## Veri kalitesi — ne bulundu, ne yapıldı

Ödev *"örnek veri gerçek bir ERP export'u gibi küçük kusurlar içerebilir"*
diyor. Bulunanlar ve **her biri için yapılan işlem**:

| Bulgu | Örnek veride | Yapılan |
|---|---|---|
| **Karakter kodlaması bozukluğu (mojibake)** | `Marbella DÃ¶ÅŸemelik Deri` → `Marbella Döşemelik Deri` | **onarıldı** (6 değer) |
| Birebir kopya satır | U001 / 2026-02 iki kez | **silindi** |
| Aynı dönem için çelişen kayıt | — | son kayıt alınır, işaretlenir |
| Eksik zorunlu alan | U010 / 2026-04 tamamen boş | **türetildi** → 5180 |
| Belirsiz imputasyon | ileri 5180 / geri 5160 | **işaretlendi** (aşağıda) |
| Stok mutabakatı ihlali | `t-1 sonu + giriş − çıkış ≠ t sonu` | işaretlenir, sapma miktarıyla |
| Birim maliyette ani sıçrama | U007 Mart **+%36**, U004 Nisan +%11 | işaretlendi |
| Geçersiz dönem formatı | — | **karantina** |
| Negatif miktar / maliyet ≥ satış | — | **kritik** işaretlenir |
| Dönem boşluğu | — | işaretlenir, trend güvenilirliği düşer |
| Tanımsız kolon | — | yok sayılır, raporlanır |

### En ilginç bulgu: veri setinin kendisi tutarsız

U010 / 2026-04 satırının tüm miktarları boş. Stok mutabakatından **iki yönde**
hesapladım:

- **İleri** (Mart'tan): `5160 + 700 − 680 = 5180`
- **Geri** (Mayıs'tan): `5180 − 700 + 680 = 5160`

İkisi uyuşmuyor. Yani eksik satır komşu dönemlerle çelişiyor — kaynak sistemde
gerçek bir tutarsızlık var. Yapılan: ileri yöndeki değeri kullanıp durumu
`IMPUTATION_AMBIGUOUS` olarak **açıkça raporlamak**. Sessizce birini seçip
geçmek yanlış olurdu.

Bu tutarsızlık teste de yazıldı — gizlenmiyor, sabitleniyor:

```python
def test_mutabakat_tek_bilinen_tutarsizlik_disinda_tutar(...):
    # 75 satırın 74'ü kuruşu kuruşuna tutuyor; tek sapma U010/2026-05'te -20
    assert (row["stok_kodu"], row["donem"]) == ("U010", "2026-05")
    assert row["mutabakat_farki"] == pytest.approx(-20.0, abs=0.01)
```

### Veri sağlık puanı iki boyutlu

Sorunu bulmak yeterli değil; **çözülüp çözülmediği** de puana giriyor. Otomatik
onarılan/türetilen/temizlenen bir sorun tam puan kırmıyor (%40 ağırlıkla),
yalnızca işaretlenip bırakılan veya karantinaya alınan sorunlar tam ağırlıkla
düşüyor. Örnek veri: **67/100** (mojibake'li dosya), **69/100** (temiz dosya).

---

## Dönemsel farklılaşma — nasıl sağlandı

Ödevin en net şartı: *"Statik, tek dönemlik bir özet yeterli değildir."*
Bunu **üç ayrı katmanda** zorunlu kıldım.

### 1. Veri katmanı: tek dönemde görülemeyen 10 hesap

| Hesap | Örnek veride | Tek dönem neden yetmez |
|---|---|---|
| MoM değişim | U011 çıkış 22→27→36→45→**117**→81 | Tek ay "81 sattı" der; seri "talep 5x hızlandı" der |
| **Marj serisi** | U007: %42,9→%41,9→**%21,0**→%23,3→%26,7→%30,5 | Mart'ta maliyet şoku olmuş, hâlâ toparlanmamış |
| Stok kapama ayı | U004: 4030 ÷ 295 = **13,7 ay** | Paydası hareketli ortalama |
| Tükenme projeksiyonu | U013: her ay net −20, **~8 ay sonra biter** | Tamamen ileriye dönük |
| Stok mutabakatı | `t-1` ile `t` karşılaştırması | Tanımı gereği iki dönem gerektirir |
| **Arz kısıtı** | U005: 5 dönem stok 0, çıkış = giriş = 77 | Tek ay "77 sattı" der; seri "**77 satabildi**" der |
| Mevsimsel tepe | U006: 195→218→310→**356**→322→241 | Nisan zirvesi |
| **Sessiz birikim** | U002: her ay +40, stok 740→940 | Hiçbir tek dönem alarm vermez |
| Talep hızlanması | U011: ilk3 ort. 28,3 → son3 ort. 81 | Oranın kendisi seri gerektirir |
| Ölü stok / yavaş hareket | U004, U001, U009, U010 | Hareket hızı seriden çıkar |

**"U005'te satış 77 değil, satabildiğimiz 77."** Bu ayrım tek dönemlik bir
rapordan çıkmaz.

### 2. Risk katmanı: her riskin "ne zaman başladığı" hesaplanıyor

Entity seviyesi riskler tüm seriye bakarak bulunuyor, dolayısıyla doğal bir
dönemi yok. Bunları son döneme yığmak yerine **ilk görülme dönemini**
hesaplattım. Sonuç — her ayın kendi hikâyesi:

| Dönem | O dönemde **ilk kez** açılan riskler |
|---|---|
| 2026-01 | `DEAD_STOCK` (U004), `SLOW_MOVER`, `STOCKOUT_IMMINENT` (U007) |
| 2026-02 | `STOCKOUT` — U005 tükendi |
| 2026-03 | `COST_SHOCK` + `MARGIN_EROSION` — U007'de maliyet şoku |
| 2026-04 | `STOCKOUT` (U003), `DEMAND_SURGE` (U011), `SEASONAL_PEAK` (U006) |
| 2026-05 | `STOCKOUT_IMMINENT` (U013), `SEASONAL_PEAK` (U011) |
| 2026-06 | — (yeni risk yok; mevcut riskler çözülmemiş) |

Trend bazlı riskler (`SILENT_ACCUMULATION`, `DYING_SKU`) için `first_seen`
bilinçli olarak **`None`** — tek bir başlangıç dönemi yok, uydurmak yanlış olur.

### 3. AI katmanı: şema modeli farklılaşmaya mecbur bırakıyor

`PeriodAnalysis` şemasında **zorunlu** bir alan var:

```python
delta_vs_prev: str = Field(
    description="Bir önceki döneme göre somut olarak ne değişti. "
                "Genel ifade değil, sayıya dayalı fark."
)
```

Ayrıca her dönem çağrısına o dönemin hesaplanmış delta tablosu, en çok
artan/azalan kayıtlar ve o dönemde açılan riskler veriliyor. Gerçek çıktıdan
(kısaltılmış):

> **2026-02** — *"U005 Barcelona stokları tükendi, çıkış 91 adet düştü ve
> portföy ilk stockout riskini kaydetti. Ciro 174.810 TL'den 169.794 TL'ye
> geriledi."*
>
> **2026-03** — *"U007'de maliyet şoku marjı çökerten, U005 ve U003'te stok
> tükenmesi devam eden bir dönem. Birim maliyet %21,67 artarak 146 TL'ye
> oturdu, marj %42,86'dan %30,48'e düştü."*
>
> **2026-05** — *"Ciro hafif yükselirken U013'te stoksuzluk riski başladı ve
> U011'de mevsimsel talep patlaması stoğu zorluyor. Kapama süresi 1,23 aya
> düştü."*

Yönetici özeti altı dönemi bir hikâyeye bağlıyor:

> *"Şubat ve Mart ayları dönüm noktaları oldu — Şubat'ta tedarik kısıtı başladı,
> Mart'ta maliyet şoku marj baskısına dönüştü ve bu iki sorun Haziran'a kadar
> çözülmeden taşındı."*

---

## Stack ve AI API seçimi

### Backend: FastAPI + Polars + Pydantic v2 + SQLite

| Karar | Gerekçe | Elenen alternatif |
|---|---|---|
| **FastAPI** | Async-first, Pydantic v2 ile doğal uyum, OpenAPI'den frontend'e tipli client üretimi | **Litestar** — teknik olarak iddialı (msgspec, daha temiz DI) ama ekosistem ve işe alım riski yüksek |
| **Polars** | Asıl sebep hız değil: null'ı `NaN`'dan ayıran veri modeli (eksik satır işi için kritik), `.over()` ile grup sınırı güvenliği, lazy API ile gerçek ölçekleme cevabı | **pandas** — daha tanıdık ama sessiz dtype dönüşümleri (eksik tamsayı → float/NaN) ve grup sınırı hatalarına daha açık |
| **Pydantic v2** | FastAPI'nin kendisi üzerine kurulu; Anthropic SDK'sının structured output'u Pydantic modeli alıyor — ikisi de yapısal zorunluluk | **msgspec** — 2-5x hızlı ama sadece tip doğruluyor ve iki entegrasyonu da kaybettirir. 91 satırda hız alakasız |
| **SQLite + SQLAlchemy 2.0 async** | Kurulum sıfır. Postgres'e geçiş tek satır: URL değişimi | **DuckDB** — analitik için doğru araç ama satır verisini kalıcılaştırmadığımız için sorgulayacağı bir şey yok; analitik mantığı Polars ile SQL arasında bölerdi |

Satır verisi **kasten** saklanmıyor: ham CSV diskte duruyor, her istekte Polars
ile yeniden hesaplanıyor (milisaniyeler) ve süreç içi bir LRU tekrarı önlüyor.
Böylece analitik mantığın tek kaynağı kod olarak kalıyor.

**`.over()` neden bu kadar vurgulanıyor?** Zaman serisi analizinin 1 numaralı
hatası, `shift(1)` yaparken bir ürünün son ayından bir sonraki ürünün ilk ayına
değer taşımak. Hata sessizdir: sonuç üretilir ama yanlıştır. Polars'ta grup
bağlamı ifadenin *içinde* yazılıyor, unutulamıyor:

```python
pl.col("donem_sonu_stok").shift(1).over(ctx.entity_key)
```

Ve bu bir testle sabitlendi — her ürünün ilk döneminde `onceki_stok` null olmalı.

### AI: Claude API

Üç somut sebep, üçü de "AI entegrasyonunun kalitesi" kalemine çalışıyor:

1. **Structured outputs** — `client.messages.parse(output_format=PydanticModel)`
   ile çıktı JSON şemaya *zorlanıyor*; şema uymazsa yeniden deneniyor.
   "Bazen düzgün JSON döndü bazen dönmedi" problemi hiç doğmuyor.
2. **Prompt caching** — 6 dönem çağrısı aynı ~13K token'lık bağlamı paylaşıyor.
   Sabit prefix cache'lenip tekrar okumalar ~%10 fiyata düşüyor.
3. **Türkçe kalitesi ve 1M context** — tüm rapor seti tek prompt'a sığıyor;
   "300+ rapor" senaryosunda önemli.

### Model seçimi ve maliyet — ölçüldü

Aynı dönem, aynı bağlam, `effort=medium`, tek değişken model:

| | Opus 5 | Sonnet 5 |
|---|---|---|
| Çıktı token | 3.279 | 2.197 |
| Süre | 53 sn | **24 sn** |
| Tek çağrı | $0,167 | **$0,056** |
| **Tam analiz (7 çağrı)** | **~$0,72** | **~$0,22** |
| Grounding | %100 | %100 |

> Tam analiz rakamları prompt önbelleğinin tamamen ısınmış olduğu durumu
> gösteriyor (7/7 isabet). Soğuk koşuda paylaşılan bağlam bir kez yazıldığı
> için maliyet yükseliyor: son ölçülen soğuk Sonnet koşusu **$0,3547**
> (5/7 isabet, 115 sn, grounding %100). Aradaki fark bir sonraki bölümde
> anlatılan önbellek sırasının neden önemli olduğunu da gösteriyor.

Sonnet 5 **~3x ucuz ve 2x hızlı**. İlk ölçümde bir kalite farkı da vardı:
Sonnet bir **dönemsel atıf hatası** yaptı — 2026-03 analizinde U003 için
*"3 dönemdir stok sıfır"* dedi; oysa U003'ün Mart stoğu 30, sıfıra Nisan'da
düştü. Tüm seriye ait toplamı (`sifir_stok_donem=3`) tek bir döneme yapıştırdı.

**Ama incelediğimde bu bir model kapasitesi sorunu değil, benim prompt hatam
çıktı** (ayrıntısı aşağıda, "en çok zorlandığım nokta"). Düzelttikten sonra
Sonnet aynı dönemde şunu yazıyor:

> *"Tükenen ürün sayısı 1'de sabit kaldı (Barcelona), ancak Havana da 30 adede
> kadar erimiş durumda."* — ve bir sonraki dönemde: *"U003 bu dönemde **ilk kez**
> stok sıfıra düştü."*

**Karar:** varsayılan Sonnet 5 + medium. Opus 5 hâlâ aksiyonlar arasında daha
iyi bağ kuruyor (*"fiyat kararı verilirken stok da bitiyor, ikisi aynı sipariş
dalgasında ele alınmalı"*) ve daha fazla aksiyon üretiyor; teslim edilecek nihai
analiz için `AI_MODEL=claude-opus-5` yapmak yeterli. Önbellek anahtarı modeli ve
prompt sürümünü içeriyor — farklı bir modelle veya eski prompt'la üretilmiş bir
analiz yanlışlıkla servis edilmiyor.

---

## Neden orkestrasyon framework'ü (LangGraph/LangChain) kullanılmadı

Akışın şekli statik iki katmanlı bir DAG:

```
N dönem analizi (paralel, bağımsız)  →  1 yönetici sentezi
```

Döngü yok, koşullu dallanma yok, insan onayı adımı yok, uzun süreli resume
ihtiyacı yok. LangGraph'ın verdiği state machine / checkpointing / conditional
edge / cycle karşılıkları burada yok. Karşılığı `asyncio.gather` + bir semafor.

Maliyeti ise gerçek olurdu: iki kritik özelliğimiz (structured outputs, prompt
caching) Anthropic'e özgü ve framework sarmalayıcıları sağlayıcıya özgü
özellikleri geriden takip ediyor. Prompt caching wrapper üzerinden çalışmazsa
yukarıdaki maliyet argümanı çöker.

**Orkestratörü yazdım, import etmedim.** Framework'ün değerli parçaları —
akışın açıkça görünmesi, telemetri, yeniden deneme, hata izolasyonu — elle ve
~180 satırda sağlandı ([`app/ai/orchestrator.py`](app/ai/orchestrator.py)).
`LLMClient` bir `Protocol` olduğu için yarın gerekirse LangGraph bu dikişin
arkasına takılır; `domain/` ve `services/` hiç değişmez.

Dogmatik değil: framework'ün haklı olacağı koşul çok adımlı, dallanan, semantik
başarısızlıkta geri dönen, insan onayı içeren akışlardır. Bizimki değil.
Detay: [ADR-008](docs/decisions/ADR-008-no-orchestration-framework.md).

---

## En çok zorlandığım nokta

**Prompt caching ile paralellik birbirini yiyordu — ve telemetri olmadan
görünmüyordu.**

6 dönem analizini `asyncio.gather` ile paralel salıyordum: hızlı ve doğru
çalışıyor gibiydi. Ama her AI çağrısının token kırılımını loglayınca şu çıktı:

```
cache_write = 90.657 token     cache_read = 0     isabetli çağrı = 0/7
```

Yedi çağrının **hepsi** cache'i yazmış, hiçbiri okumamıştı. Sebep: bir önbellek
girdisi ancak onu yazan isteğin yanıtı akmaya başladıktan sonra okunabilir hale
geliyor. Hepsini aynı anda salınca hiçbiri diğerinin yazdığını göremiyor ve
~13K token'lık bağlamın yazma ücreti (~1,25x giriş) yedi kez ödeniyor.

Çözüm: **ilk çağrıyı tek başına bekle, sonra kalanları paralel sal.**

```python
head, *rest = result.periods
first = await self._safe_period(head, ...)                    # önbelleği yazar
remaining = await asyncio.gather(*(... for period in rest))    # okur
```

Ölçülen sonuç:

| | Önce | Sonra |
|---|---|---|
| cache yazma | 90.657 | **12.951** (1 kez) |
| cache okuma | 0 | **77.706** |
| isabetli çağrı | 0/7 | **7/7** |
| maliyet | $0,398 | **~$0,22** |
| duvar saati | 93 sn | 106 sn |

**~%45 tasarruf**, karşılığında 13 saniye. Kabul edilebilir takas — ve sonuç
önbelleğe yazıldığı için bu bedel veri seti başına bir kez ödeniyor.

Buradan çıkan ders: **önbellek varsayılmaz, ölçülür.**
`usage.cache_read_input_tokens` sıfır kalıyorsa sessiz bir geçersizleştirici
var. Telemetriyi baştan yazmasam bu hatayı hiç görmezdim.

**İkinci zorluk daha ince: kendi doğrulayıcım yok yere alarm veriyordu.**
Grounding %88'de takılıydı. İncelediğimde hataların modelde olmadığı ortaya
çıktı — model *"Çantalık kategorisinin marjı %31,36"* diye doğru alıntı
yapıyordu ama `FactIndex` boyut kırılımını hiç indekslemiyordu, dolayısıyla
portföy geneline düşüp "sapma" raporluyordu. Ayrıca model bazen Türkçe
karakterleri ASCII'ye düşürüyordu (`Dosemelik` / `Döşemelik`) — bu bir
halüsinasyon değil, yazım farkı. İkisi düzeltildikten sonra **%100**.

**Üçüncü zorluk aynı dersin tekrarı: "modelin hatası" sandığım şey yine benim
hatamdı.** Sonnet, 2026-03 analizinde U003 için *"3 dönemdir stok sıfır"* dedi —
Mart stoğu 30'du. İlk refleks "daha güçlü model kullan" oldu. Ama bakınca sebep
netti: modele **entity özet tablosunu** veriyordum (tüm seriye ait toplamlar,
`sifir_stok_donem = 3` gibi) ama o döneme ait kayıt bazlı değerleri **hiç
vermiyordum**. Model dönem bazlı bir sayıya ihtiyaç duyunca elindeki tek şeyi
ödünç aldı. Yapması gereken de buydu; ben vermemiştim.

İki düzeltme, ikisi de bedava:

1. Her dönem sorusuna **o dönemin anlık görüntü tablosu** eklendi
   (`pack.snapshot_columns`) — model artık U003'ün Mart stoğunun 30 olduğunu
   doğrudan görüyor.
2. İki tablo da **kapsamıyla etiketlendi**: *"TÜM DÖNEMLERİN TOPLAMI"* vs
   *"SADECE BU DÖNEMİN DEĞERLERİ"*, ve sistem promptuna kapsam kuralı girdi.

Ek maliyet dönem başına ~250 token — tam koşuda **$0,003**. Düzeltmeden sonra
model kapsam ayrımını kendiliğinden yapıyor: *"önce genel seri ortalaması %30,48
idi, **bu dönemin anlık değeri** ondan da kötü."*

Aynı koşuda ikinci bir yanlış alarm daha çıktı: model *"Çantalık kategorisinin
cirosu 44.560 TL"* diye **doğru** bir sayı yazdı ama `Evidence.entity` alanını
boş bıraktı — çünkü alanın açıklaması *"kayıt kodu, ya da portföy geneliyse
boş"* diyordu ve bir kategori ikisi de değildi. Doğrulayıcı portföy toplamıyla
karşılaştırıp sapma raporladı. Çözüm: alana kırılım için yuva açmak.

**Dördüncü zorluk en öğreticisi: grounding %100 iken bir cümle hâlâ
yanlıştı.**

Teslim öncesi iki ayrı veri setinde koşu yaptım; ikisinde de doğrulayıcı
**%100** dedi (127/127 ve 118/118). Yine de anlatının tamamını ayrı bir
denetimden geçirdim: düzyazıdaki her sayıyı hesaplanmış 822 değere karşı
aradım. Koşulardan **birinde** Mart analizinde şu cümle çıktı:

> *"U007 Cortina: birim maliyet bu dönem 166 TL'ye sıçradı ve marj
> **%30,5**'ten %21,0'e düştü."*

U007'nin gerçek marj serisi: 42,86 → 41,90 → **20,95** → 23,33 → 26,67 → 30,48.
Yani Mart'ta marj **%41,9**'dan %21,0'e düşmüştü. Model'in yazdığı %30,5 ise
`son_marj_yuzde` — serinin **Haziran** değeri.

Doğrulayıcı bunu neden yakalayamadı? Çünkü **yakalayamaz**: 30,48 tablolarda
gerçekten var. Grounding her rakamın *var olduğunu* doğrular, o rakamın *doğru
yere konduğunu* değil. Üstelik bu iddia `evidence` alanında değil, düzyazıda —
doğrulayıcı yalnızca kanıt kalemlerine bakıyor.

Sebep yine bendeydi: `delta_vs_prev` alanı *"geçen döneme göre ne değişti"* diye
bir **karşılaştırma** istiyor, ama modele sadece **o dönemin** anlık görüntüsünü
veriyordum. Kayıt bazında elindeki tek diğer sayı seri özeti (`ilk_*`, `son_*`)
olunca, karşılaştırmanın "önce" tarafını oradan aldı. Üçüncü zorluğun aynısı,
bir adım ötesi: o zaman *bu* dönemi vermiştim, *önceki* dönemi hiç vermemişim.

Düzeltme:

1. Dönem sorusuna **bir önceki dönemin anlık görüntüsü** eklendi, açıkça
   *"KARŞILAŞTIRMA TABANI"* diye etiketlendi.
2. Sistem promptuna kural `1c` girdi: *"`ilk_*` ve `son_*` kolonları serinin
   ilk/son dönemine aittir; 'geçen dönem' anlamına GELMEZ."*
3. İki test bunu kilitledi: dönem sorusu tabanı içermeli, ilk dönemde
   içermemeli ([`tests/unit/test_ai_validation.py`](tests/unit/test_ai_validation.py)).

Kritik ayrıntı: **aynı prompt, aynı model, iki koşu — birinde hata var,
diğerinde yok.** Diğer koşuda model aynı sayıyı doğru kullandı, hatta kapsamını
kendisi etiketledi: *"serinin dönem sonu marjından (%30,48) bile daha kötü bir
nokta."* Aralıklı olması hatayı önemsiz yapmıyor, tam tersi: **belirsizlik,
promptta bir boşluk olduğunun işareti.** Model bazen doğru tahmin ediyordu,
çünkü tahmin etmek zorundaydı.

Ölçülen ek yük: dönem başına ~370 token, tam koşuda **$0,004**.

Ders (dört kez öğrenildi): **doğrulama katmanı da bir yazılımdır ve o da hata
yapar** — üstelik hata yapmadığında bile *neyi doğrulamadığını* bilmek gerekir.
Grounding %100, "her sayı gerçek" demektir; "her cümle doğru" demek değildir.
"AI hata yaptı" demeden önce doğrulayıcıyı doğrulamak, sonra da modele neyi
vermediğimi sormak gerekiyor: bir modelin hatası çoğu zaman ona verilmemiş bir
bilginin izidir. Dört bulgunun dördü de $0 prompt/kod düzeltmesiyle çözüldü;
hiçbiri için daha pahalı bir model gerekmedi.

---

## Jeneriklik kanıtı — aynı motor, farklı rapor

`zewnos-ads` pack'i (Track A'nın verisi) yazıldı. Motor, endpoint'ler, kalite
hattı ve AI katmanı **değişmedi**. Dosya yüklenirken pack bile belirtilmiyor;
başlıklardan tespit ediliyor:

```
POST /api/v1/datasets   (dosya: zewnos_meta_ads_cok_donemli.csv)
→ otomatik tespit: zewnos-ads   ·   91 → 90 satır   ·   15 risk
```

Aynı motorun reklam verisinde bulduğu şeyler:

| Kampanya | Bulgu | Kanıt |
|---|---|---|
| **K011** Kadın Giyim Geniş Kitle | `AD_FATIGUE` — kitle yorulması | Frekans 1,6→**4,3**, CTR %1,50→%0,46, ROAS 1,17→**0,33** |
| **K006** Erkek Ceket | `SCALING_INEFFICIENCY` + `UNPROFITABLE` | Harcama **+%200** (3.120→9.360 TL), ROAS 0,80→0,49 |
| **K005** Kadın Elbise Retargeting | `STAR_SCALE_UP` — bütçe artırılmalı | ROAS sabit **5,0**, frekans 1,5 (kitle doymamış) |
| **K001** Yaz Koleksiyonu | `EFFICIENT_GROWTH` | Harcama 4,25x arttı ama ROAS **3,28'de sabit** |

Son satır önemli: motor *"her harcama artışı kötüdür"* demiyor. K006'nın %200
harcama artışını verimsiz ölçekleme sayarken K001'in 4,25x artışını sağlıklı
büyüme olarak ayırıyor — çünkü ROAS'ı koruyor. Bu ayrım bir testle sabitlendi
(`test_ads_verimli_buyume_yorulmadan_ayrilir`).

---

## Katmanlı mimari — iddia değil, CI kontrolü

`domain/` katmanı `fastapi`, `sqlalchemy` veya `anthropic` **import etmiyor**.
Bunu söylemekle bırakmadım; `import-linter` sözleşmesiyle doğrulanıyor:

```
$ lint-imports
Analyzed 77 files, 229 dependencies.

Katmanlı mimari (api -> services -> domain)   KEPT
Domain katmanı çerçeveden bağımsız            KEPT
AI katmanı storage'a doğrudan erişemez        KEPT

Contracts: 3 kept, 0 broken.
```

İhlal edilirse komut sıfırdan farklı kod döndürür ve build kırılır. Bu sayede
analitik çekirdek hiçbir altyapı ayağa kaldırmadan doğrudan unit test
edilebiliyor.

Yapı Pythonic tutuldu: üçüncü parti DI container yok (FastAPI'nin `Depends`'i
yeterli), ABC mirası yerine `Protocol`, sınıf yerine fonksiyon modülleri, değer
nesneleri için `frozen dataclass`.

```
app/
├─ api/          HTTP ↔ DTO çevirisi (ince), hata handler'ları, DI bağlama
├─ services/     kullanım senaryoları
├─ domain/       ⚠️ çerçeveden bağımsız — CI ile doğrulanıyor
│   ├─ quality/     encoding onarımı + kalite hattı
│   ├─ analytics/   zaman serisi motoru
│   └─ packs/       rapor tanımları (sonart_erp, zewnos_ads)
├─ ai/           Protocol + Claude adaptörü, şemalar, prompt, orkestratör,
│                grounding doğrulaması, telemetri
├─ storage/      SQLAlchemy modelleri + repository'ler
└─ core/         ayarlar, loglama, hata sözleşmesi
```

---

## Testler

**106 test.** Vurgu "yeşil sayısı" değil, *doğru sayıyı* kontrol etmekte:

```python
def test_eksik_donem_sonu_stogu_mutabakattan_turetilir(...):
    """U010/2026-04 tamamen boş.
    Beklenen: önceki dönem sonu (5160) + giriş (700) − çıkış (680) = 5180.
    Bu değer veri setinden bağımsız olarak elle doğrulanabilir.
    """
    assert series_value(clean, "U010", "2026-04", "donem_sonu_stok") == 5180.0
```

Kapsanan alanlar:

- **Encoding:** mojibake gidiş-dönüş onarımı; sağlam Türkçe metne dokunulmaması
  (mekanizma kendini koruyor — `ş` CP1252'de olmadığı için round-trip başarısız
  olur); Windows-1254 dosya; bozuk baytlar
- **Kalite:** kopya, çelişen kayıt, imputasyon doğruluğu, belirsiz imputasyon
  tespiti, karantina, dönem boşluğu, negatif değer, marj tersliği
- **Zaman serisi:** grup sınırı güvenliği (kasıtlı sızma kurulup yakalanıyor),
  marj/kapama hesapları, mutabakat yanlış alarm kontrolü
- **Riskler:** her risk için veriden doğrulanabilir assertion + **sağlıklı
  ürünün yanlış alarm almaması** (U015)
- **AI:** kanıtsız aksiyonun şemadan geçemediği, uydurma değerin/metriğin
  yakalandığı, yuvarlama toleransı, Türkçe karakter normalizasyonu, iç
  kolonların bağlama konmadığı
- **API:** tüm uçlar, hata sözleşmesi (boş dosya → 422 `empty_dataset`, eksik
  kolon → hangi kolonların eksik olduğu, olmayan kayıt → 404), önbellek
  davranışı, PDF, OpenAPI şeması
- **Edge case:** tek dönemli veri, sadece başlık, bozuk sayı, geçersiz dönem

AI testleri para ve ağ harcamıyor: `LLMClient` bir `Protocol` olduğu için sahte
istemci tek satırla enjekte ediliyor (`lambda _: fake_llm`). Sahte istemcinin
kanıtları **gerçek hesaplanmış değerlerden** alınıyor, böylece grounding
doğrulayıcısının kendisi de test ediliyor.

---

## Bonuslar

| Bonus | Durum |
|---|---|
| Anomali / veri kalitesi tespiti | ✅ 11 kural, her biri "ne yapıldı" bilgisiyle |
| Veri üzerinde serbest soru-cevap | ✅ `POST /datasets/{id}/ask` |
| PDF / paylaşılabilir export | ✅ `GET /datasets/{id}/report.pdf` |
| Test yazımı / edge-case | ✅ 106 test |

### Soru-cevap: text-to-SQL **değil**

Modele SQL yazdırmak cazipti ama bu "AI sayı hesaplamaz" kuralını doğrudan
ihlal ederdi. Yerine hesaplanmış tablolar bağlama verilip yorumlatılıyor.
Gerçek çıktı:

> **S:** Marjı en hızlı daralan ürün hangisi ve neden?
>
> **C:** *U007 Cortina Çantalık Deri. Marj %42,86'dan %30,48'e gerileyerek
> −12,38 puan düştü. Bu, birim maliyetin %21,67 artmasına rağmen satış
> fiyatının bu artışı yansıtmamasından kaynaklanıyor.*
>
> güven: yüksek · grounding: **%100** · maliyet: $0,035
> kanıtlar: `ilk_marj_yuzde=42.86`, `son_marj_yuzde=30.48`,
> `marj_degisim_puan=-12.38`, `maliyet_degisim_yuzde=21.67`

### PDF: AI olmadan da çalışır

Rapor önbellekteki AI analizini dahil eder ama **yeni çağrı yapmaz**. AI hiç
çalıştırılmamışsa rapor yalnızca hesaplanmış verilerle üretilir. Türkçe
karakterler için sistem fontu (Arial/DejaVu) gömülüyor — Helvetica'nın WinAnsi
kodlamasında `ş`, `ğ`, `ı` yok.

---

## Production'a taşısam neyi farklı yapardım

Şu an **kasten** yapmadıklarım ve nedenleri:

| Konu | Bugün | Production'da |
|---|---|---|
| **Depolama** | SQLite + diskte CSV | Postgres (metadata) + S3/MinIO (ham dosya) + partitioned satır tablosu. Geçiş: `DATABASE_URL` değişimi |
| **Analitik motor** | Polars eager | Aynı kod `pl.scan_csv()` ile lazy'ye geçer; 10M+ satırda streaming `collect()`. Ad-hoc SQL gerekirse DuckDB (Polars'ı Arrow üzerinden zero-copy okur) |
| **Uzun işler** | İstek içinde (~100 sn) | Celery/RQ + Redis: upload → kuyruk → SSE/webhook bildirimi. 300 rapor senaryosunda zorunlu |
| **AI maliyeti** | Tek tek çağrı + önbellek | Batch API (%50 indirim) toplu analizler için; token bütçesi ve kullanıcı başına kota |
| **Kimlik / yetki** | Yok | OIDC/JWT, multi-tenancy (Postgres row-level security), rapor bazlı yetki |
| **Gözlemlenebilirlik** | Yapılandırılmış JSON log + korelasyon id | OpenTelemetry trace, token/maliyet metrikleri, grounding oranı için alarm (%80 altına düşerse prompt regresyonu var) |
| **Rate limiting** | Yok | Kullanıcı/tenant başına, AI uçlarında ayrı |
| **Prompt yönetimi** | Kodda, sürümlü (`prompt_version`) | Ayrı depo + A/B + eval seti; prompt değişimi önbelleği zaten geçersizleştiriyor |
| **Şema evrimi** | `create_all()` | Alembic migration |
| **Sır yönetimi** | `.env` | Vault / cloud secret manager |

**Ölçek notu:** 91 satırlık veride performans optimizasyonu yapmak sahte olurdu.
Bugün yapılanlar ucuz ve gerçek olanlar: uçtan uca async, paralel AI çağrıları,
prompt caching (ölçülmüş), sonuç önbelleği, chunked CSV okuma, bounded
concurrency, timeout + tipli hata zinciri.

---

## Frontend ile sözleşme

FastAPI'nin ürettiği OpenAPI şemasından Next.js için tipli TypeScript client
üretiliyor — sınırda elle tip yazmak yok:

```bash
# backend çalışırken
curl http://localhost:8000/api/v1/openapi.json -o openapi.json
npx openapi-typescript openapi.json -o src/lib/api-types.ts
```

Backend Python olmasına rağmen frontend tip güvenli. `EntitiesResponse.columns`
alanı tablo başlıklarını (`{name, label, unit}`) taşıyor, böylece frontend kolon
etiketlerini kendi içinde tekrar tanımlamıyor.

---

## API özeti

| Uç | Ne yapar |
|---|---|
| `POST /api/v1/datasets` | CSV yükle → kodlama onarımı, kalite raporu, analiz |
| `GET /datasets/{id}/quality` | Veri kalitesi raporu (bulgu + yapılan işlem) |
| `GET /datasets/{id}/overview` | KPI kartları + trend + en kritik riskler |
| `GET /datasets/{id}/periods` | Dönemsel satırlar, deltalar, boyut kırılımı |
| `GET /datasets/{id}/entities` | Kayıt bazında özet + `(kayıt, dönem)` uzun tablo |
| `GET /datasets/{id}/risks` | Risk sicili (`?severity=`, `?period=` filtreli) |
| `GET /datasets/{id}/analysis/status` | Kaç AI çağrısı gerekecek, önbellekte var mı |
| `POST /datasets/{id}/analysis` | Dönem analizleri + yönetici özeti (`?refresh=`) |
| `POST /datasets/{id}/ask` | Veri üzerinde serbest soru-cevap |
| `GET /datasets/{id}/report.pdf` | Paylaşılabilir yönetici raporu |
| `GET /packs` | Tanımlı rapor tipleri |

Tüm hatalar aynı gövdeyi döner — istemci `code` alanına göre dallanır:

```json
{ "code": "schema_mismatch",
  "message": "Zorunlu kolonlar eksik: urun_adi, kategori",
  "details": { "missing_columns": ["urun_adi", "kategori"] } }
```

---

## Mimari kararlar (ADR)

Her önemli karar için kısa bir kayıt: bağlam → seçilen → değerlendirilen
alternatifler → neden elendi → ödünler.

| | |
|---|---|
| [ADR-001](docs/decisions/ADR-001-track-secimi.md) | Track B seçimi |
| [ADR-002](docs/decisions/ADR-002-fastapi.md) | FastAPI (Litestar elendi) |
| [ADR-003](docs/decisions/ADR-003-polars.md) | Polars (pandas elendi) |
| [ADR-004](docs/decisions/ADR-004-pydantic.md) | Pydantic v2 (msgspec elendi) |
| [ADR-005](docs/decisions/ADR-005-sqlite.md) | SQLite (DuckDB/Postgres elendi) |
| [ADR-006](docs/decisions/ADR-006-model-secimi.md) | Claude Opus 5 / Sonnet 5 |
| [ADR-007](docs/decisions/ADR-007-ai-sayi-hesaplamaz.md) | **AI sayı hesaplamaz** |
| [ADR-008](docs/decisions/ADR-008-no-orchestration-framework.md) | Orkestrasyon framework'ü kullanılmadı |
| [ADR-009](docs/decisions/ADR-009-dataset-pack.md) | Dataset Pack soyutlaması |
| [ADR-010](docs/decisions/ADR-010-katman-sinirlari.md) | Katman sınırları CI ile zorlanıyor |

---

## Bilinen sınırlar

- **Dönem formatı** `YYYY-MM` varsayılıyor. Çeyreklik/haftalık raporlar için
  pack'e bir dönem ayrıştırıcı eklemek gerekir.
- **Eşikler sabit** (ölü stok > 12 ay, marj erozyonu > 5 puan). Gerçek
  kullanımda kategori bazlı ve yapılandırılabilir olmalı.
- **Analiz süresi ~100 sn** ve istek içinde çalışıyor. Production'da kuyruğa
  taşınmalı.
- **Bağlam sınırı:** entity tablosu 40 satırla sınırlı; aşılırsa risk taşıyan
  kayıtlar önceliklendiriliyor. Yüzlerce SKU'lu raporlarda özetleme katmanı
  gerekir.
- **Grounding oranı** kanıtların *varlığını* doğruluyor, yorumun *doğruluğunu*
  değil. Bir sayı doğru olabilir ama yanlış bağlamda kullanılabilir. Yaşanan
  örnek: `sifir_stok_donem = 3` değeri gerçekti ama tek bir döneme atfedilmişti
  ve düzyazıda geçtiği için grounding onu hiç görmedi. Prompt tarafında çözüldü
  (dönem anlık görüntüsü + kapsam etiketleri), ama **yapısal çözüm bu değil**:
  bir sonraki adım kapsam doğrulaması — döneme bağlı bir kanıt o dönemin
  tablosunda aranmalı, seri toplamına düşmemeli.
