"""Tes aturan murni 5.4/5.5/5.6 (tanpa database)."""

from __future__ import annotations

import rules
import seed_data


def build_units() -> list[dict]:
    units: list[dict] = []
    number = 1
    for idx, (kode, judul, indicators, _proposed) in enumerate(seed_data.UNITS, start=1):
        inds = []
        for urutan, teks in enumerate(indicators, start=1):
            inds.append({"kode": f"IND-{number:03d}", "teks": teks, "urutan": urutan})
            number += 1
        units.append({"kode": kode, "judul": judul, "urutan": idx, "indicators": inds})
    return units


def build_subs() -> list[dict]:
    return [
        {"kode": kode, "judul": judul, "urutan": urutan, "unit_kodes": list(unit_kodes)}
        for kode, judul, urutan, unit_kodes in seed_data.SUB_COMPETENCIES
    ]


def all_scores(units: list[dict], value: int = 3) -> dict[str, int]:
    return {
        ind["kode"]: value
        for unit in units
        for ind in unit["indicators"]
    }


def zero_scores(units: list[dict]) -> dict[str, int]:
    return all_scores(units, 0)


def fill_unit(scores: dict[str, int], units: list[dict], kode: str, value: int = 3) -> None:
    unit = next(u for u in units if u["kode"] == kode)
    for ind in unit["indicators"]:
        scores[ind["kode"]] = value


def test_seed_persis_tabel_5_2_dan_total_61_indikator():
    expected = [
        ("J.611000.003.02", "Merancang Topologi Jaringan", 2),
        ("J.611000.004.01", "Merancang Pengalamatan Jaringan", 2),
        ("J.611000.008.02", "Menyiapkan Kabel Jaringan", 2),
        ("J.611000.009.02", "Memasang Kabel Jaringan", 3),
        ("J.611000.010.02", "Memasang Jaringan Nirkabel", 4),
        ("J.611000.011.02", "Memasang Perangkat Jaringan ke dalam Sistem Jaringan", 13),
        ("J.611000.012.02", "Mengkonfigurasi Switch pada Jaringan", 4),
        ("J.611000.006.01", "Merancang Keamanan Jaringan", 11),
        (
            "J.611000.015.02",
            "Memonitor Keamanan dan Pengaturan Akun Pengguna dalam Jaringan Komputer",
            3,
        ),
        ("J.611000.020.01", "Mengoptimalkan Kinerja Sistem Jaringan", 9),
        ("J.611000.017.01", "Mengidentifikasi Sumber Kerusakan", 2),
        ("J.611000.018.02", "Memperbaiki Kerusakan Konfigurasi Jaringan", 2),
        (
            "J.611000.022.01",
            "Melakukan Backup dan Restore Konfigurasi Perangkat Jaringan",
            4,
        ),
    ]
    actual = [(kode, judul, len(inds)) for kode, judul, inds, _ in seed_data.UNITS]
    assert actual == expected
    assert sum(item[2] for item in actual) == 61

    mapping = {kode: units for kode, _judul, _urutan, units in seed_data.SUB_COMPETENCIES}
    assert mapping == {
        "SK-01": ["J.611000.003.02", "J.611000.004.01"],
        "SK-02": [
            "J.611000.009.02",
            "J.611000.010.02",
            "J.611000.011.02",
        ],
        "SK-03": [
            "J.611000.009.02",
            "J.611000.011.02",
            "J.611000.012.02",
            "J.611000.022.01",
        ],
        "SK-04": ["J.611000.006.01", "J.611000.011.02", "J.611000.012.02"],
        "SK-05": ["J.611000.017.01", "J.611000.018.02", "J.611000.022.01"],
    }


def test_semua_13_unit_lulus_kompeten_penuh():
    units = build_units()
    result = rules.compute_result(units, build_subs(), all_scores(units), "Ahmad (03)")
    assert result["outcome"] == "kompeten_penuh"
    assert result["predicate"] == "Sangat Mahir"
    assert len(result["unit_passed"]) == 13
    assert result["statement"] == (
        "Peserta Ahmad (03) dinyatakan kompeten sebagai Junior Network Technician "
        "dengan predikat Sangat Mahir."
    )


