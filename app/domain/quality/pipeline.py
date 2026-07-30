"""Ingestion + veri kalitesi hatti.

Ham CSV baytlarindan analize hazir, temiz bir Polars tablosuna giden yol.
Her adim ne buldugunu ve *ne yaptigini* raporlar -- kullaniciya "sorun var"
demek yetmez, "sorunu nasil ele aldim" da soylenmeli.

Akis:
    bayt -> kodlama coz/onar -> CSV ayristir -> basliklari eslestir
         -> tip donusumu -> birebir kopya temizle -> anahtar kopya tespit
         -> eksik deger tamamla -> butunluk kontrolu -> donem bosluklari
         -> karantina -> (temiz tablo, kalite raporu)
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

import polars as pl

from app.core.errors import EmptyDatasetError, IngestionError, SchemaMismatchError
from app.domain.analytics.series import build_series
from app.domain.models import (
    ColumnType,
    IssueAction,
    QualityIssue,
    QualityReport,
    Severity,
)
from app.domain.packs.base import DatasetPack
from app.domain.quality.encoding import decode_bytes

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
_IMPUTED_SUFFIX = "__imputed"
_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """Hattin ciktisi: temiz veri + karantina + tam kalite raporu."""

    clean: pl.DataFrame
    quarantined: pl.DataFrame
    report: QualityReport
    imputed_columns: tuple[str, ...]


def ingest(raw: bytes, pack: DatasetPack) -> IngestOutcome:
    """Ham CSV baytlarini pack semasina gore isler."""
    issues: list[QualityIssue] = []
    ctx = pack.context

    # -- 1. kodlama --------------------------------------------------------
    decoded = decode_bytes(raw)
    if not decoded.text.strip():
        raise EmptyDatasetError("Dosya boş.")

    if decoded.repaired:
        issues.append(
            QualityIssue(
                code="ENCODING_REPAIRED",
                title="Karakter kodlaması bozukluğu onarıldı",
                severity=Severity.ORTA,
                action=IssueAction.ONARILDI,
                affected_rows=len(decoded.repaired_samples),
                detail=(
                    "Dosya UTF-8 iken CP1252 olarak okunup tekrar kaydedilmiş "
                    "(mojibake). Türkçe karakterler geri kazanıldı."
                ),
                samples=decoded.repaired_samples,
            )
        )
    elif decoded.suspect_unrepaired:
        issues.append(
            QualityIssue(
                code="ENCODING_SUSPECT",
                title="Karakter kodlaması şüpheli, güvenli onarım yapılamadı",
                severity=Severity.YUKSEK,
                action=IssueAction.ISARETLENDI,
                affected_rows=0,
                detail=(
                    "Metinde mojibake izi var ancak geri dönüşü kayıpsız değil. "
                    "Veriyi bozmamak için dokunulmadı; kaynak export'un kodlaması "
                    "kontrol edilmeli."
                ),
            )
        )

    # -- 2. CSV ayristirma -------------------------------------------------
    frame = _parse_csv(decoded.text)
    raw_row_count = frame.height
    if raw_row_count == 0:
        raise EmptyDatasetError("Dosyada başlık dışında satır yok.")

    # -- 3. baslik eslestirme ---------------------------------------------
    frame, issues_headers = _map_headers(frame, pack)
    issues.extend(issues_headers)

    # -- 4. tip donusumu ---------------------------------------------------
    frame, issues_cast = _coerce_types(frame, pack)
    issues.extend(issues_cast)

    # -- 5. birebir kopya --------------------------------------------------
    frame, issue_exact = _drop_exact_duplicates(frame)
    if issue_exact:
        issues.append(issue_exact)

    # -- 6. anahtar kopya (ayni entity+donem, farkli degerler) -------------
    frame, issue_key = _resolve_key_duplicates(frame, pack)
    if issue_key:
        issues.append(issue_key)

    # sirali olmak zorunlu: tum pencere hesaplari buna dayanir
    frame = frame.sort([ctx.entity_key, ctx.period_key])

    # -- 7. eksik deger tamamlama -----------------------------------------
    frame, issues_imputed, imputed_cols = _impute(frame, pack)
    issues.extend(issues_imputed)

    # -- 8. donem bosluklari ----------------------------------------------
    gap_issue = _detect_period_gaps(frame, pack)
    if gap_issue:
        issues.append(gap_issue)

    # -- 9. karantina ------------------------------------------------------
    clean, quarantined, issue_quarantine = _quarantine_incomplete(frame, pack)
    if issue_quarantine:
        issues.append(issue_quarantine)

    if clean.height == 0:
        raise EmptyDatasetError(
            "Tüm satırlar zorunlu alan eksikliği nedeniyle karantinaya alındı; "
            "analiz edilebilecek veri kalmadı."
        )

    # -- 10. butunluk kurallari (temiz veri uzerinde) ----------------------
    issues.extend(_check_integrity(clean, pack))

    report = QualityReport(
        raw_row_count=raw_row_count,
        clean_row_count=clean.height,
        quarantined_row_count=quarantined.height,
        encoding_detected=decoded.encoding,
        encoding_repaired=decoded.repaired,
        issues=tuple(sorted(issues, key=lambda i: i.severity.rank)),
    )
    return IngestOutcome(clean, quarantined, report, imputed_cols)


# ---------------------------------------------------------------------------
# adim implementasyonlari
# ---------------------------------------------------------------------------
def _parse_csv(text: str) -> pl.DataFrame:
    """Her kolonu once metin olarak okur.

    Tip cikarimini Polars'a birakmiyoruz: bozuk bir hucre yuzunden tum
    kolonun sessizce metne dusmesini degil, hangi hucrenin cevrilemedigini
    gormek istiyoruz.
    """
    buffer = io.BytesIO(text.encode("utf-8"))
    try:
        frame = pl.read_csv(
            buffer,
            infer_schema_length=0,  # hepsi String
            try_parse_dates=False,
            ignore_errors=False,
            truncate_ragged_lines=True,
        )
    except Exception as exc:
        raise IngestionError(f"CSV ayrıştırılamadı: {exc}") from exc

    # tamamen bos satirlari at
    if frame.height:
        non_null = pl.sum_horizontal(
            [pl.col(c).is_not_null() & (pl.col(c).str.strip_chars() != "") for c in frame.columns]
        )
        frame = frame.filter(non_null > 0)
    return frame


def _map_headers(frame: pl.DataFrame, pack: DatasetPack) -> tuple[pl.DataFrame, list[QualityIssue]]:
    mapping, missing = pack.resolve_headers(frame.columns)
    if missing:
        raise SchemaMismatchError(
            f"Zorunlu kolonlar eksik: {', '.join(missing)}",
            details={
                "missing_columns": missing,
                "found_columns": frame.columns,
                "expected_pack": pack.key,
            },
        )

    issues: list[QualityIssue] = []
    unknown = [c for c in frame.columns if c not in mapping]
    if unknown:
        issues.append(
            QualityIssue(
                code="UNKNOWN_COLUMNS",
                title="Şemada tanımlı olmayan kolonlar yok sayıldı",
                severity=Severity.BILGI,
                action=IssueAction.ISARETLENDI,
                affected_rows=0,
                detail="Bu kolonlar analize dahil edilmedi.",
                samples=tuple(unknown[:8]),
            )
        )

    return frame.rename(mapping).select(list(mapping.values())), issues


# Sayi yazim bicimleri. ERP export'lari ayni dosyada bile karisik gelebiliyor;
# bicimi tahmin etmek yerine kaliba bakip karar veriyoruz.
_TR_TAM = r"^-?\d{1,3}(\.\d{3})+$"  # 12.500        -> 12500
_TR_ONDALIK = r"^-?\d+,\d+$"  # 12,5          -> 12.5
_TR_KARISIK = r"^-?\d{1,3}(\.\d{3})+,\d+$"  # 1.234,56      -> 1234.56
_EN_TAM = r"^-?\d{1,3}(,\d{3})+$"  # 12,500        -> 12500
_EN_KARISIK = r"^-?\d{1,3}(,\d{3})+\.\d+$"  # 1,234.56      -> 1234.56
_SADE = r"^-?\d+(\.\d+)?$"  # 12500 / 12.5  -> oldugu gibi


def _normalize_number(text: pl.Expr) -> pl.Expr:
    """Sayi metnini Polars'in okuyabilecegi tek bicime indirger.

    Neden kalip esleme: "12.500" tek basina belirsizdir -- Turkce yazimda
    on iki bin bes yuz, Ingilizce yazimda on iki nokta bes. Nokta/virgul
    kor bir sekilde silinirse ("replace_all") ikisinden biri sessizce 1000
    kat yanlis okunur. Kalip eslesmezse deger null olur ve kalite raporunda
    "cevrilemeyen deger" olarak GORUNUR -- sessiz yanlis yerine gurultulu
    eksik tercih edilir.

    Belirsizlik cozumu: bir ayracin ardindan TAM UC hane geliyorsa o ayrac
    binliktir. "12.500" -> 12500 ve "12,500" -> 12500; ondalik istegi
    "12,5" ya da "12.5" diye yazilir. Kural iki ayrac icin de ayni.

    Sira ONEMLI: kaliplar ozgulden genele denenir. "12.500" hem _TR_TAM'e
    hem _SADE'ye uyar; _SADE once denenirse deger 1000 kat yanlis okunur.
    """
    compact = text.str.replace_all(r"[\s ]", "")
    dotless = compact.str.replace_all(r"\.", "")
    commaless = compact.str.replace_all(",", "")
    return (
        pl.when(compact.str.contains(_TR_KARISIK))
        .then(dotless.str.replace(",", "."))
        .when(compact.str.contains(_EN_KARISIK))
        .then(commaless)
        .when(compact.str.contains(_TR_TAM))
        .then(dotless)
        .when(compact.str.contains(_EN_TAM))
        .then(commaless)
        .when(compact.str.contains(_TR_ONDALIK))
        .then(compact.str.replace(",", "."))
        .when(compact.str.contains(_SADE))
        .then(compact)
        .otherwise(None)
    )


def _coerce_types(
    frame: pl.DataFrame, pack: DatasetPack
) -> tuple[pl.DataFrame, list[QualityIssue]]:
    """Metin kolonlari hedef tiplere cevirir, cevrilemeyeni null yapar."""
    issues: list[QualityIssue] = []
    exprs: list[pl.Expr] = []

    for column in pack.columns:
        name = column.canonical
        if name not in frame.columns:
            continue
        cleaned = pl.col(name).cast(pl.String).str.strip_chars()
        # bos string'i null'a cevir -- "eksik" ile "bos metin" ayni sey degil
        cleaned = pl.when(cleaned == "").then(None).otherwise(cleaned)

        match column.dtype:
            case ColumnType.TAMSAYI:
                expr = (
                    _normalize_number(cleaned)
                    .cast(pl.Float64, strict=False)
                    .cast(pl.Int64, strict=False)
                )
            case ColumnType.ONDALIK:
                expr = _normalize_number(cleaned).cast(pl.Float64, strict=False)
            case ColumnType.DONEM | ColumnType.METIN:
                expr = cleaned
            case _:
                expr = cleaned
        exprs.append(expr.alias(name))

    frame = frame.with_columns(exprs)

    # cevrilemeyen sayisal hucreleri raporla
    for column in pack.columns:
        name = column.canonical
        if name not in frame.columns or column.dtype not in (
            ColumnType.TAMSAYI,
            ColumnType.ONDALIK,
        ):
            continue
        null_count = int(frame.select(pl.col(name).is_null().sum()).item())
        if null_count:
            # Bilinerek BILGI seviyesi: bu sadece tespit. Asil hukum bir sonraki
            # adimlarda veriliyor -- deger tamamlanabildiyse TURETILDI, yoksa
            # KARANTINA olarak raporlanacak. Ikisini de saymak ayni sorunu iki
            # kez cezalandirmak olurdu.
            issues.append(
                QualityIssue(
                    code="MISSING_DETECTED",
                    title=f"'{column.label or name}' alanında eksik/okunamayan değer",
                    severity=Severity.BILGI,
                    action=IssueAction.ISARETLENDI,
                    affected_rows=null_count,
                    detail=(
                        f"{null_count} satırda değer boş ya da sayıya çevrilemedi. "
                        "Tamamlama kuralları bir sonraki adımda denenecek."
                    ),
                )
            )

    # donem formatini dogrula
    period_key = pack.period_key
    if period_key in frame.columns:
        bad = frame.filter(
            pl.col(period_key).is_not_null() & ~pl.col(period_key).str.contains(_PERIOD_RE.pattern)
        )
        if bad.height:
            issues.append(
                QualityIssue(
                    code="INVALID_PERIOD_FORMAT",
                    title="Dönem formatı beklenen YYYY-AA kalıbına uymuyor",
                    severity=Severity.YUKSEK,
                    action=IssueAction.KARANTINA,
                    affected_rows=bad.height,
                    detail="Bu satırlar zaman serisine dahil edilemez.",
                    samples=tuple(
                        str(v) for v in bad.get_column(period_key).unique().to_list()[:5]
                    ),
                )
            )
            frame = frame.filter(
                pl.col(period_key).is_not_null()
                & pl.col(period_key).str.contains(_PERIOD_RE.pattern)
            )

    return frame, issues


def _drop_exact_duplicates(frame: pl.DataFrame) -> tuple[pl.DataFrame, QualityIssue | None]:
    before = frame.height
    deduped = frame.unique(keep="first", maintain_order=True)
    removed = before - deduped.height
    if removed == 0:
        return frame, None
    return deduped, QualityIssue(
        code="DUPLICATE_EXACT",
        title="Birebir aynı satırlar kaldırıldı",
        severity=Severity.ORTA,
        action=IssueAction.SILINDI,
        affected_rows=removed,
        detail=(
            f"{removed} satır tüm kolonlarıyla birebir tekrar ediyordu. "
            "ERP export'larında sayfalama/birleştirme hatasının tipik izi. "
            "Toplamları şişmemesi için tekil hale getirildi."
        ),
    )


def _resolve_key_duplicates(
    frame: pl.DataFrame, pack: DatasetPack
) -> tuple[pl.DataFrame, QualityIssue | None]:
    """Ayni (entity, donem) icin birden fazla *farkli* kayit varsa son kayit alinir."""
    keys = [pack.entity_key, pack.period_key]
    if not all(k in frame.columns for k in keys):
        return frame, None

    counts = frame.group_by(keys).len().filter(pl.col("len") > 1)
    if counts.height == 0:
        return frame, None

    samples = tuple(f"{row[0]} / {row[1]} ({row[2]} kayıt)" for row in counts.head(5).iter_rows())
    deduped = frame.unique(subset=keys, keep="last", maintain_order=True)
    removed = frame.height - deduped.height
    return deduped, QualityIssue(
        code="DUPLICATE_KEY",
        title="Aynı dönem için çelişen kayıtlar",
        severity=Severity.YUKSEK,
        action=IssueAction.SILINDI,
        affected_rows=removed,
        detail=(
            "Aynı ürün-dönem çifti için birden fazla ve birbirinden farklı kayıt "
            "bulundu. En son kayıt doğru kabul edildi (ERP'de düzeltme kaydı "
            "genellikle sonradan yazılır)."
        ),
        samples=samples,
    )


def _impute(
    frame: pl.DataFrame, pack: DatasetPack
) -> tuple[pl.DataFrame, list[QualityIssue], tuple[str, ...]]:
    """Pack'in tanimladigi tamamlama kurallarini sirayla uygular."""
    issues: list[QualityIssue] = []
    imputed_columns: list[str] = []
    ctx = pack.context

    for rule in pack.imputation_rules:
        target = rule.target_column
        if target not in frame.columns:
            continue

        missing_mask = pl.col(target).is_null()
        missing_count = int(frame.select(missing_mask.sum()).item())
        if missing_count == 0:
            continue

        forward = rule.forward(ctx)
        frame = frame.with_columns(forward.alias("__fwd"))

        ambiguous_detail = ""
        if rule.backward is not None:
            frame = frame.with_columns(rule.backward(ctx).alias("__bwd"))
            conflict = frame.filter(
                pl.col(target).is_null()
                & pl.col("__fwd").is_not_null()
                & pl.col("__bwd").is_not_null()
                & ((pl.col("__fwd") - pl.col("__bwd")).abs() > rule.tolerance)
            )
            if conflict.height:
                rows = conflict.select([ctx.entity_key, ctx.period_key, "__fwd", "__bwd"]).head(5)
                samples = tuple(
                    f"{r[0]} / {r[1]}: ileri={r[2]:.0f} geri={r[3]:.0f}" for r in rows.iter_rows()
                )
                ambiguous_detail = (
                    " İleri ve geri yönde hesaplanan değerler uyuşmuyor -- veri "
                    "setinde bu kayıt için gerçek bir tutarsızlık var. İleri yöndeki "
                    "değer kullanıldı ve durum raporlandı."
                )
                issues.append(
                    QualityIssue(
                        code="IMPUTATION_AMBIGUOUS",
                        title="Eksik değer iki yönden farklı hesaplanıyor",
                        severity=Severity.YUKSEK,
                        action=IssueAction.ISARETLENDI,
                        affected_rows=conflict.height,
                        detail=(
                            "Eksik satır, önceki dönemden ileri doğru ve sonraki "
                            "dönemden geri doğru hesaplandığında farklı sonuç veriyor. "
                            "Bu, eksik satırın komşu dönemlerle çeliştiğini gösterir; "
                            "kaynak sistemde bu kayıt doğrulanmalı."
                        ),
                        samples=samples,
                    )
                )

        filled = int(
            frame.select((pl.col(target).is_null() & pl.col("__fwd").is_not_null()).sum()).item()
        )
        if filled:
            frame = frame.with_columns(
                [
                    (pl.col(target).is_null() & pl.col("__fwd").is_not_null()).alias(
                        f"{target}{_IMPUTED_SUFFIX}"
                    ),
                    pl.coalesce([pl.col(target), pl.col("__fwd")]).alias(target),
                ]
            )
            imputed_columns.append(target)
            issues.append(
                QualityIssue(
                    code=rule.code,
                    title=rule.title,
                    severity=Severity.ORTA,
                    action=IssueAction.TURETILDI,
                    affected_rows=filled,
                    detail=rule.detail + ambiguous_detail,
                )
            )

        frame = frame.drop([c for c in ("__fwd", "__bwd") if c in frame.columns])

    return frame, issues, tuple(imputed_columns)


