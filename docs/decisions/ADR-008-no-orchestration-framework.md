# ADR-008 — Orkestrasyon framework'ü (LangGraph/LangChain) kullanılmadı

**Durum:** Kabul edildi

## Bağlam

AI akışını yönetmek için LangGraph veya LangChain kullanmak yaygın bir refleks.
Gerekçe genelde iki başlık: (a) ileride tool-calling gerekebilir, (b) orkestrasyon
framework'ü "daha güvenli".

Bizim akışın şekli:

```
N dönem analizi (paralel, bağımsız)  →  1 yönetici sentezi
```

Döngü yok, koşullu dallanma yok, insan onayı adımı yok, uzun süreli resume
ihtiyacı yok. Bu statik iki katmanlı bir DAG.

## Karar

**Framework kullanılmadı. Orkestratör yazıldı** (`app/ai/orchestrator.py`,
~180 satır).

## Gerekçe

**LangGraph'ın verdikleri bu şekle karşılık gelmiyor:** state machine,
checkpointing, conditional edge, cycle, interrupt. Karşılığı `asyncio.gather`
+ bir semafor.

**Maliyeti ise gerçek olurdu:**

1. **İki kritik özelliğimiz Anthropic'e özgü:** `messages.parse()` ile
   structured outputs ve `cache_control` ile prompt caching. Framework
   sarmalayıcıları sağlayıcıya özgü özellikleri geriden takip eder. Prompt
   caching wrapper üzerinden çalışmazsa README'nin maliyet argümanı çöker.
2. **Hata ayıklama:** bir şey bozulduğunda kendi 180 satırını değil, framework
   içini debug ederiz. (Ve gerçekten bir şey bozuldu — aşağıya bakın.)
3. **Açıklanabilirlik:** *"Neden LangGraph?"* → *"Herkes kullanıyor"* zayıf
   cevap. *"Neden kullanmadın?"* → *"Akışım statik bir DAG; döngü ve dallanma
   yok. `asyncio.gather` yetiyordu ve SDK'nın structured outputs + prompt
   caching özelliklerine doğrudan erişimimi korudum"* — yargı gösteren cevap.

**"Daha güvenli" iddiası tek tek:**

| Framework'ün vaadi | Bizde nasıl karşılandı |
|---|---|
| Retry / backoff | Anthropic SDK 429/5xx'i exponential backoff ile deniyor (`max_retries`) + tipli exception zinciri |
| Çıktı doğrulama | `messages.parse()` şemayı API katmanında zorluyor, uymazsa yeniden deniyor — framework seviyesi doğrulamadan güçlü |
| Gözlemlenebilirlik | Her çağrıda model, token, maliyet, cache hit, süre, deneme sayısı loglanıyor (`telemetry.py`, ~90 satır) |
| Hata izolasyonu | `return_exceptions=True` + başarısız dönemler yanıtta `failed_periods` olarak dönüyor; bir dönem düşse analiz yine üretiliyor |
| Checkpoint / resume | 7 çağrı, ~100 sn, üstelik sonuç SQLite'a önbelleklenmiş |

**Tool-calling endişesi:** bu ödevde gerekmiyor, hatta istemiyoruz —
soru-cevapta text-to-SQL "AI sayı hesaplamaz" kuralını
([ADR-007](ADR-007-ai-sayi-hesaplamaz.md)) ihlal ederdi. İleride gerekirse
Anthropic SDK'sının kendi tool runner'ı var ve sağlayıcı-native olduğu için
structured outputs + caching çalışmaya devam eder.

**Ve kritik nokta:** `LLMClient` bir `Protocol`. Yarın LangGraph gerekirse bu
dikişin arkasına takılır, `domain/` ve `services/` hiç değişmez. Bugün
kullanmamak yarını kapatmıyor.

## Kendi orkestratörümüzü yazmanın karşılığı: bir hatayı görebildik

İlk sürümde 7 çağrıyı `asyncio.gather` ile aynı anda salıyordum. Doğru
çalışıyordu. Ama telemetri şunu gösterdi:

```
cache_write = 90.657 token     cache_read = 0     isabetli çağrı = 0/7
```

Yedi çağrının **hepsi** önbelleği yazmış, hiçbiri okumamıştı. Bir önbellek
girdisi ancak onu yazan isteğin yanıtı akmaya başladıktan sonra okunabilir hale
geliyor; hepsini aynı anda salınca hiçbiri diğerinin yazdığını göremiyor ve
~13K token'lık bağlamın yazma ücreti (~1,25x giriş) yedi kez ödeniyor.

Çözüm: **ilk çağrıyı tek başına bekle, sonra kalanları paralel sal.**

```python
head, *rest = result.periods
first = await self._safe_period(head, ...)                    # önbelleği yazar
remaining = await asyncio.gather(*(... for period in rest))    # okur
```

| | Önce | Sonra |
|---|---|---|
| cache yazma | 90.657 | **12.951** (1 kez) |
| cache okuma | 0 | **77.706** |
| isabetli çağrı | 0/7 | **7/7** |
| maliyet | $0,398 | **~$0,22** |
| duvar saati | 93 sn | 106 sn |

Bir framework'ün arkasında bu hatayı görmek çok daha zor olurdu — token
kırılımını kendimiz logladığımız için bulundu.

## Framework'ün haklı olacağı koşul

Dogmatik değil. LangGraph şu durumlarda doğru araç: çok adımlı, dallanan,
semantik başarısızlıkta geri dönen, insan onayı içeren veya saatlerce süren
resume gerektiren akışlar. Bizimki bunların hiçbiri değil.

## Sonuçları

- Bağımlılık ağacı küçük; `langchain-core` ve provider adaptörleri yok.
- Akış dosyaya bakınca okunuyor: `gather(dönemler)` → `synthesize`.
- Ödün: bir gün gerçekten karmaşık bir agentic akış gerekirse framework'ü o
  zaman ekleyeceğiz. Protocol dikişi bunu ucuz tutuyor.
