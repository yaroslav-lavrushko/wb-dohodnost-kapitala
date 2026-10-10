"""Конвейер: файлы → раскладка по ролям → проверка входа → расчёт → отчёты.

Один вход для всех способов запуска: командная строка (cli.py), веб-версия в браузере (Pyodide)
и скилл Claude вызывают run().
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path

import pandas as pd

from . import capital, cogs, report, stock_io, wb_io


@dataclass
class Options:
    inputs: list = field(default_factory=list)      # папки или файлы — тип определяется по колонкам
    detail: list = field(default_factory=list)      # явные детализации
    catalog: list = field(default_factory=list)     # явные каталоги себестоимости
    stock: list = field(default_factory=list)       # явные остатки, можно «файл.xlsx@ГГГГ-ММ-ДД»
    config: str | None = None                       # свой config.json (по умолчанию — встроенный)
    aliases: str | None = None                      # aliases.json: «артикул WB → название в каталоге»
    commission_pp: float | None = None              # сценарий «комиссия +N п.п.»
    stock_date: str = ""                            # дата снимка для остатков без даты
    test_stock_days: float | None = None            # ТЕСТОВЫЙ запас артикулам без остатка (помечается)
    label: str = ""                                 # подпись прогона


def default_config() -> dict:
    return json.loads(resources.files("wb_capital").joinpath("config.json").read_text(encoding="utf-8"))


def classify(paths: list[Path]) -> tuple[dict, list[str]]:
    """Раскладывает файлы по ролям по содержимому колонок."""
    roles = {"detail": [], "catalog": [], "stock": [], "unknown": []}
    notes = []
    files = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in (".xlsx", ".zip")
                            and not f.name.startswith(("~$", ".")))
        elif p.is_file():
            files.append(p)
        else:
            notes.append(f"путь не найден: {p}")
    for f in files:
        n = cogs.nfc(f.name).lower()
        if f.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(f) as z:
                    ok = any(m.lower().endswith(".xlsx") for m in z.namelist())
            except zipfile.BadZipFile:
                ok = False
            (roles["detail"] if ok else roles["unknown"]).append(f)
            continue
        if any(s in n for s in ("сверка", "общее", "общий", "себестоимость_")):
            notes.append(f"пропущен (склейка/сверка/расчёт, не исходная выгрузка): {f.name}")
            continue
        try:
            xl = pd.ExcelFile(f)
        except Exception as e:
            notes.append(f"{f.name}: не читается ({e.__class__.__name__})")
            continue
        head_cols = {cogs.nfc(str(c)).strip().lower() for sh in xl.sheet_names[:3] for c in xl.parse(sh, nrows=0).columns}
        if "обоснование для оплаты" in head_cols:
            roles["detail"].append(f)
        elif cogs.looks_like_catalog(xl):
            roles["catalog"].append(f)
        elif stock_io.sniff(xl):
            roles["stock"].append(f)
        else:
            roles["unknown"].append(f)
            first = xl.parse(xl.sheet_names[0], nrows=0).columns
            miss = stock_io.missing_report(first)
            if "артикул" not in miss:   # артикул есть — значит, это остатки без количества
                notes.append(f"НЕ РАСПОЗНАН {f.name}: похоже на остатки, но не хватает колонки: {miss}")
            else:
                notes.append(f"НЕ РАСПОЗНАН {f.name}: не детализация (нет «Обоснование для оплаты»), не каталог "
                             f"(«Номер поставки», «Название товара», «Себестоимость») и не остатки ({miss})")
    # zip-дубли xlsx того же отчёта отсеет wb_io.discover
    return roles, notes


def run(o: Options, out: str | Path, log=print) -> dict:
    """Возвращает {'ok': bool, 'paths': [...], 'errors', 'warnings', 'summary'}. Ничего не роняет на плохом входе."""
    a = o
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else default_config()

    roles, notes = classify([Path(p).expanduser() for p in a.inputs])
    roles["detail"] += [Path(p).expanduser() for p in a.detail]
    roles["catalog"] += [Path(p).expanduser() for p in a.catalog]
    stock_specs = [(p, None) for p in roles["stock"]] + [stock_io.split_spec(p) for p in a.stock]
    errors, warnings = [], []
    warnings += [n for n in notes if n.startswith("НЕ РАСПОЗНАН")]
    notes = [n for n in notes if not n.startswith("НЕ РАСПОЗНАН")]
    for f in roles["unknown"]:
        if f.suffix.lower() == ".zip":
            warnings.append(f"НЕ РАСПОЗНАН {f.name}: zip без xlsx внутри — пропущен")

    # 1. детализации
    det = {"df": None, "files": [], "errors": [], "warnings": [], "notes": []}
    if roles["detail"]:
        det = wb_io.load([str(p) for p in roles["detail"]])
        errors += det["errors"]
        warnings += det["warnings"]
        notes += det["notes"]
    else:
        errors.append("нет ни одной детализации WB (нужен «Еженедельный детализированный отчёт», колонка «Обоснование для оплаты»)")
    # «Кол-во» и «Артикул поставщика» для этого инструмента обязательны
    if det["df"] is not None:
        d = det["df"]
        if d["article"].isna().all():
            errors.append("в детализациях нет колонки «Артикул поставщика» — без неё не посчитать товары")
        if pd.to_numeric(d["qty"], errors="coerce").fillna(0).eq(0).all():
            errors.append("в детализациях нет колонки «Кол-во» — без неё не посчитать штуки и себестоимость")

    # 2. каталог
    catalog, cat_src = {}, []
    if not roles["catalog"]:
        errors.append("нет каталога себестоимости (лист «Каталог (себестоимость)»: «Номер поставки», «Название товара», «Себестоимость»)")
    for f in roles["catalog"]:
        c = cogs.load_catalog(f)
        errors += c["errors"]
        for k, v in c["index"].items():
            catalog.setdefault(k, []).extend(v)
        if not c["errors"]:
            cat_src.append(f"{f.name} / {c['sheet']} ({c['rows']} строк)")
    for k in catalog:
        catalog[k] = sorted(set(catalog[k]))
    aliases = cogs.load_aliases(Path(a.aliases)) if a.aliases else {}

    # 3. остатки (необязательны: без них — только P&L и пометка)
    default_date = stock_io.parse_date(a.stock_date)
    recs, stock_src = [], []
    for n, (f, d) in enumerate(stock_specs):
        s = stock_io.load(f, d, default_date, cfg["stock"]["include_in_transit"])
        if s["records"] is not None:
            s["records"]["source"] = s["records"]["source"] + f" [файл №{n + 1}]"
        errors += s["errors"]
        warnings += s["warnings"]
        notes += s["notes"]
        if s["records"] is not None:
            recs.append(s["records"])
            stock_src.append(f.name + (f" @ {d:%d.%m.%Y}" if d is not None else ""))
    stock_df = pd.concat(recs, ignore_index=True) if recs else None
    if stock_df is None and not a.test_stock_days:
        warnings.append("нет файла остатков — доходность капитала не посчитать, будет только P&L по артикулам")

    meta = {"label": a.label, "run_date": date.today().isoformat(), "details": det["files"],
            "catalog": cat_src, "stock": stock_src, "stock_date": a.stock_date,
            "notes": notes, "warnings": warnings, "errors": errors}

    if errors:
        report.write_errors(out, meta)
        log("❌ Входные данные не подходят:")
        for e in errors:
            log("  – " + e)
        log(f"Подробно: {out / 'ОШИБКИ-входных-данных.txt'}")
        return {"ok": False, "paths": [out / "ОШИБКИ-входных-данных.txt"], "errors": errors,
                "warnings": warnings, "summary": None}

    res = capital.compute(det["df"], catalog, aliases, stock_df, cfg, a.test_stock_days, a.commission_pp,
                          a.stock_date)
    warnings += res["checks"]["stock_warnings"]
    for m in res["checks"]["merged_articles"]:
        notes.append("один код WB — несколько названий артикула, считаю одним товаром: " + " = ".join(f"«{x}»" for x in m))
    paths = report.write(out, res, meta, cfg)
    t = res["table"]
    log(f"✓ Период: {res['checks']['period'][0]:%d.%m.%Y}–{res['checks']['period'][1]:%d.%m.%Y} "
        f"({res['days']} дн.) · артикулов: {len(t)}")
    log("✓ Вердикты: " + ", ".join(f"{k} — {v}" for k, v in t["Вердикт"].value_counts().items()))
    log(f"✓ Сумма по артикулам = итог кабинета: {'да' if res['checks']['conserved'] else 'НЕТ'}")
    for w in warnings:
        log("⚠ " + w)
    for p in paths:
        log(f"→ {p}")
    return {"ok": True, "paths": paths, "errors": [], "warnings": warnings,
            "summary": {"verdicts": t["Вердикт"].value_counts().to_dict(),
                        "conserved": res["checks"]["conserved"], "days": res["days"]},
            "result": res}
