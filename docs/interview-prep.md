# Mülakat hazırlık notları

Muhtemel sorular ve dosyaya bakmadan verilebilecek cevaplar. Her cevabın
arkasındaki kod yolu da yazılı.

---

## Track ve kapsam

**S: Neden Track B'yi seçtin?**

Ödev metninde Track B bölümünde şu cümle var: *"300+ farklı raporu 'Yönetici
dashboard'u' halinde sunabilmek nihai hedefimiz — bu ödev bunun küçük ölçekli
bir simülasyonudur."* Bu cümle Track A için yazılmamış. Yani B sizin asıl
probleminiz. Ayrıca verinin kendisi zaman serisi analizi olmadan çözülemeyecek
üç sinyal içeriyordu.

Dürüst olmak gerekirse A'nın iki avantajı vardı: video anlaşılırlığı ve
bonusların kolaylığı. Puan tablosuna göre ikisi çok yakındı. Stratejik
hizalanma belirleyici oldu.
→ `docs/decisions/ADR-001-track-secimi.md`

**S: Track A'yı da yaptığını söylüyorsun, nasıl?**

`zewnos-ads` pack'i olarak. Motor, endpoint'ler, kalite hattı ve AI katmanı
değişmedi — sadece ~330 satırlık bir yapılandırma nesnesi eklendi. Dosyayı
yüklerken pack belirtmek de zorunlu değil, başlıklardan tespit ediliyor.
Gösterebilirim: `POST /api/v1/datasets` ile reklam CSV'sini yükleyip aynı
dashboard uçlarını çağırmak yeterli.

---

## Mimari

**S: "301. rapor" gelirse ne yapman gerekir?**

Bir Python nesnesi yazmak. `DatasetPack` — kolonlar, türetilmiş metrikler,
bütünlük kuralları, imputasyon kuralları, risk kuralları, toplulaştırmalar ve
AI prompt profili. Sonra `registry.py`'ye kaydetmek. Motora, endpoint'lere, AI
katmanına dokunmuyorum.
→ `app/domain/packs/base.py`, `app/services/registry.py`

**S: Pack'i neden Protocol yapmadın?**

Çünkü pack bir davranış değil, yapılandırma. Python'da veri taşıyan bir
soyutlama için Protocol/ABC yazmak gereksiz tören — Java alışkanlığını Python'a
taşımak olur. Protocol'u gerçekten takas edilebilir davranış için sakladım:
`LLMClient`. Testlerde sahte istemci tek satırla enjekte ediliyor
(`lambda _: fake_llm`), ileride farklı bir sağlayıcı veya orkestrasyon katmanı
aynı dikişe takılır.

**S: Katmanlı mimari dedin, nasıl emin olabiliyorsun?**

Emin olmuyorum, doğruluyorum. `import-linter` sözleşmesi CI kontrolü:
`domain/` katmanı `fastapi`, `sqlalchemy` veya `anthropic` import edemiyor.
İhlal olursa build kırılıyor. `lint-imports` çalıştırıp gösterebilirim —
3 sözleşme, 76 dosya, 218 bağımlılık, hepsi KEPT.

Asıl kazanç şu: domain hiçbir framework'e bağlı olmadığı için analitik çekirdek
hiçbir altyapı ayağa kaldırmadan test edilebiliyor.
→ `.importlinter`, `docs/decisions/ADR-010-katman-sinirlari.md`

**S: NestJS gibi bir yapı kurmadın mı? DI container yok.**

Bilinçli. FastAPI'nin `Depends`'i yeterli ve daha okunabilir. Üçüncü parti
container eklemek bu ölçekte ceremony olurdu. Encapsulation'ı erişim
belirteçleri değil paket sınırları sağlıyor — ve o sınır makineyle kontrol
ediliyor, insan disiplinine bırakılmıyor.

---

## Veri kalitesi

**S: Encoding hatasını nasıl fark ettin?**

Dosyada `Marbella DÃ¶ÅŸemelik Deri` gibi değerler vardı. Bu klasik mojibake:
dosya UTF-8'ken bir yerde CP1252 gibi okunup tekrar kaydedilmiş. Logo/Netsis
export'larının en sık kusuru.

