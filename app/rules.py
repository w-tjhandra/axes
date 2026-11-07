"""Aturan perhitungan kelulusan multi-skema asesmen kompetensi.

Penjelasan Teknis (1-2 kalimat): Seluruh fungsi pada modul ini dirancang sebagai *pure function*
(tidak menyentuh database atau disk) sehingga hasil kalkulasi skor 100% deterministik dan mudah
diuji pada berbagai skema asesmen tanpa efek samping.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Mapping

DEFAULT_CONFIG: dict[str, Any] = {
    "pass_threshold": 70,
    "predicate_sangat_mahir": 90,
    "predicate_mahir": 80,
    "predicate_cakap": 70,
    "scheme_nama": "Junior Network Technician",
    "templates": {
        "penuh": (
            "Peserta {peserta} dinyatakan kompeten sebagai Junior Network "
            "Technician dengan predikat {predikat}."
        ),
        "sub": (
            "Peserta {peserta} dinyatakan kompeten pada sub kompetensi {sub} "
            "dengan predikat {predikat}."
        ),
        "unit": (
            "Peserta {peserta} dinyatakan kompeten pada unit {unit} dengan "
            "predikat {predikat}."
        ),
        "belum": "Peserta {peserta} dinyatakan belum kompeten.",
    },
}

OUTCOME_LABELS = {
    "kompeten_penuh": "Kompeten Penuh",
    "kompeten_sub": "Kompeten pada Sub Kompetensi",
    "kompeten_unit": "Kompeten pada Unit",
    "belum_kompeten": "Belum Kompeten",
}

PREDICATE_TIDAK_MEMENUHI = "Tidak Memenuhi"


def participant_label(nama: str, nomor: str | int | None) -> str:
    """Label peserta untuk pernyataan hasil, contoh: ``Ahmad (03)``."""
    nama = (nama or "").strip()
    nomor = "" if nomor is None else str(nomor).strip()
    if nama and nomor:
        return f"{nama} ({nomor})"
    return nama or nomor


def unit_percent(total_score: int, indicator_count: int) -> float:
    """Persen nilai unit, dibulatkan 2 desimal."""
    if indicator_count <= 0:
        return 0.0
    return round((total_score / (3 * indicator_count)) * 100, 2)


def is_unit_passed(total_score: int, indicator_count: int, pass_threshold: int = 70) -> bool:
    """Lulus unit bila persentase mencapai ambang batas (default 70%: total * 10 >= 21 * n)."""
    if indicator_count <= 0:
        return False
    if pass_threshold == 70:
        return total_score * 10 >= 21 * indicator_count
    return (total_score * 100) >= (pass_threshold * 3 * indicator_count)


def predicate_for(average_percent: float | None, config: Mapping[str, Any] | None = None) -> str | None:
    """Predikat dari rata-rata persen unit lulus."""
    if average_percent is None:
        return None
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if average_percent >= float(cfg["predicate_sangat_mahir"]):
        return "Sangat Mahir"
    if average_percent >= float(cfg["predicate_mahir"]):
        return "Mahir"
    if average_percent >= float(cfg["predicate_cakap"]):
        return "Cakap"
    return PREDICATE_TIDAK_MEMENUHI


def _normalise_units(units: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(unit) for unit in units]


def _score_value(scores: Mapping[str, Any], kode: str) -> int | None:
    value = scores.get(kode)
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value < 0 or value > 3:
        return None
    return value


def compute_unit_results(
    units: Iterable[Mapping[str, Any]],
    scores: Mapping[str, Any],
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Hitung ringkasan tiap unit dari daftar unit + skor indikator."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    threshold = int(cfg.get("pass_threshold", 70))
    results: list[dict[str, Any]] = []
    for unit in _normalise_units(units):
        indicators = list(unit.get("indicators") or [])
        total = 0
        filled = 0
        empty: list[str] = []
        for ind in indicators:
            kode = str(ind.get("kode"))
            value = _score_value(scores, kode)
            if value is None:
                empty.append(kode)
            else:
                filled += 1
                total += value
        n = len(indicators)
        percent = unit_percent(total, n)
        results.append(
            {
                "kode": unit.get("kode"),
                "judul": unit.get("judul"),
                "urutan": unit.get("urutan"),
                "total_score": total,
                "max_score": 3 * n,
                "indicator_count": n,
                "filled": filled,
                "empty_count": len(empty),
                "empty_indicators": empty,
                "percent": percent,
                "passed": is_unit_passed(total, n, threshold),
            }
        )
    return results


def _rank_sub_competencies(
    sub_competencies: Iterable[Mapping[str, Any]],
    by_code: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluasi dan urutkan sub-kompetensi berdasarkan rata-rata skor tertinggi."""
    sub_ranked: list[dict[str, Any]] = []
    for sub in sub_competencies:
        member_codes = [str(code) for code in (sub.get("unit_kodes") or [])]
        members = [by_code[code] for code in member_codes if code in by_code]
        fulfilled = (
            bool(member_codes)
            and len(members) == len(member_codes)
            and all(member["passed"] for member in members)
        )
        avg = round(mean([member["percent"] for member in members]), 2) if members else 0.0
        sub_ranked.append(
            {
                "kode": sub.get("kode"),
                "judul": sub.get("judul"),
                "urutan": sub.get("urutan"),
                "unit_kodes": member_codes,
                "fulfilled": fulfilled,
                "average_percent": avg,
            }
        )
    sub_ranked.sort(key=lambda s: (-s["average_percent"], s["urutan"] or 0))
    return sub_ranked


