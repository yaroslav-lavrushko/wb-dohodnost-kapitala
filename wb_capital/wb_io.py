"""Чтение еженедельных детализаций WB: поиск файлов, склейка, проверка колонок.

Читает и колонки программы лояльности WB (компенсация скидки, стоимость участия, удержанные баллы) —
они нужны для P&L.

Сопоставление колонок — только по имени (NFC + нижний регистр + пробелы),
никогда по букве: WB регулярно вставляет новые колонки в середину.
"""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd

# канонический ключ -> имя колонки в новом формате WB (82 колонки)
COLS = {
    "doc": "Тип документа",
    "reason": "Обоснование для оплаты",
    "kind": "Виды логистики, штрафов и корректировок ВВ",
    "pay": "К перечислению Продавцу за реализованный Товар",
    "retail": "Цена розничная с учетом согласованной скидки",
    "realized": "Вайлдберриз реализовал Товар (Пр)",
    "logistics": "Услуги по доставке товара покупателю",
    "penalty": "Общая сумма штрафов",
    "vv_corr": "Корректировка Вознаграждения Вайлдберриз (ВВ)",
    "storage": "Хранение",
    "deduction": "Удержания",
    "acceptance": "Операции на приемке",
    "rebill": "Возмещение издержек по перевозке/по складским операциям с товаром",
    "supply": "Номер поставки",
    "srid": "Srid",
    "date": "Дата продажи",
    "article": "Артикул поставщика",
    "nm": "Код номенклатуры",
    "brand": "Бренд",
    "name": "Название",
    "barcode": "Баркод",
    "qty": "Кол-во",
    "warehouse": "Склад",
    "loyalty_comp": "Компенсация скидки по программе лояльности",
    "loyalty_cost": "Стоимость участия в программе лояльности",
    "loyalty_points": "Сумма баллов, удержанных по программе лояльности",
}

# старые названия тех же колонок (форматы WB 2024–2025)
ALIASES = {
    "acceptance": ["Платная приемка"],
    "kind": ["Виды логистики, штрафов и доплат", "Обоснование штрафов и доплат"],
    "retail": ["Цена розничная с учётом согласованной скидки"],
}

REQUIRED = ["doc", "reason", "pay", "logistics", "penalty", "storage", "deduction", "date", "srid"]
MONEY = ["pay", "retail", "realized", "logistics", "penalty", "vv_corr", "storage",
         "deduction", "acceptance", "rebill", "loyalty_comp", "loyalty_cost", "loyalty_points"]

SKIP_NAME = ("сверка", "себестоимост", "общее", "общий", "общая", "общие", "~$")


def nfc(s):
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", nfc(str(s))).strip().lower().replace("ё", "е")


def _report_no(name: str) -> str | None:
    m = re.search(r"№\s*(\d+)", nfc(name))
    return m.group(1) if m else None


def discover(paths: list[str]) -> tuple[list[Path], list[str]]:
    """Файлы детализаций из путей. Папка — только её верхний уровень.
    Явно указанный файл берётся всегда; в папке пропускаются склейки/сверки.
    Если есть и xlsx, и zip с тем же номером отчёта — берётся xlsx."""
    found: list[Path] = []
    notes: list[str] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_file():
            found.append(p)
        elif p.is_dir():
            for f in sorted(p.iterdir(), key=lambda x: nfc(x.name)):
                n = nfc(f.name).lower()
                if not f.is_file() or f.suffix.lower() not in (".xlsx", ".zip"):
                    continue
                if any(s in n for s in SKIP_NAME):
                    notes.append(f"пропущен (склейка/сверка/себестоимость): {f.name}")
                    continue
                found.append(f)
        else:
            notes.append(f"путь не найден: {raw}")
    xlsx_nos = {_report_no(f.name) for f in found if f.suffix.lower() == ".xlsx"} - {None}
    out = []
    for f in found:
        if f.suffix.lower() == ".zip" and _report_no(f.name) in xlsx_nos:
            notes.append(f"пропущен zip-дубль xlsx: {f.name}")
            continue
        out.append(f)
    return out, notes