Onarım: metni CP1252 baytlarına geri çevirip UTF-8 olarak çözmek. Kritik detay
şu — bu işlem **kendiliğinden korumalı**: zaten doğru olan bir Türkçe metin
`ş` harfi CP1252'de bulunmadığı için `.encode("cp1252")` aşamasında hata verir
ve onarım denenmez. Yani sağlam veriyi yanlışlıkla bozma riski yok. Bunu bir
testle sabitledim.

Kayıplı bozulma durumunda (geri dönüşü olmayan bayt kaybı) veriye dokunmuyorum,
`ENCODING_SUSPECT` olarak raporluyorum. Veriyi bozmaktansa bilinmezliği
bildirmek doğru.
→ `app/domain/quality/encoding.py`, `tests/unit/test_encoding.py`

**S: Eksik satırı nasıl doldurdun? 5180 nereden geldi?**

U010/2026-04 satırının tüm miktarları boştu. Giriş/çıkış'ı ürünün kendi
ortancasından (700/680) doldurdum — ortalama değil ortanca, çünkü tek bir uç
değer tahmini bozmasın. Dönem sonu stoğunu ise stok mutabakatı denkleminden:
önceki dönem sonu (5160) + giriş (700) − çıkış (680) = **5180**.

Bu değer veri setinden bağımsız olarak elle doğrulanabilir, o yüzden teste
yazdım: `test_eksik_donem_sonu_stogu_mutabakattan_turetilir`.

**S: Ama bu değerin doğru olduğunu nasıl biliyorsun?**

Bilmiyorum — ve en ilginç bulgu tam burada. Aynı değeri bir de ters yönden
hesapladım: Mayıs'tan geriye doğru `5180 − 700 + 680 = 5160`. İki sonuç
uyuşmuyor.

Yani eksik satır komşu dönemlerle çelişiyor; kaynak sistemde gerçek bir
tutarsızlık var. Yaptığım: ileri yöndeki değeri kullanıp durumu
`IMPUTATION_AMBIGUOUS` olarak **açıkça raporlamak**. Sessizce birini seçip
geçmek yanlış olurdu — kullanıcı bunu bilmeli.

Bu tutarsızlığı teste de yazdım; gizlemiyorum, sabitliyorum: 75 satırın 74'ü
kuruşu kuruşuna tutuyor, tek sapma U010/2026-05'te −20.

**S: Kendi imputasyonun mutabakat alarmı üretmiyor mu?**

Üretirdi. Bu yüzden bütünlük kontrolü imputasyon yapılan satırı **ve onu izleyen
dönemi** muaf tutuyor — aksi halde kendi doldurduğumuz değer yapay bir ihlal
üretirdi. Bunu da bir testle sabitledim
(`test_imputasyon_yapay_mutabakat_ihlali_uretmez`).
→ `app/domain/quality/pipeline.py::_check_integrity`

**S: Veri sağlık puanı nasıl hesaplanıyor?**

İki boyutlu: sorunun ağırlığı ve **çözülüp çözülmediği**. Otomatik
onarılan/türetilen/temizlenen bir sorun %40 ağırlıkla düşüyor; sadece
işaretlenip bırakılan veya karantinaya alınan sorunlar tam ağırlıkla. Çünkü
"sorunu buldum ve çözdüm" ile "sorunu buldum, sende kalsın" aynı şey değil.

İlk sürümde bu ayrım yoktu ve puan 28'e düşüyordu — aynı eksik değer hem
"eksik" hem "tamamlandı" diye iki kez cezalandırılıyordu. Düzelttim.

---

## Zaman serisi

**S: Dönemsel farklılaşmayı nasıl sağladın?**

Üç katmanda:

1. **Veri:** tek dönemde görülemeyecek 10 hesap. En net örnek U005 —
   tek ay bakınca "77 sattı" der, seriye bakınca "**77 satabildi**" der: stok 5
   dönem sıfır, çıkış girişe kilitli. Bu ayrım tek dönemlik bir rapordan çıkmaz.
2. **Risk:** her riskin "ilk görülme dönemi" hesaplanıyor. Entity seviyesi
   riskler tüm seriye bakarak bulunuyor, doğal bir dönemi yok — son döneme
   yığmak yerine gerçek başlangıcı buluyorum. Sonuç: Şubat'ta stockout, Mart'ta
   maliyet şoku, Nisan'da talep patlaması. Her ayın kendi hikâyesi.
3. **AI:** `PeriodAnalysis` şemasında `delta_vs_prev` alanı zorunlu. Model her
   dönem için aynı genel metni üretemiyor, bir önceki döneme göre neyin
   değiştiğini söylemek zorunda.

