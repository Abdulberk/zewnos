"""API entegrasyon testleri.

AI cagrilari sahte bir istemciyle karsilaniyor: `LLMClient` bir Protocol
oldugu icin gercek Anthropic istemcisi yerine tek satirla takas edilebiliyor.
Boylece tum uctan uca akis parayla ve ag erisimiyle test edilmiyor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ai_schemas import (
    Action,
    Evidence,
    ExecutiveSummary,
    PeriodAnalysis,
    QAAnswer,
    RiskHighlight,
)
from app.ai.telemetry import CallStats
from app.api.deps import get_analysis_service
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services.analysis_service import AnalysisService
from app.storage.db import create_all, dispose_engine, get_session, init_engine
from app.storage.repositories import AICacheRepository

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
PREFIX = "/api/v1"


class FakeLLMClient:
    """Semaya uygun, kanitlari GERCEK hesaplanmis degerlerden alan sahte model.

    Kanitlarin gercek olmasi onemli: boylece grounding dogrulayicisinin
    calistigini da test ediyoruz, sadece akisi degil.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def structured(
        self, *, label: str, system: str, cached_context: str, question: str, schema: type
    ) -> tuple[Any, CallStats]:
        self.calls.append(label)
        stats = CallStats(
            label=label,
            model="fake-model",
            input_tokens=100,
            output_tokens=200,
            cache_read_tokens=0 if len(self.calls) == 1 else 900,
            cache_write_tokens=900 if len(self.calls) == 1 else 0,
            duration_ms=5,
        )
        evidence = [Evidence(metric="son_stok", value=4030.0, unit="adet", entity="U004")]
        action = Action(
            priority="yuksek",
            title="U004 icin yeni alimi durdurun",
            rationale="Kapama suresi 13.66 ay ve sermaye bagli.",
            evidence=evidence,
            owner="satinalma",
            horizon="bu_ay",
            expected_impact_tl=36270.0,
        )

        if schema is PeriodAnalysis:
            period = label.split(":", 1)[1]
            return (
                PeriodAnalysis(
                    period=period,
                    headline=f"{period} donemi ozeti",
                    delta_vs_prev=f"{period} doneminde stok bagli sermaye degisti ve marj baski altinda.",
                    dominant_dynamics=["stok_riski"],
                    actions=[action],
                    watch_items=["U002 sessiz birikim"],
                ),
                stats,
            )
        if schema is ExecutiveSummary:
            return (
                ExecutiveSummary(
                    headline="Stok riski ve marj baskisi one cikiyor",
                    situation="Portfoyde 18 risk tespit edildi.",
                    period_narrative="Alti donemde stok riski buyudu.",
                    top_risks=[
                        RiskHighlight(
                            entity="U004",
                            title="Olu stok",
                            why_it_matters="36.270 TL sermaye bagli",
                            evidence=evidence,
                        )
                    ],
                    opportunities=[],
                    strategic_actions=[action],
                ),
                stats,
            )
        if schema is QAAnswer:
            return (
                QAAnswer(
                    answer="Marji en hizli daralan urun U007 Cortina Cantalik Deri.",
                    evidence=evidence,
                    confidence="yuksek",
                    caveats=[],
                ),
                stats,
            )
        raise AssertionError(f"beklenmeyen sema: {schema}")


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest_asyncio.fixture
async def client(tmp_path: Path, fake_llm: FakeLLMClient) -> AsyncIterator[AsyncClient]:
    """Izole veritabani + sahte AI istemcisi ile uygulama.

    `LLMClient` bir Protocol oldugu icin AnalysisService'e sahte istemci
    enjekte etmek tek satir: `lambda _: fake_llm`. Mimarideki bu dikis
    sayesinde tum AI akisi parasiz ve agsiz test edilebiliyor.
    """
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        anthropic_api_key="sk-ant-test-key",
        ai_model="fake-model",
        app_env="test",
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    async def override_analysis_service(
        session: AsyncSession = Depends(get_session),
    ) -> AnalysisService:
        return AnalysisService(AICacheRepository(session), settings, lambda _: fake_llm)

    app.dependency_overrides[get_analysis_service] = override_analysis_service

    # ASGITransport lifespan'i calistirmaz; veritabanini elle hazirliyoruz.
    init_engine(settings.database_url)
    await create_all()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            yield http_client
    finally:
        await dispose_engine()


async def upload(client: AsyncClient, filename: str, pack: str | None = None) -> dict[str, Any]:
    path = SAMPLES / filename
    data = {"pack": pack} if pack else None
    files = {"file": (path.name, path.read_bytes(), "text/csv")}
    response = await client.post(f"{PREFIX}/datasets", files=files, data=data)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Temel akis
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_saglik_ve_packler(client: AsyncClient):
    assert (await client.get(f"{PREFIX}/health")).json() == {"status": "ok"}
    packs = (await client.get(f"{PREFIX}/packs")).json()
    assert {p["key"] for p in packs} == {"sonart-erp", "zewnos-ads"}