def test_sub_kompetensi_terpenuhi_dipilih():
    units = build_units()
    scores = zero_scores(units)
    fill_unit(scores, units, "J.611000.003.02")
    fill_unit(scores, units, "J.611000.004.01")
    result = rules.compute_result(units, build_subs(), scores, "Ahmad (03)")
    assert result["outcome"] == "kompeten_sub"
    assert result["selected_sub"]["kode"] == "SK-01"
    assert result["predicate"] == "Sangat Mahir"
    assert result["statement"] == (
        "Peserta Ahmad (03) dinyatakan kompeten pada sub kompetensi "
        "Perancang Jaringan Muda dengan predikat Sangat Mahir."
    )


def test_seri_sub_pilih_urutan_teratas():
    units = build_units()
    scores = zero_scores(units)
    for kode in (
        "J.611000.003.02",
        "J.611000.004.01",
        "J.611000.017.01",
        "J.611000.018.02",
        "J.611000.022.01",
    ):
        fill_unit(scores, units, kode)
    result = rules.compute_result(units, build_subs(), scores, "Ahmad (03)")
    assert result["outcome"] == "kompeten_sub"
    assert [s["kode"] for s in result["sub_fulfilled"][:2]] == ["SK-01", "SK-05"]
    assert result["selected_sub"]["kode"] == "SK-01"


def test_sub_dipilih_rata_rata_tertinggi():
    units = build_units()
    scores = zero_scores(units)
    fill_unit(scores, units, "J.611000.003.02")
    fill_unit(scores, units, "J.611000.004.01")
    fill_unit(scores, units, "J.611000.009.02")
    fill_unit(scores, units, "J.611000.022.01")
    unit_011 = next(u for u in units if u["kode"] == "J.611000.011.02")
    for index, ind in enumerate(unit_011["indicators"]):
        scores[ind["kode"]] = 3 if index < 2 else 2
    unit_012 = next(u for u in units if u["kode"] == "J.611000.012.02")
    for index, ind in enumerate(unit_012["indicators"]):
        scores[ind["kode"]] = 3 if index < 1 else 2
    result = rules.compute_result(units, build_subs(), scores, "Ahmad (03)")
    assert result["outcome"] == "kompeten_sub"
    assert result["selected_sub"]["kode"] == "SK-01"
    assert result["selected_sub"]["average_percent"] == 100.0
    sk03 = next(s for s in result["sub_competencies"] if s["kode"] == "SK-03")
    assert sk03["fulfilled"] is True
    assert sk03["average_percent"] < 100.0


def test_kombinasi_praktik_masuk_sk02_sk03_sk04():
    units = build_units()
    subs = build_subs()

    # Kasus 1: 009.02, 011.02, 012.02, 006.01, 022.01 -> memenuhi SK-03 dan SK-04
    scores_1 = zero_scores(units)
    for kode in ["J.611000.009.02", "J.611000.011.02", "J.611000.012.02", "J.611000.006.01", "J.611000.022.01"]:
        fill_unit(scores_1, units, kode)
    res_1 = rules.compute_result(units, subs, scores_1, "Andi (01)")
    assert res_1["outcome"] == "kompeten_sub"
    assert {"SK-03", "SK-04"} <= {s["kode"] for s in res_1["sub_fulfilled"]}

    # Kasus 2: 009.02, 010.02, 011.02, 012.02, 022.01 -> memenuhi SK-02 dan SK-03
    scores_2 = zero_scores(units)
    for kode in ["J.611000.009.02", "J.611000.010.02", "J.611000.011.02", "J.611000.012.02", "J.611000.022.01"]:
        fill_unit(scores_2, units, kode)
    res_2 = rules.compute_result(units, subs, scores_2, "Budi (02)")
    assert res_2["outcome"] == "kompeten_sub"
    assert {"SK-02", "SK-03"} <= {s["kode"] for s in res_2["sub_fulfilled"]}


def test_unit_lulus_tanpa_sub_jadi_belum_kompeten():
    units = build_units()
    scores = zero_scores(units)
    fill_unit(scores, units, "J.611000.008.02")
    result = rules.compute_result(units, build_subs(), scores, "Ahmad (03)")
    assert result["outcome"] == "belum_kompeten"
    assert result["unit_passed"] == ["J.611000.008.02"]
    assert result["predicate"] is None
    assert result["technical_percent"] > 0
    assert result["statement"] == "Peserta Ahmad (03) dinyatakan belum kompeten."