**S: Trend bazlı risklerde first_seen neden None?**

`SILENT_ACCUMULATION` ve `DYING_SKU` tanım gereği tüm seriye ait — tek bir
başlangıç dönemi yok. Son dönemi uydurmak yanlış olurdu. `None` dönüyor ve
dashboard bunu "dönem atfı yok" olarak gösteriyor.

**S: `.over()` neden bu kadar önemli?**

Zaman serisi analizinin 1 numaralı hatası: `shift(1)` yaparken bir ürünün son
ayından bir sonraki ürünün ilk ayına değer taşımak. Hata **sessizdir** — sonuç
üretilir ama yanlıştır. Polars'ta grup bağlamı ifadenin içinde yazılıyor,
unutulamıyor.

Bunu bir testle sabitledim: her ürünün ilk döneminde `onceki_stok` null olmalı.
Ayrıca kasıtlı sızma kurup yakalandığını doğrulayan bir kontrol testi de var.

**S: Kapama ayını neden 3 dönemlik ortalamaya böldün?**

Tek dönemlik çıkışa bölmek gürültüye açık; mevsimsel bir düşüş yaşayan ürün
"stok 20 ay yeter" gibi görünür. 3 dönemlik hareketli ortalama dalgalanmayı
yumuşatıyor. Eşikler (kritik <1,5 ay, yavaş 6-12, ölü >12) pack'te tek yerde
sabit — gerçek kullanımda kategori bazlı ve yapılandırılabilir olmalı, bu bir
sınırlama olarak README'de yazılı.

---

## AI entegrasyonu

**S: AI'ın uydurma sayı üretmesini nasıl engelledin?**

Üç katman:

1. Modele **ham CSV asla verilmiyor**. Gördüğü her sayı Polars tarafından
   hesaplanmış. Hesaplayamaz çünkü hesaplayacağı veri elinde değil.
2. **Şema** her aksiyona en az bir kanıt zorunlu kılıyor
   (`Field(min_length=1)`). Boş kanıt listesi Pydantic doğrulamasından geçemez.
3. **Doğrulayıcı** modelin yazdığı her `(metrik, kayıt, dönem, değer)`
   dörtlüsünü hesaplanmış tablolarda arayıp karşılaştırıyor. Sonuç grounding
   oranı olarak API yanıtında dönüyor: örnek veride **%100 (126/126)**.

→ `app/ai/context.py`, `app/ai/ai_schemas.py`, `app/ai/validation.py`,
  `docs/decisions/ADR-007-ai-sayi-hesaplamaz.md`

**S: Grounding %100 — hiç hata olmadı mı?**

Oldu, ama beklediğim yerde değil. Başta %88'de takılıydı ve incelediğimde
**hataların modelde değil kendi doğrulayıcımda** olduğu ortaya çıktı:

- Model *"Çantalık kategorisinin marjı %31,36"* diye doğru alıntı yapıyordu ama
  `FactIndex` boyut kırılımını indekslemiyordu → portföy geneline düşüp "sapma"
  raporluyordu.
- Model bazen Türkçe karakterleri ASCII'ye düşürüyordu (`Dosemelik`) → lookup
  başarısız oluyordu. Bu halüsinasyon değil, yazım farkı.

İkisini düzelttikten sonra %100. Ders: doğrulama katmanı da bir yazılım ve o da
hata yapar. "AI hata yaptı" demeden önce doğrulayıcıyı doğrulamak gerekiyor.

**S: Grounding %100 ise çıktı tamamen doğru mu?**

Hayır, ve bunu README'de sınırlama olarak yazdım. Grounding kanıtların
*varlığını* doğruluyor, yorumun *doğruluğunu* değil. Bir sayı doğru olabilir
ama yanlış bağlamda kullanılabilir.

Gerçek örnek: Sonnet 5, 2026-03 analizinde U003 için "3 dönemdir stok sıfır"
dedi. `sifir_stok_donem=3` değeri **doğru** — ama tüm seriye ait, o döneme
değil. U003'ün Mart stoğu 30'du. Grounding bunu yakalamadı çünkü sayı gerçekten
var. Bunu kapatmak için dönem-kapsam doğrulaması gerekir; bir sonraki adım
olarak not ettim.

**S: Neden LangGraph/LangChain kullanmadın?**