def _frames_from(path: Path):
    """(имя_источника, DataFrame) для xlsx или каждого xlsx внутри zip."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                if member.lower().endswith(".xlsx") and not member.startswith("__MACOSX"):
                    data = z.read(member)
                    yield f"{path.name}/{member}", data, pd.ExcelFile(io.BytesIO(data))
    else:
        data = path.read_bytes()
        yield path.name, data, pd.ExcelFile(io.BytesIO(data))


def _map_columns(cols) -> dict:
    """канонический ключ -> фактическое имя колонки в файле."""
    by_key = {_key(c): c for c in cols}
    res = {}
    for k, name in COLS.items():
        for cand in [name] + ALIASES.get(k, []):
            if _key(cand) in by_key:
                res[k] = by_key[_key(cand)]
                break
    return res


def load(paths: list[str]) -> dict:
    """Читает и склеивает детализации. Ничего не роняет: проблемы — в errors/warnings.

    Возвращает dict: df (канонические колонки + служебные), files, errors, warnings, notes.
    """
    files, notes = discover(paths)
    errors, warnings, parts, meta = [], [], [], []
    seen_hash = {}
    for f in files:
        try:
            sources = list(_frames_from(f))
        except Exception as e:  # битый файл
            errors.append(f"{f.name}: не читается ({e.__class__.__name__}: {e})")
            continue
        for src, data, xl in sources:
            h = hashlib.md5(data).hexdigest()
            if h in seen_hash:
                notes.append(f"пропущен дубль по содержимому: {src} = {seen_hash[h]}")
                continue
            seen_hash[h] = src
            sheet, colmap, raw = None, None, None
            for sh in xl.sheet_names:
                head = xl.parse(sh, nrows=0)
                cm = _map_columns(head.columns)
                if "reason" in cm:
                    sheet, colmap = sh, cm
                    break
            if sheet is None:
                errors.append(f"{src}: не похоже на детализацию WB — нет колонки «{COLS['reason']}» ни на одном листе")
                continue
            missing = [COLS[k] for k in REQUIRED if k not in colmap]
            if missing:
                errors.append(f"{src}: не хватает обязательных колонок: " + "; ".join(f"«{m}»" for m in missing))
                continue
            raw = xl.parse(sheet)
            opt_missing = [COLS[k] for k in COLS if k not in colmap and k not in REQUIRED
                           and not k.startswith("loyalty")]  # в старых форматах их нет — это норма
            if opt_missing:
                warnings.append(f"{src}: нет колонок {', '.join('«'+m+'»' for m in opt_missing)} — считаю их нулём/пустыми")
            df = pd.DataFrame({k: raw[c] for k, c in colmap.items()})
            for k in COLS:
                if k not in df:
                    df[k] = 0.0 if k in MONEY else None
            for k in MONEY:
                df[k] = pd.to_numeric(df[k], errors="coerce").fillna(0.0)
            for k in ("reason", "kind", "doc", "article", "brand", "name", "warehouse", "srid"):
                df[k] = df[k].map(lambda v: nfc(str(v)).strip() if pd.notna(v) and str(v).strip() != "" else None)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["report"] = _report_no(src) or Path(src).stem
            df["source"] = src
            df["src_row"] = range(2, len(df) + 2)  # номер строки в Excel-файле WB
            parts.append(df)
            meta.append({"источник": src, "отчёт": df["report"].iat[0] if len(df) else "",
                         "строк": len(df), "колонок": raw.shape[1],
                         "с": df["date"].min(), "по": df["date"].max(),
                         "к_перечислению": float(df["pay"].sum())})
    if not parts:
        return {"df": None, "files": meta, "errors": errors or ["не найдено ни одной детализации WB"],
                "warnings": warnings, "notes": notes}
    df = pd.concat(parts, ignore_index=True)
    # контроль склейки
    if len(df) != sum(m["строк"] for m in meta):
        errors.append("склейка потеряла строки")
    if abs(df["pay"].sum() - sum(m["к_перечислению"] for m in meta)) > 0.01:
        errors.append("склейка: не сошлась сумма «К перечислению» по файлам")
    return {"df": df, "files": meta, "errors": errors, "warnings": warnings, "notes": notes}
