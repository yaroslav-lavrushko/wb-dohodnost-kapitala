"""Сборка сайта для GitHub Pages: веб-версия + расчётное ядро + демо-данные + готовый демо-отчёт.

    python scripts/build_site.py [--out _site]

Веб-версия считает в браузере (Pyodide) тем же пакетом wb_capital, что и командная строка.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELS = ["openpyxl==3.1.5", "et_xmlfile==2.0.0"]   # чистый Python, в Pyodide ставятся из файлов сайта


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "_site"))
    out = Path(ap.parse_args().out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copy(ROOT / "web" / "index.html", out / "index.html")
    (out / ".nojekyll").write_text("")

    # расчётное ядро
    with zipfile.ZipFile(out / "wb_capital.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "wb_capital").iterdir()):
            if f.suffix in (".py", ".json"):
                z.write(f, f"wb_capital/{f.name}")

    # колёса чистого Python для браузера
    wh = out / "wheels"
    wh.mkdir()
    subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary", ":all:", "-q",
                    "-d", str(wh), *WHEELS], check=True)
    (wh / "index.json").write_text(json.dumps(sorted(p.name for p in wh.glob("*.whl"))), encoding="utf-8")

    # демо-данные (выдуманные) и готовый демо-отчёт
    dd = out / "demo-data"
    dd.mkdir()
    names = []
    for f in sorted((ROOT / "demo" / "data").glob("*.xlsx")):
        shutil.copy(f, dd / f.name)
        names.append(f.name)
    (dd / "index.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    from wb_capital import Options, run
    res = run(Options(inputs=[str(ROOT / "demo" / "data")],
                      label="Демо-магазин «Северная косметика» · выдуманные данные"), out / "demo", log=lambda *_: None)
    if not res["ok"]:
        print("демо-отчёт не собрался:", res["errors"])
        return 1
    (out / "demo" / "доходность-капитала.html").rename(out / "demo" / "index.html")

    # шаблон каталога себестоимости
    import pandas as pd
    (out / "template").mkdir()
    with pd.ExcelWriter(out / "template" / "каталог-себестоимости-шаблон.xlsx") as w:
        pd.DataFrame([{"Номер поставки": 12345678, "Название товара": "артикул поставщика как в WB",
                       "Себестоимость": 250.0, "Кол-во в поставке": 100}]).to_excel(
            w, sheet_name="Каталог (себестоимость)", index=False)
    print(f"сайт собран: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
