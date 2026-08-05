"""Uygulama ayarlari.

Tek kaynak: ortam degiskenleri (.env). Pydantic Settings ile tiplenir ve
uygulama acilisinda bir kez dogrulanir -- yanlis yapilandirma calisma
zamaninda degil, baslangicta patlar.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- uygulama ---
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_prefix: str = "/api/v1"

    # Tarayicidan cagiran arayuzlerin kokenleri, virgulle ayrilmis. Varsayilan
    # yalnizca yerel Next.js gelistirme sunucusu; dagitilmis bir arayuz
    # eklenecekse ortam degiskeniyle verilir. Kodda sabit tutmak, arayuzun her
    # yeni adresinde backend'i yeniden dagitmayi gerektirirdi.
    #
    # Tip neden list[str] degil: pydantic-settings karmasik alanlari ortamdan
    # yalnizca JSON olarak cozer ve bunu alan dogrulayicisindan ONCE yapar --
    # dagitim paneline JSON yazmak hataya acik. Duz metin alip `allowed_origins`
    # ile listeye ceviriyoruz.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- depolama ---
    database_url: str = "sqlite+aiosqlite:///./sonart.db"
    upload_dir: Path = Path("./storage/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB

    # --- AI ---
    # Anahtar opsiyonel: yoksa uygulama acilir ve AI disi tum endpoint'ler
    # calisir; sadece analiz uclari 503 ile "yapilandirilmamis" der.
    anthropic_api_key: str | None = None
    # Varsayilan: Sonnet 5 + medium. Olculen karsilastirmada (bkz. README
    # "Model secimi") Sonnet 5 tam analizi ~3x ucuza ve ~2x hizli uretiyor;
    # Opus 5 ise donemsel atif dogrulugunda ve aksiyon derinliginde belirgin
    # sekilde daha iyi. Ikisi de ortam degiskeniyle degisebilir: gelistirme
    # sirasinda Sonnet, teslim edilecek nihai analizde Opus.
    ai_model: str = "claude-sonnet-5"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_max_tokens: int = 12_000
    ai_max_concurrency: int = 6
    ai_timeout_seconds: float = 180.0
    ai_max_retries: int = 3
    ai_cache_enabled: bool = True

    # Prompt surumu: onbellek anahtarinin parcasi. Degistiginde eski analizler
    # otomatik gecersizlesir -- yeni prompt ile uretilmemis bir cikti sessizce
    # servis edilmez.
    #   v1 -> v2: donem sorusuna o doneme ait "anlik goruntu" tablosu eklendi ve
    #             iki tablo da kapsamiyla etiketlendi (seri toplami / tek donem).
    #             Sebep: model seri toplamini tek bir doneme atfediyordu.
    #   v2 -> v3: Evidence.entity alani boyut kirilimlerini de kapsayacak sekilde
    #             tarif edildi. Sebep: model kategori seviyesi bir degeri dogru
    #             alintiliyor ama kapsamini bos birakiyordu; dogrulayici da onu
    #             portfoy geneliyle karsilastirip yanlis alarm veriyordu.
    #   v3 -> v4: kullaniciya gorunen tum etiketler ve risk anlatilari duzgun
    #             Turkce'ye cevrildi ("Brut Kar" -> "Brüt Kâr"). Bu etiketler
    #             modele giden tablolarin basliklarinda yer aldigi icin prompt
    #             icerigi degisti; eski onbellek girdileri gecersiz.
    #   v4 -> v5: cikti dili kurali netlestirildi ("prompt ASCII yazilmistir,
    #             onu taklit etme"). Sebep: prompt ASCII oldugu icin model bazi
    #             alanlarda uslubu aynalayip "kapama suresi 8.16 ay" gibi ASCII
    #             Turkce uretiyordu; ozellikle ilk donem ve soru-cevap ucunda.
    #   v5 -> v6: donem sorusuna BIR ONCEKI donemin anlik goruntusu eklendi ve
    #             `ilk_*`/`son_*` kolonlarinin seri uclarini gosterdigi acikca
    #             yazildi. Sebep: `delta_vs_prev` bir karsilastirma istiyordu
    #             ama tabani verilmiyordu; model kayit bazinda tek bulabildigi
    #             sayiya, seri ozetine uzaniyordu. Olculen: Mart analizinde
    #             U007 icin "marj %30.5'ten %21.0'e dustu" -- %30.5 Haziran
    #             degeri, Subat gercegi %41.9. Sayi tablolarda var oldugu icin
    #             grounding %100 kaliyor; dogrulayici degil prompt eksikti.
    prompt_version: str = "v6"

    @field_validator("upload_dir")
    @classmethod
    def _ensure_upload_dir(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @property
    def allowed_origins(self) -> list[str]:
        """CORS icin izinli kokenler."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ai_configured(self) -> bool:
        """AI cagrilari yapilabilir mi?"""
        return bool(self.anthropic_api_key and self.anthropic_api_key.startswith("sk-ant-"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Surec basina tek Settings ornegi (FastAPI Depends ile enjekte edilir)."""
    return Settings()