Akışım statik iki katmanlı bir DAG: N dönem analizi paralel, sonra 1 sentez.
Döngü yok, koşullu dallanma yok, insan onayı yok, resume ihtiyacı yok.
LangGraph'ın verdikleri (state machine, checkpointing, conditional edge, cycle)
bu şekle karşılık gelmiyor. Karşılığı `asyncio.gather` + bir semafor.

Maliyeti ise gerçek olurdu: iki kritik özelliğim (structured outputs, prompt
caching) Anthropic'e özgü ve framework sarmalayıcıları sağlayıcıya özgü
özellikleri geriden takip ediyor. Caching wrapper üzerinden çalışmazsa maliyet
argümanım çöker.

Ve şunu ekleyeyim: **orkestratörü yazdım, import etmedim.** Framework'ün
değerli parçaları — akışın görünürlüğü, telemetri, yeniden deneme, hata
izolasyonu — elle ve ~180 satırda var. `LLMClient` Protocol olduğu için yarın
gerekirse arkasına takılır.

Dogmatik değilim: çok adımlı, dallanan, insan onayı içeren bir akış olsaydı
LangGraph doğru araç olurdu.

**S: Framework kullanmamak sana ne kazandırdı?**

Bir hata bulmamı sağladı. 7 çağrıyı `asyncio.gather` ile paralel salıyordum.
Doğru çalışıyordu ama telemetri şunu gösterdi: `cache_write=90.657,
cache_read=0, isabet=0/7`. Yedi çağrının hepsi önbelleği yazmış, hiçbiri
okumamıştı — çünkü bir önbellek girdisi ancak onu yazan isteğin yanıtı akmaya
başladıktan sonra okunabilir hale geliyor.

Çözüm: ilk çağrıyı tek başına bekle, sonra kalanları paralel sal. Maliyet
$0,398 → $0,22 (**%45**), karşılığında 13 saniye. Bir framework'ün arkasında bu
hatayı görmek çok daha zor olurdu.

**S: Neden Sonnet 5 ve Opus 5 ikisi de var?**

Ölçtüm. Aynı dönem, aynı bağlam, `effort=medium`, tek değişken model:
Sonnet ~3x ucuz ve 2x hızlı ($0,22 vs $0,72 tam analiz). Ama Sonnet bir dönemsel
atıf hatası yaptı, Opus yapmadı ve aksiyonlar arasında bağ kurdu.

Karar: geliştirmede Sonnet, teslim edilecek nihai analizde Opus. İkisi de
`.env`'den değişiyor ve önbellek anahtarı modeli içeriyor — Sonnet'le üretilmiş
bir analiz Opus'a geçince yanlışlıkla servis edilmiyor.

**S: Prompt tasarımında ne yaptın?**

Sistem promptu pack'ten üretiliyor: persona, değişmez kurallar, aksiyon üslubu,
departman listesi, dönem dinamikleri, metrik sözlüğü. Bağlam iki parçaya
ayrılıyor — sabit kısım (tablolar + risk sicili) önbelleklenir, değişken kısım
("şu dönemi analiz et") önbellek kırılma noktasından sonra gelir.

Bir ince detay: mover metriklerini modele **teknik adıyla** veriyorum
(`` `cikis_miktar_change` ``). Sadece etiket verirsem model kanıt yazarken adı
kendi uyduruyor ve doğrulayıcı geçerli bir kanıtı bulamıyor. Bunu ölçerek
buldum.

---

## Kod kalitesi ve testler

**S: Testlerde neye dikkat ettin?**

"Yeşil sayısı" değil, *doğru sayıyı* kontrol etmeye. Örnek:

```python
assert series_value(clean, "U010", "2026-04", "donem_sonu_stok") == 5180.0
```

Bu 5180 veri setinden bağımsız olarak elle doğrulanabilir. "Bir sayı döndü"
değil, "DOĞRU sayı döndü" test ediliyor.

Ayrıca **yanlış pozitif testleri** var: U015 istikrarlı bir ürün ve hiç risk
almaması gerekiyor. Her ürüne risk yazan bir motor işe yaramaz.

**S: AI testleri para harcıyor mu?**

Hayır. `LLMClient` bir Protocol olduğu için sahte istemci tek satırla enjekte
ediliyor. Ve sahte istemcinin kanıtları **gerçek hesaplanmış değerlerden**
alınıyor — böylece grounding doğrulayıcısının kendisi de test ediliyor, sadece
akış değil.

