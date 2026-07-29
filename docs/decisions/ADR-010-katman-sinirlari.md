# ADR-010 — Katman sınırları CI'da zorlanıyor

**Durum:** Kabul edildi

## Bağlam

"Katmanlı mimari kurdum" ve "temiz mimari uyguladım" cümleleri kolay söylenir,
zor doğrulanır. Bir hafta sonra bir router doğrudan SQLAlchemy sorgusu yazarsa
kimse fark etmez ve iddia sessizce yanlış hale gelir.

FastAPI, NestJS gibi bir yapı dayatmıyor. Bu görünürde bir zayıflık ama aslında
fırsat: yapıyı biz tasarlıyoruz — ve tasarladığımızı **doğrulayabiliriz**.

## Karar

Katman sınırları `import-linter` sözleşmesiyle tanımlandı ve CI kontrolü haline
getirildi. `.importlinter` içinde üç sözleşme var:

```ini
[importlinter:contract:layers]
type = layers
layers =
    app.api
    app.services
    app.domain

[importlinter:contract:domain-purity]
type = forbidden
source_modules = app.domain
forbidden_modules =
    fastapi
    sqlalchemy
    anthropic
    app.api
    app.services
    app.storage
    app.ai

[importlinter:contract:ai-isolation]
type = forbidden
source_modules = app.ai
forbidden_modules =
    app.storage
    app.api
```

Çıktı:

```
$ lint-imports
Analyzed 76 files, 218 dependencies.

Katmanlı mimari (api -> services -> domain)   KEPT
Domain katmanı çerçeveden bağımsız            KEPT
AI katmanı storage'a doğrudan erişemez        KEPT

Contracts: 3 kept, 0 broken.
```

İhlal edilirse komut sıfırdan farklı kod döndürür ve build kırılır.

## Neden bu üç sözleşme

1. **Katman sırası** — üst katman altı çağırabilir, tersi olamaz. Router'ın iş
   mantığı yazmasını, servisin HTTP bilmesini engelliyor.
2. **Domain saflığı** — asıl kazanç bu. `domain/` hiçbir framework'e bağımlı
   olmadığı için analitik çekirdek hiçbir altyapı ayağa kaldırmadan doğrudan
   unit test edilebiliyor. 93 testin çoğu ne veritabanı ne HTTP istemcisi
   gerektiriyor.
   - Not: `polars` yasaklı listede **değil** — Polars bir framework değil,
     domain'in hesaplama dili. Analitik mantığın kendisi.
3. **AI izolasyonu** — AI katmanı önbelleğe doğrudan dokunmuyor; önbellek
   servis katmanından geçiyor. Böylece orkestratör saf kalıyor ve test edilirken
   veritabanı gerektirmiyor.

## Pythonic tutmak için yapılmayanlar

Sınırları korumak için ceremony eklemedik:

| Yapılmadı | Yerine |
|---|---|
| Üçüncü parti DI container (`dependency-injector`, `punq`) | FastAPI'nin `Depends`'i; bağlama açık fonksiyonlarla |
| ABC mirası ve `IService` isimlendirmesi | `typing.Protocol` (yapısal tipleme) — yalnızca gerçekten takas edilen iki yerde |
| Her servis için sınıf | Fonksiyon modülleri; sınıf ancak durum tutuyorsa (repository bir session tutar) |
| Getter/setter, private konvansiyonları | `frozen dataclass` değer nesneleri |
| Global kayıt yapan decorator, metaclass | Açık kompozisyon |

Encapsulation'ı erişim belirteçleri değil **paket sınırları** sağlıyor — ve bu
sınır makine tarafından kontrol ediliyor, insan disiplinine bırakılmıyor.

## Değerlendirilen alternatifler

| Alternatif | Neden elendi |
|---|---|
| Sınırı sadece dokümantasyonda anlatmak | Doğrulanamaz; zamanla yanlış hale gelir |
| Kod inceleme disiplinine bırakmak | Tek kişilik projede inceleyen yok |
| `pytest-archon` / özel AST kontrolü | `import-linter` bu işi zaten yapıyor, tekerlek icadı olurdu |
| Sınırı hiç koymamak (tek katman) | Domain testleri altyapı gerektirirdi; analitik çekirdek doğrudan test edilemezdi |

## Sonuçları

- Mimari iddiası mülakatta gösterilebilir: `.importlinter` dosyası açılıp
  komut çalıştırılır.
- Yeni bir geliştirici yanlışlıkla katman ihlali yaparsa build kırılır ve
  nedenini söyler.
- Ödün: `include_external_packages = True` gerektiği için analiz tüm bağımlılık
  ağacını tarıyor; 76 dosyada birkaç saniye sürüyor. Büyük projelerde CI'da
  ayrı bir adım olur.