def _detect_period_gaps(frame: pl.DataFrame, pack: DatasetPack) -> QualityIssue | None:
    """Bir entity'nin veri setindeki bazi donemlerde hic kaydi yoksa isaretler."""
    ctx = pack.context
    all_periods = frame.get_column(ctx.period_key).unique().sort().to_list()
    if len(all_periods) < 2:
        return None

    per_entity = frame.group_by(ctx.entity_key).agg(pl.col(ctx.period_key).n_unique().alias("n"))
    incomplete = per_entity.filter(pl.col("n") < len(all_periods))
    if incomplete.height == 0:
        return None

    samples = tuple(
        f"{row[0]}: {row[1]}/{len(all_periods)} dönem" for row in incomplete.head(5).iter_rows()
    )
    return QualityIssue(
        code="PERIOD_GAP",
        title="Bazı kayıtlarda dönem boşlukları var",
        severity=Severity.ORTA,
        action=IssueAction.ISARETLENDI,
        affected_rows=incomplete.height,
        detail=(
            f"Veri seti {len(all_periods)} dönem içeriyor ancak bazı kayıtlar tüm "
            "dönemlerde bulunmuyor. Trend hesapları bu kayıtlar için daha az "
            "noktaya dayanır."
        ),
        samples=samples,
    )