**S: 93 test var, kapsama oranı ne?**

Kapsama oranını hedef almadım; onun yerine risk bazlı test yazdım. Kritik
yollar: encoding onarımı, imputasyon doğruluğu, grup sınırı güvenliği, her risk
kuralı, hata sözleşmesi, önbellek davranışı, edge case'ler (boş dosya, tek
dönem, bozuk sayı, geçersiz dönem formatı).

Bilinçli olarak test etmediğim yer: PDF'in görsel çıktısı. Üretildiğini ve AI
dahil edilince büyüdüğünü kontrol ediyorum, ama piksel karşılaştırması yapmıyorum.

---

## Ölçekleme ve production

**S: 300 rapora nasıl ölçeklenir?**

Üç boyutta:

1. **Kod:** rapor başına bir pack. Motor değişmiyor.
2. **Veri:** Polars pipeline lazy'ye geçer (`scan_csv`), `collect()` streaming
   olur. Kod aynı kalır. Ad-hoc SQL gerekirse DuckDB — Polars'ı Arrow üzerinden
   zero-copy okuyor.
3. **AI:** şu an analiz istek içinde ~100 saniye. 300 rapor senaryosunda
   kuyruğa taşınmalı: Celery/RQ + Redis, upload → kuyruk → SSE/webhook
   bildirimi. Toplu analizler için Batch API (%50 indirim).

**S: 91 satırlık veride performans optimizasyonu yaptın mı?**

Kasten yapmadım — sahte olurdu ve mülakatta yakalanırdı. Yaptıklarım ucuz ve
gerçek olanlar: uçtan uca async, paralel AI çağrıları, prompt caching
(ölçülmüş), sonuç önbelleği, chunked CSV okuma, bounded concurrency, timeout +
tipli hata zinciri.

Yapmadıklarım ve nedenleri README'de tablo halinde yazılı. Olgunluk, gereksiz
mühendislik yapmamayı **bilerek** yapmaktır.

**S: Güvenlik tarafında ne var, ne eksik?**

Var: `.env` gitignore'da, `.env.example` placeholder ile, anahtar koda
gömülmüyor. Dosya boyutu sınırı. Tüm hatalar iç detay sızdırmadan dönüyor —
beklenmeyen hata 500 döner ama tam iz sadece logda. Yüklenen dosya adı
`Path().name` ile sanitize ediliyor (path traversal).

Eksik: kimlik doğrulama, yetkilendirme, rate limiting, multi-tenancy. Bunlar
production listesinde. Ayrıca CSV'nin kendisi güvenilir kabul ediliyor — formül
enjeksiyonu (Excel'e geri export edilirse) düşünülmedi.

**S: Bu projeyi bir daha yapsan neyi farklı yapardın?**

Üç şey:

1. **Telemetriyi daha erken yazardım.** Prompt caching hatasını ancak token
   kırılımını loglayınca gördüm. Önce yazsam ilk denemede doğru kurardım.
2. **Doğrulayıcıyı test verisiyle beslerdim.** Grounding %88'de takılıyken
   sorunun modelde olduğunu varsaydım; doğrulayıcının kendi testleri olsaydı
   daha hızlı bulurdum.
3. **Eşikleri baştan yapılandırılabilir yapardım.** Şu an pack'te sabit; gerçek
   kullanımda kategori bazlı olmaları gerekecek ve bu refactor edilecek.

---

## Hızlı referans — kod nerede

| Konu | Dosya |
|---|---|
| Pack sözleşmesi | `app/domain/packs/base.py` |
| ERP pack | `app/domain/packs/sonart_erp.py` |
| Reklam pack | `app/domain/packs/zewnos_ads.py` |
| Encoding onarımı | `app/domain/quality/encoding.py` |
| Kalite hattı | `app/domain/quality/pipeline.py` |
| Zaman serisi motoru | `app/domain/analytics/engine.py`, `series.py` |
| AI çıktı şeması | `app/ai/ai_schemas.py` |
| Prompt / bağlam | `app/ai/context.py` |
| Orkestratör | `app/ai/orchestrator.py` |
| Grounding doğrulaması | `app/ai/validation.py` |
| Telemetri / maliyet | `app/ai/telemetry.py` |
| Katman sözleşmesi | `.importlinter` |
