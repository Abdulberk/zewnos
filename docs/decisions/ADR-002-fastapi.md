# ADR-002 — FastAPI (Litestar elendi)

**Durum:** Kabul edildi

## Bağlam

Backend framework'ü seçilecek. İlanda Next.js/React geçiyor, yani frontend
TypeScript olacak; backend dili serbest (ödev metni açıkça "Python/FastAPI,
Node.js vb. — serbest" diyor).

NestJS ciddi bir alternatifti: hazır DI container, module sistemi,
guard/interceptor/pipe, decorator tabanlı yapı — mimari olarak FastAPI'den daha
"kurumsal" görünüyor. Ama analitik çekirdeği TypeScript'te yazmak, on ayrı
zaman serisi hesabını elle uygulamak demekti (bkz. [ADR-003](ADR-003-polars.md)).

2026 karşılaştırmalarında FastAPI hâlâ greenfield için varsayılan tercih
konumunda: async-first, Pydantic v2 ile doğal uyum, güçlü OpenAPI desteği ve
özellikle AI/LLM backend iş yüklerine iyi oturuyor.

## Karar

**FastAPI.** Katmanlı disiplin, hazır bir framework yapısına güvenmek yerine
elle ve Pythonic biçimde kurulacak; sınırlar CI'da doğrulanacak
([ADR-010](ADR-010-katman-sinirlari.md)).

## Değerlendirilen alternatifler

| Alternatif | Güçlü yanı | Neden elendi |
|---|---|---|
| **Litestar** | msgspec tabanlı serialization (daha hızlı), daha temiz DI, güçlü tipleme. Teknik olarak en iddialı rakip | Ekosistem ve işe alım riski. "Ekibin bunu biliyor mu?" sorusuna zayıf düşer |
| **NestJS / TypeScript** | Tek dil, hazır DI/module iskeleti | Analitik çekirdeği elle yazmak ~3-4x kod ve test yükü; 48 saatte bonusları riske atar |
| **Python analiz servisi + NestJS gateway** | Her dilin gücü | 91 satırlık veride iki runtime, iki deploy, serialization sınırı. Ölçek gerekçesi yok — savunulamaz |
| **Django Ninja** | Django ekosistemi | Django'ya bağlı değiliz; ORM/admin avantajı bu projede karşılık bulmuyor |

## Sonuçları

- OpenAPI şemasından Next.js için tipli TS client üretiliyor; sınırda elle tip
  yazmak yok. Backend Python olsa da frontend tip güvenli.
- FastAPI yapı dayatmıyor — bu görünürde zayıflık, aslında fırsat: iskeleti biz
  tasarladık ve *neden öyle olduğunu* savunabiliyoruz.
- Ödün: hazır bir DI container ve module sistemi yok; `Depends` ve paket
  sınırlarıyla idare ediliyor. Bu proje ölçeğinde yeterli.
