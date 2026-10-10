"""Тесты на выдуманных данных. Эталоны в tests/golden/ сняты до переупаковки кода в пакет и сверены
с прежней версией — любое изменение цифр должно быть осознанным (перегенерировать эталон)."""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest

from wb_capital import Options, run
from wb_capital.cli import main as cli_main

HERE = Path(__file__).resolve().parent
FX = HERE / "fixtures"
DEMO = HERE.parent / "demo" / "data"
quiet = dict(log=lambda *_: None)


def snap(res):
    t = res["result"]["table"]
    items = []
    for _, r in t.sort_values("Артикул").iterrows():
        def g(c):
            v = r[c]
            return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 2)
        items.append({"article": r["Артикул"], "verdict": r["Вердикт"], "profit": g("Прибыль"),
                      "capital": g("Капитал в остатке"), "return_pct": g("Доходность капитала, %"),
                      "stock_days": g("Запас, дней"), "excess": g("Лишний запас, ₽")})
    locs = res["result"]["locations"]
    return {"items": items,
            "locations": {r["Место хранения"]: round(float(r["Деньги по себестоимости"]), 2) for _, r in locs.iterrows()}}


def approx_equal(a, b):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(approx_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, (int, float)):
        return abs(a - b) <= 0.02 + 1e-6 * abs(a)
    return a == b


@pytest.mark.parametrize("name,opts", [
    ("sintetika", {}),
    ("sintetika_test_stock", {"test_stock_days": 45, "commission_pp": 5}),
])
def test_golden(tmp_path, name, opts):
    res = run(Options(inputs=[str(FX / "sintetika")], **opts), tmp_path, **quiet)
    assert res["ok"]
    golden = json.loads((HERE / "golden" / f"{name}.json").read_text(encoding="utf-8"))
    assert approx_equal(snap(res), golden)


def test_all_verdicts_and_places(tmp_path):
    res = run(Options(inputs=[str(FX / "sintetika")]), tmp_path, **quiet)
    verdicts = set(res["result"]["table"]["Вердикт"])
    assert {"развивать", "сократить закупку", "держать", "выводить", "нет продаж в периоде"} <= verdicts
    assert set(res["result"]["locations"]["Место хранения"]) == {"Склады маркетплейса", "Склад Подольск", "Склад Москва"}
    assert res["summary"]["conserved"]
    assert (tmp_path / "доходность-капитала.xlsx").exists() and (tmp_path / "доходность-капитала.html").exists()


def test_rows_without_header_are_ignored_and_reported(tmp_path):
    res = run(Options(inputs=[str(FX / "sintetika")]), tmp_path, **quiet)
    cream = res["result"]["table"].set_index("Артикул").loc["Тест крем 50 мл"]
    assert cream["Остаток, шт"] == pytest.approx(142.5)          # 999 шт из блока без заголовка не учтены
    assert any("без своего заголовка" in w for w in res["warnings"])


def test_same_snapshot_twice_counted_once(tmp_path):
    src = FX / "sintetika"
    d = tmp_path / "in"
    shutil.copytree(src, d)
    shutil.copy(src / "остатки-WB-2026-03-15.xlsx", d / "копия-остатки-WB-2026-03-15.xlsx")
    a = run(Options(inputs=[str(src)]), tmp_path / "a", **quiet)
    b = run(Options(inputs=[str(d)]), tmp_path / "b", **quiet)
    assert approx_equal(snap(a), snap(b))
    assert any("точная копия" in w for w in b["warnings"])


def test_broken_inputs_name_missing_columns(tmp_path):
    res = run(Options(inputs=[str(FX / "bitye")]), tmp_path, **quiet)
    assert not res["ok"]
    text = " ".join(res["errors"])
    assert "«Хранение»" in text and "«Srid»" in text and "«Себестоимость»" in text
    assert any("количество" in w for w in res["warnings"])
    assert (tmp_path / "ОШИБКИ-входных-данных.txt").exists()


def test_cli_exit_codes(tmp_path):
    assert cli_main(["--in", str(FX / "sintetika"), "--out", str(tmp_path / "ok")]) == 0
    assert cli_main(["--in", str(FX / "bitye"), "--out", str(tmp_path / "bad")]) == 2


def test_demo_shop(tmp_path):
    res = run(Options(inputs=[str(DEMO)]), tmp_path, **quiet)
    assert res["ok"] and res["summary"]["conserved"]
    t = res["result"]["table"]
    assert len(t) == 30
    assert {"развивать", "сократить закупку", "держать", "выводить"} <= set(t["Вердикт"])
    assert len(res["result"]["locations"]) == 3


def test_one_wb_code_two_names_is_one_product(tmp_path):
    """Код WB — главный: два названия артикула под одним кодом считаются одним товаром."""
    import pandas as pd
    d = tmp_path / "in"
    shutil.copytree(FX / "sintetika", d)
    f = d / "Еженедельный детализированный отчет №T002_000000.xlsx"
    df = pd.read_excel(f)
    df.loc[df["Артикул поставщика"] == "Тест крем 50 мл", "Артикул поставщика"] = "тест крем 50мл (новая карточка)"
    df.to_excel(f, index=False)
    res = run(Options(inputs=[str(d)]), tmp_path / "out", **quiet)
    names = set(res["result"]["table"]["Артикул"])
    assert not any("новая карточка" in n for n in names)
    assert res["result"]["checks"]["merged_articles"]
