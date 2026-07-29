# ADR-007 — AI sayı hesaplamaz; hesaplar Polars'ta, AI yorumlar

**Durum:** Kabul edildi
**Bu, projenin en önemli mimari kararı.**

## Bağlam

"AI ile veri analizi" denince en yaygın yaklaşım CSV'yi (veya bir örneklemini)
prompt'a koyup modelden analiz istemek. Bu yaklaşım çalışır gibi görünür ama iki
temel sorunu var:

1. **Model aritmetik yapar ve hata yapabilir.** "Toplam ciro 168.696 TL"
   cümlesinin doğruluğunu kimse kontrol etmiyor.
2. **Doğrulanamaz.** Çıktıda bir sayı varsa nereden geldiği belli değil;
   yanlışsa fark edilmiyor.

Puan tablosunda "AI entegrasyonunun kalitesi (prompt tasarımı, **çıktı
tutarlılığı**)" %20 ağırlıkta. Bu kalem tam olarak bu problem hakkında.

## Karar

**Modele ham CSV asla verilmiyor.** AI'ın gördüğü her sayı Polars tarafından
hesaplanmış ve `app/ai/context.py` üzerinden geçmiş durumda. Model
hesaplayamaz, çünkü hesaplayacağı ham veriye erişimi yok.

Üstüne iki katman zorlama:

### 1. Şema seviyesinde: kanıtsız aksiyon geçemez

```python
class Action(BaseModel):
    priority: Literal["kritik", "yuksek", "orta", "dusuk"]
    title: str
    rationale: str
    evidence: list[Evidence] = Field(min_length=1)   # boş liste REDDEDİLİR
    owner: str
    horizon: Literal["bu_hafta", "bu_ay", "bu_ceyrek"]
```

`Evidence` bir `(metrik, değer, birim, kayıt, dönem)` dörtlüsü. Model her
aksiyon için en az bir tane vermek zorunda.

### 2. Doğrulama seviyesinde: her kanıt gerçekten var mı?

`app/ai/validation.py` motorun ürettiği tüm sayıların aranabilir bir dizinini
(`FactIndex`) kuruyor: dönem özeti, entity özeti, boyut kırılımı, uzun seri,
KPI'lar, risk kanıtları. Sonra modelin yazdığı her kanıt bu dizinde aranıp
karşılaştırılıyor.

Sonuç bir **grounding oranı** olarak API yanıtında dönüyor:

```json
{ "total_evidence": 126, "verified_evidence": 126, "grounding_ratio": 1.0, "issues": [] }
```

Sistem promptunda da kural açıkça yazılı:

> *"Hiçbir sayıyı kendin hesaplama. Sana verilen tablolardaki değerleri olduğu
> gibi kullan. Toplama, oranlama, yüzde çıkarma yapma. Bir sayıya ihtiyacın
> varsa ve tablolarda yoksa, o iddiayı kurma."*

## Ölçülen sonuç

Örnek veride **%100 (126/126)**.

Yola çıkarken %88'de takılıydı ve incelediğimde **hatalar modelde değil, kendi
doğrulayıcımda** çıktı:

- Model *"Çantalık kategorisinin marjı %31,36"* diye doğru alıntı yapıyordu ama
  `FactIndex` boyut kırılımını hiç indekslemiyordu → portföy geneline düşüp
  "sapma" raporluyordu.
- Model bazen Türkçe karakterleri ASCII'ye düşürüyordu (`Dosemelik` /
  `Döşemelik`) → lookup başarısız oluyordu. Bu bir halüsinasyon değil, yazım
  farkı; normalize edilmesi gerekiyordu.

Ders: **doğrulama katmanı da bir yazılım ve o da hata yapar.** "AI hata yaptı"
demeden önce doğrulayıcıyı doğrulamak gerekiyor.

## Sonuçları

- Halüsinasyon iki katmanda birden engelliyor: şema kanıt zorunlu kılıyor,
  doğrulayıcı kanıtın gerçekliğini kontrol ediyor.
- **Soru-cevap bonusunda text-to-SQL yapılmadı** — model SQL yazsaydı bu kuralı
  doğrudan ihlal ederdi. Yerine hesaplanmış tablolar bağlama verilip
  yorumlatıldı.
- Grounding oranı bir **regresyon sinyali**: prompt değişikliğinden sonra oran
  düşerse bir şey bozulmuş demektir. Production'da bunun üzerine alarm kurulur.
- **Sınır:** grounding oranı kanıtların *varlığını* doğruluyor, yorumun
  *doğruluğunu* değil. Bir sayı doğru olabilir ama yanlış bağlamda
  kullanılabilir — Sonnet'in dönemsel atıf hatası
  ([ADR-006](ADR-006-model-secimi.md)) tam olarak bu türdendi ve grounding
  bunu yakalamadı. Bunu kapatmak için dönem-kapsam doğrulaması gerekir; bir
  sonraki adım.
- Ödün: modele daha az serbestlik. Tablolarda olmayan bir çıkarım yapamıyor.
  Bu projede istenen davranış tam olarak bu.