def compute_result(
    units: Iterable[Mapping[str, Any]],
    sub_competencies: Iterable[Mapping[str, Any]],
    scores: Mapping[str, Any],
    participant: str,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Hitung keputusan akhir asesmen lintas skema."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    unit_results = compute_unit_results(units, scores, cfg)
    by_code = {str(u["kode"]): u for u in unit_results}
    passed = [u for u in unit_results if u["passed"]]
    failed = [u for u in unit_results if not u["passed"]]
    passed_codes = [str(u["kode"]) for u in passed]
    failed_codes = [str(u["kode"]) for u in failed]
    empty_indicators = [kode for u in unit_results for kode in u["empty_indicators"]]

    all_passed = bool(unit_results) and all(u["passed"] for u in unit_results)
    sub_ranked = _rank_sub_competencies(sub_competencies, by_code)
    fulfilled_subs = [s for s in sub_ranked if s["fulfilled"]]

    selected_sub: dict[str, Any] | None = None
    if all_passed:
        outcome = "kompeten_penuh"
    elif fulfilled_subs:
        selected_sub = fulfilled_subs[0]
        outcome = "kompeten_sub"
    elif passed:
        outcome = "kompeten_unit"
    else:
        outcome = "belum_kompeten"

    average_passed = round(mean([u["percent"] for u in passed]), 2) if passed else None
    predicate = predicate_for(average_passed, cfg)
    statement = _build_statement(cfg, outcome, participant, predicate, selected_sub, passed_codes)

    return {
        "outcome": outcome,
        "outcome_label": OUTCOME_LABELS[outcome],
        "predicate": predicate,
        "average_percent": average_passed,
        "unit_passed": passed_codes,
        "unit_failed": failed_codes,
        "unit_results": unit_results,
        "sub_competencies": sub_ranked,
        "sub_fulfilled": fulfilled_subs,
        "selected_sub": selected_sub,
        "statement": statement,
        "empty_count": len(empty_indicators),
        "empty_indicators": empty_indicators,
        "total_score": sum(u["total_score"] for u in unit_results),
        "max_score": sum(u["max_score"] for u in unit_results),
    }


def _build_statement(
    cfg: Mapping[str, Any],
    outcome: str,
    participant: str,
    predicate: str | None,
    selected_sub: dict[str, Any] | None,
    passed_codes: list[str],
) -> str:
    skema = str(cfg.get("scheme_nama") or "Junior Network Technician")
    if outcome == "kompeten_penuh":
        return _format_statement(
            cfg, "penuh", peserta=participant, predikat=predicate or "", skema=skema
        )
    if outcome == "kompeten_sub" and selected_sub:
        return _format_statement(
            cfg,
            "sub",
            peserta=participant,
            sub=selected_sub.get("judul") or selected_sub.get("kode") or "",
            predikat=predicate or "",
            skema=skema,
        )
    if outcome == "kompeten_unit":
        return _format_statement(
            cfg, "unit", peserta=participant, unit=", ".join(passed_codes), predikat=predicate or "", skema=skema
        )
    return _format_statement(cfg, "belum", peserta=participant, skema=skema)


def _format_statement(config: Mapping[str, Any], key: str, **values: Any) -> str:
    templates = config.get("templates") or DEFAULT_CONFIG["templates"]
    default = DEFAULT_CONFIG["templates"][key]
    template = templates.get(key, default) if isinstance(templates, Mapping) else default
    try:
        return str(template).format(**values)
    except (KeyError, IndexError, ValueError):
        return str(default).format(**values)
