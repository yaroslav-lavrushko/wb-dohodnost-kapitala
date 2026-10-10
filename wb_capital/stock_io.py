"""Остатки: любые места хранения, любые файлы, любое число таблиц на листе, снимки по датам.

Принцип учёта: капитал — весь свой товар, где бы он ни лежал
(склады маркетплейсов, свои склады, фулфилмент, товар в пути). Каждая найденная таблица —
одно или несколько мест хранения; у каждой — дата снимка. Остатки на одну дату по разным
местам складываются, снимки одного места на разные даты — усредняются (см. capital.py).

Что понимает (по именам колонок, не по буквам):
  • WB «Остатки по складам»: Артикул продавца · Всего находится на складах · В пути …
  • выгрузки сервисов аналитики: Артикул · Артикул маркетплейса · Остатки на складах МП / на моих складах
  • любой учёт склада (1С, МойСклад, ФФ): Артикул/Наименование/Код WB · Остаток (· Склад · Дата)
Место хранения: колонка «Склад» (строка = артикул × склад) → заголовок вида «Склад Подольск»
→ тип выгрузки (склады маркетплейса) → имя листа или файла.
Дата снимка: ключ «файл@ГГГГ-ММ-ДД» → колонка «Дата» → дата в имени файла → --stock-date → «без даты».
Таблица кончается на первой пустой строке. Строки без своего заголовка не угадываются — в предупреждения.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from .cogs import norm


def _k(s) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s))).strip().lower().replace("ё", "е")


ARTICLE = ["артикул продавца", "артикул поставщика", "наименование", "название товара", "товар", "артикул"]
NM = ["артикул маркетплейса", "артикул wb", "артикул вб", "код номенклатуры", "nmid", "nm id", "код wb"]
QTY_TOTAL = ["всего находится на складах", "остатки всего, шт", "остатки, шт", "остаток, шт", "остаток", "остатки",
             "количество, шт", "количество", "кол-во"]
# колонки-места внутри одной таблицы (сервисы аналитики): каждая — своё место хранения
QTY_PARTS = {"остатки на складах мп, шт": "Склады маркетплейса", "остатки на моих складах, шт": "Свои склады"}
TRANSIT = ["в пути до получателей", "в пути возвраты на склад wb", "в пути к клиентам, шт", "в пути от клиентов, шт"]
VALUE = ["капитализация по себестоимости", "остаток по себестоимости, ₽", "остаток по себестоимости",
         "сумма по себестоимости", "стоимость остатка по себестоимости"]
LOCATION_COL = ["склад", "место хранения", "склад хранения", "warehouse"]
DATE_COL = ["дата", "дата снимка", "на дату", "дата остатка"]
MP_SIGNS = ["всего находится на складах", "в пути до получателей"]
GENERIC_SHEETS = {"sheet1", "worksheet", "лист1", "sheet", "лист", "data", "export"}
BAD_ART = {"-", "—", "nan", "итого", "всего", "итог"}


def _find(ck: dict, names):
    for n in names:
        if n in ck:
            return ck[n]
    return None


def detect(labels: dict) -> dict | None:
    """labels: {индекс_колонки: заголовок}. Карта колонок таблицы остатков или None."""
    ck = {}
    for i, v in labels.items():
        ck.setdefault(_k(v), i)
    art, nm = _find(ck, ARTICLE), _find(ck, NM)
    parts = {ck[n]: loc for n, loc in QTY_PARTS.items() if n in ck}
    qty = None if parts else _find(ck, QTY_TOTAL)
    if not (art is not None or nm is not None) or not (qty is not None or parts):
        return None
    if nm is None and art is not None and "артикул" in ck and ck["артикул"] != art:
        nm = ck["артикул"]   # «Артикул» рядом с «Наименованием» в учётных выгрузках — обычно код маркетплейса;
        #                      если там не числа, код просто не распознается и сопоставление пойдёт по названию
    named = [i for k, i in ck.items() if k.startswith("склад ") and i not in (art, nm, qty)]
    return {"article": art, "nm": nm, "qty": qty, "parts": parts,
            "transit": [ck[n] for n in TRANSIT if n in ck], "value": _find(ck, VALUE),
            "loc_col": _find(ck, LOCATION_COL), "date_col": _find(ck, DATE_COL),
            "named_loc": labels[named[0]].strip() if named else None,
            "mp": any(s in ck for s in MP_SIGNS)}


def missing_report(columns) -> str:
    ck = {_k(c): c for c in columns}
    need = []
    if not (_find(ck, ARTICLE) or _find(ck, NM)):
        need.append("артикул («Артикул продавца» / «Артикул поставщика» / «Артикул маркетплейса»)")
    if not (_find(ck, QTY_TOTAL) or any(n in ck for n in QTY_PARTS)):
        need.append("количество («Всего находится на складах» / «Остаток, шт» / «Остатки всего, шт»)")
    return "; ".join(need)


def _segments(row: list) -> list[tuple[int, int]]:
    """Непрерывные куски заголовка; разделитель — 2+ пустые колонки подряд."""
    segs, start, gap = [], None, 0
    for j, v in enumerate(row + [None, None]):
        empty = v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""
        if not empty:
            if start is None:
                start = j
            gap, last = 0, j
        elif start is not None:
            gap += 1
            if gap >= 2:
                segs.append((start, last))
                start, gap = None, 0
    return segs


def find_tables(raw: pd.DataFrame) -> list[dict]:
    """Все таблицы остатков на листе: [{hdr, c0, c1, cm, end, orphan}]."""
    tables = []
    covered = []  # (r0, r1, c0, c1)
    for r in range(len(raw)):
        row = raw.iloc[r].tolist()
        for c0, c1 in _segments(row):
            if any(r0 <= r <= r1 and not (c1 < a or c0 > b) for r0, r1, a, b in covered):
                continue
            labels = {j: str(row[j]) for j in range(c0, c1 + 1) if pd.notna(row[j]) and str(row[j]).strip()}
            cm = detect(labels)
            if not cm:
                continue
            ids = [c for c in (cm["article"], cm["nm"]) if c is not None]
            body = raw.iloc[r + 1:, ids]
            blank = body.isna().all(axis=1).to_numpy() | body.apply(
                lambda s: s.astype(str).str.strip().eq(""), axis=0).all(axis=1).to_numpy()
            started = False
            end = len(raw) - 1
            for i, b in enumerate(blank):
                if not b:
                    started = True
                elif started:
                    end = r + i  # последняя строка данных
                    break
            # строки ниже пустой строки в тех же колонках, у которых нет своего заголовка
            below = raw.iloc[end + 1:, ids]
            orphan = int((~below.isna().all(axis=1)).sum()) if len(below) else 0
            tables.append({"hdr": r, "c0": c0, "c1": c1, "cm": cm, "end": end, "orphan": orphan})
            covered.append((r, end, c0, c1))
    # сироты, у которых ниже нашлась своя таблица, — не сироты
    for t in tables:
        later = [u for u in tables if u["hdr"] > t["end"] and not (u["c1"] < t["c0"] or u["c0"] > t["c1"])]
        if later:
            t["orphan"] = 0
    return tables


DATE_RX = [(re.compile(r"(20\d\d)-(\d\d)-(\d\d)"), lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
           (re.compile(r"(\d\d)\.(\d\d)\.(20\d\d)"), lambda m: f"{m[3]}-{m[2]}-{m[1]}")]


def parse_date(text: str | None):
    """Последняя дата в строке (для «с…по…» — дата «по»)."""
    if not text:
        return None
    found = []
    for rx, fmt in DATE_RX:
        for m in rx.finditer(text):
            found.append((m.start(), fmt(m)))
    if not found:
        return None
    d = pd.to_datetime(sorted(found)[-1][1], errors="coerce")
    return None if pd.isna(d) else d.normalize()


def split_spec(spec: str) -> tuple[Path, object]:
    """«путь@дата» → (путь, дата|None)."""
    if "@" in spec:
        p, d = spec.rsplit("@", 1)
        dd = parse_date(d)
        if dd is not None:
            return Path(p).expanduser(), dd
    return Path(spec).expanduser(), None


def _clean_art(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = unicodedata.normalize("NFC", str(v)).strip()
    return None if s.lower() in BAD_ART or not s else s


def load(path: Path, date_hint=None, default_date=None, include_transit: bool = True) -> dict:
    """{'records': DataFrame[location, date, article, nm, key, units, transit, value_file, source],
        'errors', 'warnings', 'notes'}"""
    out = {"records": None, "errors": [], "warnings": [], "notes": []}
    try:
        xl = pd.ExcelFile(path)
    except Exception as e:
        out["errors"].append(f"{path.name}: не читается ({e.__class__.__name__})")
        return out
    file_date = date_hint if date_hint is not None else parse_date(path.stem)
    recs = []
    for sh in xl.sheet_names:
        raw = xl.parse(sh, header=None, dtype=object)
        if raw.empty:
            continue
        for t in find_tables(raw):
            cm, r, end = t["cm"], t["hdr"], t["end"]
            body = raw.iloc[r + 1:end + 1]
            num = lambda j: pd.to_numeric(body.iloc[:, j], errors="coerce").fillna(0.0).to_numpy() if j is not None else 0.0
            art = body.iloc[:, cm["article"]].map(_clean_art).to_numpy() if cm["article"] is not None else [None] * len(body)
            nmv = pd.to_numeric(body.iloc[:, cm["nm"]], errors="coerce").to_numpy() if cm["nm"] is not None else [float("nan")] * len(body)
            transit = sum(num(j) for j in cm["transit"]) if (include_transit and cm["transit"]) else 0.0
            value = num(cm["value"]) if cm["value"] is not None else None
            # дата
            if cm["date_col"] is not None:
                dates = pd.to_datetime(body.iloc[:, cm["date_col"]], errors="coerce", dayfirst=True).dt.normalize()
                fill = file_date if file_date is not None else default_date
                if fill is not None:
                    dates = dates.fillna(fill)
            else:
                d = file_date if file_date is not None else default_date
                dates = pd.Series([d] * len(body), index=body.index)
            # место(а)
            sheet_name = None if sh.strip().lower() in GENERIC_SHEETS else sh.strip()
            base_loc = ("Склады маркетплейса" if cm["mp"] else cm["named_loc"] or sheet_name or path.stem)
            columns = list(cm["parts"].items()) if cm["parts"] else [(cm["qty"], None)]
            for k, (qcol, part_loc) in enumerate(columns):
                if cm["loc_col"] is not None:
                    locs = body.iloc[:, cm["loc_col"]].map(lambda v: str(v).strip() if pd.notna(v) and str(v).strip() else base_loc)
                else:
                    locs = pd.Series([part_loc or base_loc] * len(body), index=body.index)
                first = k == 0
                recs.append(pd.DataFrame({
                    "location": locs.to_numpy(), "date": dates.to_numpy(), "article": art, "nm": nmv,
                    "units": num(qcol),
                    "transit": transit if (first and (cm["mp"] or cm["parts"])) else 0.0,
                    "value_file": value if (first and value is not None) else float("nan"),
                    "source": f"{path.name} / {sh} / строка {r + 1}"}))
            used = [raw.iat[r, j] for j in [cm["article"], cm["nm"], cm["qty"], *cm["parts"], *cm["transit"],
                                            cm["value"], cm["loc_col"], cm["date_col"]] if j is not None]
            dtxt = "по колонке дат" if cm["date_col"] is not None else (
                f"{(file_date or default_date):%d.%m.%Y}" if (file_date or default_date) is not None else "без даты")
            out["notes"].append(f"{path.name}, лист «{sh}», таблица со строки {r + 1}: место «"
                                + ("по колонке «Склад»" if cm["loc_col"] is not None else
                                   ", ".join(sorted({p or base_loc for _, p in columns}))) + f"», дата {dtxt}; колонки "
                                + ", ".join(f"«{c}»" for c in used))
            if t["orphan"]:
                out["warnings"].append(f"{path.name}, лист «{sh}»: под таблицей со строки {r + 1} после пустой строки "
                                       f"ещё {t['orphan']} строк без своего заголовка — не учтены (дайте им заголовок, "
                                       f"если это остатки)")
    if not recs:
        first = xl.parse(xl.sheet_names[0], nrows=0).columns
        out["errors"].append(f"{path.name}: не похоже на остатки — не хватает колонок: {missing_report(first) or 'артикул и количество'}")
        return out
    df = pd.concat(recs, ignore_index=True)
    df = df[df["article"].notna() | pd.notna(df["nm"])].copy()
    df["key"] = df["article"].map(lambda a: norm(a) or None if a else None)
    if (df["date"].isna()).any():
        out["warnings"].append(f"{path.name}: у снимка нет даты — считаю одним снимком «без даты» "
                               f"(дату можно задать: --stock \"{path.name}@ГГГГ-ММ-ДД\")")
    out["records"] = df
    return out


def sniff(xl: pd.ExcelFile) -> bool:
    """Есть ли в файле хоть одна таблица остатков (для раскладки файлов по ролям)."""
    for sh in xl.sheet_names:
        head = xl.parse(sh, header=None, nrows=60, dtype=object)
        if find_tables(head):
            return True
    return False


def combine(rec: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """rec с колонкой key (уже приведённой к артикулу детализаций).
    Возвращает: по артикулу [key, article, nm, qty_stock, qty_transit, value_file];
                по месту×артикулу [location, key, units, transit];
                снимки [location, dates, n_dates, sources].
    Правило: одна дата — места складываются; одно место на разные даты — среднее по его датам."""
    rec = rec.copy()
    rec["date_k"] = rec["date"].map(lambda d: "без даты" if pd.isna(d) else pd.Timestamp(d).strftime("%Y-%m-%d"))
    per = rec.groupby(["location", "date_k", "key"], as_index=False).agg(
        units=("units", "sum"), transit=("transit", "sum"),
        value_file=("value_file", lambda s: s.sum(min_count=1)))
    ndates = rec.groupby("location")["date_k"].nunique()
    loc_key = per.groupby(["location", "key"], as_index=False).agg(
        units=("units", "sum"), transit=("transit", "sum"), value_file=("value_file", lambda s: s.sum(min_count=1)))
    loc_key["n"] = loc_key["location"].map(ndates)
    for c in ("units", "transit", "value_file"):
        loc_key[c] = loc_key[c] / loc_key["n"]
    names = rec.groupby("key").agg(article=("article", lambda s: next((v for v in s if isinstance(v, str)), None)),
                                   nm=("nm", "first"))
    by_key = loc_key.groupby("key").agg(qty_stock=("units", "sum"), qty_transit=("transit", "sum"),
                                        value_file=("value_file", lambda s: s.sum(min_count=1))).join(names).reset_index()
    snaps = rec.groupby("location").agg(dates=("date_k", lambda s: ", ".join(sorted(set(s)))),
                                        n_dates=("date_k", "nunique"),
                                        sources=("source", lambda s: "; ".join(sorted(set(s))))).reset_index()
    return by_key, loc_key[["location", "key", "units", "transit"]], snaps


def dedupe(rec: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Одно место на одну дату из разных таблиц: точная копия — берётся один раз; разные данные — складываются
    (выгрузка могла быть разбита на части), но с предупреждением."""
    warns = []
    rec = rec.copy()
    rec["_d"] = rec["date"].map(lambda d: "без даты" if pd.isna(d) else pd.Timestamp(d).strftime("%d.%m.%Y"))
    keep = []
    for (loc, d), g in rec.groupby(["location", "_d"], sort=False):
        srcs = list(dict.fromkeys(g["source"]))
        if len(srcs) == 1:
            keep.append(g)
            continue
        sig = {}
        for src in srcs:
            part = g[g["source"] == src]
            key = tuple(sorted(part.groupby("key")["units"].sum().round(3).items()))
            if key in sig:
                warns.append(f"«{loc}» на {d}: таблица «{src}» — точная копия «{sig[key]}», учтена один раз")
                continue
            sig[key] = src
            keep.append(part)
        if len(sig) > 1:
            warns.append(f"«{loc}» на {d}: {len(sig)} разные таблицы — сложены (если это одна выгрузка дважды "
                         f"в разном виде — уберите лишнюю)")
    out = pd.concat(keep, ignore_index=True).drop(columns="_d") if keep else rec.drop(columns="_d")
    return out, warns
