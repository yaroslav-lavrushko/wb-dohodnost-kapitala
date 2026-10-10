"""Себестоимость по паре «поставка × артикул».

Алгоритм:
    1) точное совпадение (поставка, артикул) → цена этой поставки;
    2) нет точного → ближайшая поставка ≤ нашей с этим товаром;
    3) все поставки товара позже → первая (минимальный номер);
    4) товара нет в каталоге → цены нет, строка помечается.
Сопоставление — по нормализованному названию (NFC, нижний регистр, сжатые пробелы)
плюс словарь алиасов «артикул WB → название в каталоге».
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

CATALOG_SHEET = "Каталог (себестоимость)"
STATUS_RU = {
    "exact": "точно по поставке",
    "alias_exact": "точно по поставке (алиас)",
    "nearest_le": "по ближайшей более ранней поставке",
    "alias_nearest_le": "по ближайшей более ранней поставке (алиас)",
    "first": "по первой поставке в каталоге",
    "alias_first": "по первой поставке в каталоге (алиас)",
    "missing": "нет в каталоге",
}


def nfc(s):
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def norm(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    # точка в конце названия — вторая карточка того же товара в WB («…75 мл.»): считаем одним товаром
    # «100мл» и «100 мл» — одно и то же
    t = " ".join(nfc(str(s)).strip().lower().replace("ё", "е").split()).rstrip(" .")
    return re.sub(r"(\d)\s*(мл|гр|г|л|шт)\b", r"\1 \2", t)


def catalog_columns(cols) -> dict:
    """Ищет колонки каталога по смыслу. Возвращает {supply,name,norm,price} (что нашлось)."""
    cols = [nfc(str(c)) for c in cols]
    low = {c: c.lower() for c in cols}
    res = {}
    res["supply"] = next((c for c in cols if "поставк" in low[c]), None)
    res["name"] = next((c for c in cols if "название" in low[c] and "норм" not in low[c]), None)
    res["norm"] = next((c for c in cols if "норм" in low[c]), None)
    res["price"] = next((c for c in cols if "себест" in low[c]), None)
    return res


def looks_like_catalog(xl: pd.ExcelFile) -> str | None:
    """Имя листа-каталога или None."""
    names = [nfc(s) for s in xl.sheet_names]
    if CATALOG_SHEET in names:
        return xl.sheet_names[names.index(CATALOG_SHEET)]
    for sh in xl.sheet_names:
        cm = catalog_columns(xl.parse(sh, nrows=0).columns)
        if cm["supply"] and cm["name"] and cm["price"]:
            return sh
    return None


def load_catalog(path: Path, sheet: str | None = None) -> dict:
    """{'index': {норм_название: [(поставка, цена), ...]}, 'rows': n, 'errors': [...]}"""
    xl = pd.ExcelFile(path)
    sheet = sheet or looks_like_catalog(xl)
    if sheet is None:
        return {"index": {}, "rows": 0,
                "errors": [f"{path.name}: не найден лист каталога себестоимости — нужен лист «{CATALOG_SHEET}» "
                           f"или колонки «Номер поставки», «Название товара», «Себестоимость»"]}
    df = xl.parse(sheet)
    df.columns = [nfc(str(c)) for c in df.columns]
    cm = catalog_columns(df.columns)
    missing = [n for n, k in [("Номер поставки", "supply"), ("Название товара", "name"), ("Себестоимость", "price")]
               if not cm[k]]
    if missing:
        return {"index": {}, "rows": 0,
                "errors": [f"{path.name}, лист «{sheet}»: не хватает колонок каталога: "
                           + "; ".join(f"«{m}»" for m in missing)]}
    idx = defaultdict(list)
    n = 0
    for _, r in df.iterrows():
        sup = pd.to_numeric(r[cm["supply"]], errors="coerce")
        price = pd.to_numeric(r[cm["price"]], errors="coerce")
        if pd.isna(sup) or pd.isna(price):
            continue
        key = r[cm["norm"]] if cm["norm"] and isinstance(r[cm["norm"]], str) else r[cm["name"]]
        key = norm(key)
        if not key:
            continue
        idx[key].append((int(sup), float(price)))
        n += 1
    for k in idx:
        idx[k].sort()
    return {"index": dict(idx), "rows": n, "errors": [], "sheet": sheet, "file": path.name}


def load_aliases(path: Path | None) -> dict:
    al = {}
    if path and path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        al = {norm(k): norm(v) for k, v in raw.items() if not str(k).startswith("_")}
    return al


def _resolve(article: str, catalog: dict, aliases: dict) -> tuple[str | None, bool]:
    n = norm(article)
    if n in aliases:
        return aliases[n], True
    return (n if n in catalog else None), False


def find_price(supply: int, article: str, catalog: dict, aliases: dict):
    """(цена, поставка_цены, статус)."""
    n, used_alias = _resolve(article, catalog, aliases)
    if n is None or n not in catalog:
        return None, None, "missing"
    pre = "alias_" if used_alias else ""
    cands = catalog[n]
    for s, p in cands:
        if s == supply:
            return p, s, pre + "exact"
    earlier = [(s, p) for s, p in cands if s <= supply]
    if earlier:
        s, p = max(earlier)
        return p, s, pre + "nearest_le"
    s, p = min(cands)
    return p, s, pre + "first"


def latest_price(article: str, catalog: dict, aliases: dict):
    """Цена последней (максимальной по номеру) поставки — для оценки остатков."""
    n, _ = _resolve(article, catalog, aliases)
    if n is None or n not in catalog:
        return None, None
    s, p = max(catalog[n])
    return p, s