@pytest.mark.asyncio
async def test_yukleme_pack_tespiti_yapar(client: AsyncClient):
    payload = await upload(client, "sonart_erp_cok_donemli.csv")
    assert payload["dataset"]["pack_key"] == "sonart-erp"
    assert payload["dataset"]["raw_row_count"] == 91
    assert payload["dataset"]["clean_row_count"] == 90
    assert len(payload["periods"]) == 6


@pytest.mark.asyncio
async def test_ads_dosyasi_dogru_packe_yonlenir(client: AsyncClient):
    payload = await upload(client, "zewnos_meta_ads_cok_donemli.csv")
    assert payload["dataset"]["pack_key"] == "zewnos-ads"


@pytest.mark.asyncio
async def test_kalite_raporu_yapilan_islemi_bildirir(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    quality = (await client.get(f"{PREFIX}/datasets/{dataset_id}/quality")).json()
    codes = {i["code"] for i in quality["issues"]}
    assert "DUPLICATE_EXACT" in codes
    assert "IMPUTED_STOCK" in codes
    actions = {i["code"]: i["action"] for i in quality["issues"]}
    assert actions["DUPLICATE_EXACT"] == "silindi"
    assert actions["IMPUTED_STOCK"] == "turetildi"


@pytest.mark.asyncio
async def test_dashboard_uclari_veri_dondurur(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]

    overview = (await client.get(f"{PREFIX}/datasets/{dataset_id}/overview")).json()
    assert overview["headline_metrics"]
    assert overview["risk_counts_by_severity"]["kritik"] >= 1

    periods = (await client.get(f"{PREFIX}/datasets/{dataset_id}/periods")).json()
    assert len(periods["rows"]) == 6
    assert any(d["new_risks"] for d in periods["deltas"])

    entities = (await client.get(f"{PREFIX}/datasets/{dataset_id}/entities")).json()
    assert len(entities["rows"]) == 15
    assert len(entities["series_rows"]) == 90


@pytest.mark.asyncio
async def test_risk_filtreleri_calisir(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    kritik = (
        await client.get(f"{PREFIX}/datasets/{dataset_id}/risks", params={"severity": "kritik"})
    ).json()
    assert kritik["total"] >= 1
    assert all(r["severity"] == "kritik" for r in kritik["risks"])

    mart = (
        await client.get(f"{PREFIX}/datasets/{dataset_id}/risks", params={"period": "2026-03"})
    ).json()
    assert all(r["first_seen_period"] == "2026-03" for r in mart["risks"])


@pytest.mark.asyncio
async def test_risk_filtresinde_dagilim_da_filtrelenir(client: AsyncClient):
    """Filtrelenmis yanitta total ile dagilim ayni kumeyi anlatmali.

    Aksi halde ekranda "3 kritik risk" basligi altinda 18'lik bir dagilim
    grafigi cikar; kullanici hangisine inanacagini bilemez.
    """
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    tumu = (await client.get(f"{PREFIX}/datasets/{dataset_id}/risks")).json()
    kritik = (
        await client.get(f"{PREFIX}/datasets/{dataset_id}/risks", params={"severity": "kritik"})
    ).json()

    assert kritik["total"] < tumu["total"], "filtre gercekten daraltmali"
    assert sum(kritik["by_severity"].values()) == kritik["total"]
    assert sum(kritik["by_code"].values()) == kritik["total"]
    assert set(kritik["by_severity"]) == {"kritik"}


# ---------------------------------------------------------------------------
# AI akisi (sahte istemci)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_analiz_her_donem_icin_cagri_yapar(client: AsyncClient, fake_llm: FakeLLMClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    payload = (await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis")).json()

    assert len(payload["periods"]) == 6
    assert payload["summary"] is not None
    assert payload["cached"] is False
    # 6 donem + 1 sentez
    assert len(fake_llm.calls) == 7
    assert "executive_summary" in fake_llm.calls
    # sahte istemcinin kanitlari gercek degerlerden alindigi icin %100 dogrulanmali
    assert payload["grounding"]["grounding_ratio"] == 1.0


@pytest.mark.asyncio
async def test_ikinci_analiz_onbellekten_gelir(client: AsyncClient, fake_llm: FakeLLMClient):
    """Onbellek olmadan her dashboard yenilemesi 7 AI cagrisi demek olurdu."""
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis")
    first_count = len(fake_llm.calls)

    second = (await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis")).json()
    assert second["cached"] is True
    assert len(fake_llm.calls) == first_count  # yeni cagri YAPILMADI


@pytest.mark.asyncio
async def test_refresh_onbellegi_atlar(client: AsyncClient, fake_llm: FakeLLMClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis")
    before = len(fake_llm.calls)
    payload = (
        await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis", params={"refresh": "true"})
    ).json()
    assert payload["cached"] is False
    assert len(fake_llm.calls) == before + 7


@pytest.mark.asyncio
async def test_analiz_durumu_onbellegi_bildirir(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    before = (await client.get(f"{PREFIX}/datasets/{dataset_id}/analysis/status")).json()
    assert before["cached"] is False
    assert before["estimated_calls"] == 7

    await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis")
    after = (await client.get(f"{PREFIX}/datasets/{dataset_id}/analysis/status")).json()
    assert after["cached"] is True
    assert after["estimated_calls"] == 0


@pytest.mark.asyncio
async def test_soru_cevap_kanit_dondurur(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    response = await client.post(
        f"{PREFIX}/datasets/{dataset_id}/ask",
        json={"question": "Marji en hizli daralan urun hangisi?"},
    )
    payload = response.json()
    assert payload["answer"]["evidence"]
    assert payload["grounding"]["grounding_ratio"] == 1.0


# ---------------------------------------------------------------------------
# Hata sozlesmesi
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bos_dosya_422_ve_kod_dondurur(client: AsyncClient):
    response = await client.post(f"{PREFIX}/datasets", files={"file": ("bos.csv", b"", "text/csv")})
    assert response.status_code == 422
    assert response.json()["code"] == "empty_dataset"


@pytest.mark.asyncio
async def test_eksik_kolon_hangi_kolonlarin_eksik_oldugunu_soyler(client: AsyncClient):
    response = await client.post(
        f"{PREFIX}/datasets",
        files={"file": ("x.csv", b"stok_kodu,donem\nU1,2026-01\n", "text/csv")},
        data={"pack": "sonart-erp"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "schema_mismatch"
    assert "birim_maliyet_tl" in body["details"]["missing_columns"]


@pytest.mark.asyncio
async def test_bilinmeyen_pack_400_dondurur(client: AsyncClient):
    response = await client.post(
        f"{PREFIX}/datasets",
        files={"file": ("x.csv", b"a\n1\n", "text/csv")},
        data={"pack": "olmayan-pack"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "unknown_pack"


@pytest.mark.asyncio
async def test_olmayan_dataset_404_dondurur(client: AsyncClient):
    response = await client.get(f"{PREFIX}/datasets/yokboyle/overview")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_cok_kisa_soru_reddedilir(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    response = await client.post(f"{PREFIX}/datasets/{dataset_id}/ask", json={"question": "a"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.asyncio
async def test_her_yanit_korelasyon_kimligi_tasir(client: AsyncClient):
    response = await client.get(f"{PREFIX}/health")
    assert response.headers["x-request-id"]
    assert response.headers["x-response-time-ms"]


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pdf_ai_olmadan_uretilir(client: AsyncClient, fake_llm: FakeLLMClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    response = await client.get(f"{PREFIX}/datasets/{dataset_id}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert fake_llm.calls == []  # rapor icin AI cagrisi yapilmadi


@pytest.mark.asyncio
async def test_pdf_onbellekteki_analizi_dahil_eder(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis")
    with_ai = await client.get(f"{PREFIX}/datasets/{dataset_id}/report.pdf")
    without_ai = await client.get(
        f"{PREFIX}/datasets/{dataset_id}/report.pdf", params={"include_ai": "false"}
    )
    assert len(with_ai.content) > len(without_ai.content)


# ---------------------------------------------------------------------------
# Yasam dongusu
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_silme_veri_setini_ve_onbellegi_kaldirir(client: AsyncClient):
    dataset_id = (await upload(client, "sonart_erp_cok_donemli.csv"))["dataset"]["id"]
    await client.post(f"{PREFIX}/datasets/{dataset_id}/analysis")
    assert (await client.delete(f"{PREFIX}/datasets/{dataset_id}")).status_code == 204
    assert (await client.get(f"{PREFIX}/datasets/{dataset_id}/overview")).status_code == 404


@pytest.mark.asyncio
async def test_openapi_semasi_uretilir(client: AsyncClient):
    """Next.js istemcisi bu semadan uretilecek; kirilirsa frontend tipleri kirilir."""
    schema = (await client.get(f"{PREFIX}/openapi.json")).json()
    assert schema["info"]["title"] == "Sonart Insight API"
    assert f"{PREFIX}/datasets" in schema["paths"]
    assert "UploadResponse" in schema["components"]["schemas"]