def _quarantine_incomplete(
    frame: pl.DataFrame, pack: DatasetPack
) -> tuple[pl.DataFrame, pl.DataFrame, QualityIssue | None]:
    """Tamamlama sonrasi hala zorunlu alani eksik olan satirlari ayirir."""
    required = [c for c in pack.required_columns if c in frame.columns]
    if not required:
        return frame, frame.head(0), None

    incomplete_mask = pl.any_horizontal([pl.col(c).is_null() for c in required])
    quarantined = frame.filter(incomplete_mask)
    clean = frame.filter(~incomplete_mask)

    if quarantined.height == 0:
        return clean, quarantined, None

    ctx = pack.context
    samples = tuple(
        f"{row[0]} / {row[1]}"
        for row in quarantined.select([ctx.entity_key, ctx.period_key]).head(5).iter_rows()
    )
    return (
        clean,
        quarantined,
        QualityIssue(
            code="ROW_QUARANTINED",
            title="Tamamlanamayan satırlar analiz dışı bırakıldı",
            severity=Severity.YUKSEK,
            action=IssueAction.KARANTINA,
            affected_rows=quarantined.height,
            detail=(
                "Zorunlu alanları eksik olan ve veri setinin kendi iç tutarlılığından "
                "türetilemeyen satırlar. Yanlış sonuç üretmemek için hesaplamalara "
                "dahil edilmedi; ham hali ayrıca saklanıyor."
            ),
            samples=samples,
        ),
    )