def test_min_sub_passed_mewajibkan_jumlah_sub_kompetensi():
    units = build_units()
    scores = zero_scores(units)
    for kode in ["J.611000.003.02", "J.611000.004.01"]:
        fill_unit(scores, units, kode)
    res_one = rules.compute_result(units, build_subs(), scores, "Ahmad (03)", {"min_sub_passed": 1})
    assert res_one["outcome"] == "kompeten_sub"
    res_two = rules.compute_result(units, build_subs(), scores, "Ahmad (03)", {"min_sub_passed": 2})
    assert res_two["outcome"] == "belum_kompeten"


def test_tidak_ada_unit_lulus_belum_kompeten():
    units = build_units()
    result = rules.compute_result(units, build_subs(), zero_scores(units), "Ahmad (03)")
    assert result["outcome"] == "belum_kompeten"
    assert result["predicate"] is None
    assert result["statement"] == "Peserta Ahmad (03) dinyatakan belum kompeten."


def test_indikator_kosong_dihitung_nol_dan_ditandai():
    unit = build_units()[0]
    scores = {unit["indicators"][0]["kode"]: 3, unit["indicators"][1]["kode"]: None}
    summary = rules.compute_unit_results([unit], scores)[0]
    assert summary["total_score"] == 3
    assert summary["percent"] == 50.0
    assert summary["empty_count"] == 1
    assert summary["passed"] is False


def test_batas_ambang_70_persen_24_dari_33_lulus_23_gagal():
    unit = {
        "kode": "U-33",
        "judul": "Unit 33 indikator",
        "urutan": 1,
        "indicators": [{"kode": f"I-{i}", "teks": f"Indikator {i}", "urutan": i} for i in range(1, 34)],
    }
    scores_24 = {f"I-{i}": 3 for i in range(1, 25)}
    scores_23 = {f"I-{i}": 3 for i in range(1, 24)}
    assert rules.compute_unit_results([unit], scores_24)[0]["passed"] is True
    assert rules.compute_unit_results([unit], scores_24)[0]["percent"] == 72.73
    assert rules.compute_unit_results([unit], scores_23)[0]["passed"] is False
    assert rules.compute_unit_results([unit], scores_23)[0]["percent"] == 69.7


def test_predikat_batas_90_80_70():
    def one_unit(total: int) -> dict:
        unit = {
            "kode": "U-10",
            "judul": "Unit 10 indikator",
            "urutan": 1,
            "indicators": [{"kode": f"I-{i}", "teks": "x", "urutan": i} for i in range(1, 11)],
        }
        scores = {}
        remaining = total
        for ind in unit["indicators"]:
            value = min(3, remaining)
            scores[ind["kode"]] = value
            remaining -= value
        return rules.compute_result([unit], [], scores, "Ahmad (03)")

    assert one_unit(27)["predicate"] == "Sangat Mahir"
    assert one_unit(24)["predicate"] == "Mahir"
    assert one_unit(21)["predicate"] == "Cakap"
    assert one_unit(20)["outcome"] == "belum_kompeten"


def test_label_peserta_dan_semua_format_pernyataan():
    assert rules.participant_label("Ahmad", "03") == "Ahmad (03)"
    assert rules.participant_label("Ahmad", None) == "Ahmad"
    units = build_units()
    subs = build_subs()

    penuh = rules.compute_result(units, subs, all_scores(units), "Ahmad (03)")
    assert penuh["statement"].startswith("Peserta Ahmad (03) dinyatakan kompeten sebagai")

    scores = zero_scores(units)
    fill_unit(scores, units, "J.611000.008.02")
    unit_only = rules.compute_result(units, subs, scores, "Ahmad (03)")
    assert unit_only["statement"] == "Peserta Ahmad (03) dinyatakan belum kompeten."

    belum = rules.compute_result(units, subs, zero_scores(units), "Ahmad (03)")
    assert belum["statement"] == "Peserta Ahmad (03) dinyatakan belum kompeten."