def _check_integrity(frame: pl.DataFrame, pack: DatasetPack) -> list[QualityIssue]:
    """Pack'in butunluk kurallarini calistirir.

    Not: imputasyon uygulanmis satirlarin *hemen sonraki* donemi bu
    kontrollerden muaf tutulur -- aksi halde kendi doldurdugumuz deger
    yapay bir "mutabakat ihlali" uretir.
    """
    issues: list[QualityIssue] = []
    ctx = pack.context

    # Butunluk kurallari turetilmis kolonlara dayanir (or. mutabakat_farki,
    # maliyet_mom_yuzde). Analiz motorunun kullandigi ayni fonksiyonla
    # zenginlestiriyoruz ki iki taraf birbirinden ayrismasin.
    enriched = build_series(frame, pack)

    imputed_flags = [c for c in enriched.columns if c.endswith(_IMPUTED_SUFFIX)]
    if imputed_flags:
        # Kendi doldurdugumuz deger yapay bir "mutabakat ihlali" uretmesin:
        # imputasyon yapilan satir ve onu izleyen donem muaf tutulur.
        was_imputed = pl.any_horizontal([pl.col(c).fill_null(False) for c in imputed_flags])
        suppress = was_imputed | was_imputed.shift(1, fill_value=False).over(ctx.entity_key)
    else:
        suppress = pl.lit(False)

    for rule in pack.integrity_rules:
        try:
            violation = rule.violation(ctx) & ~suppress
            offending = enriched.filter(violation.fill_null(False))
        except Exception as exc:
            # Sessizce yutmuyoruz: eksik kolon genellikle pack'te bir hata
            # demektir ve gizlenirse kural hic calismadan "gecmis" gorunur.
            _log.warning(
                "Bütünlük kuralı çalıştırılamadı",
                extra={"rule": rule.code, "pack": pack.key, "error": str(exc)},
            )
            continue
        if offending.height == 0:
            continue

        sample_cols = [c for c in rule.sample_columns if c in offending.columns]
        if not sample_cols:
            sample_cols = [ctx.entity_key, ctx.period_key]
        samples = tuple(
            " / ".join(_fmt(v) for v in row)
            for row in offending.select(sample_cols).head(5).iter_rows()
        )
        issues.append(
            QualityIssue(
                code=rule.code,
                title=rule.title,
                severity=rule.severity,
                action=rule.action,
                affected_rows=offending.height,
                detail=rule.detail_template.format(count=offending.height),
                samples=samples,
            )
        )
    return issues


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ")
    return str(value)
