"""Выход: Excel (6 листов) и самодостаточный HTML с квадрантом «доходность × оборачиваемость»."""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import report_html


MONEY = ["Выручка", "К перечислению за товар", "Комиссия и эквайринг", "Логистика", "Штрафы", "Корректировка ВВ",
         "Хранение", "Платная приёмка", "Возмещение издержек", "Налог", "Расходы WB и маркетинг", "Себестоимость",
         "Прибыль", "Капитал в остатке", "Цена единицы остатка", "Доп. комиссия (сценарий)", "Прибыль (сценарий)",
         "Компенсация лояльности WB", "Лояльность WB (участие, баллы)", "Лишний запас, ₽"]
QTY = ["Продано, шт", "Возвратов, шт", "Остаток, шт", "В пути, шт"]
VERDICT_ORDER = {"развивать": 0, "сократить закупку": 0.5, "держать": 1, "выводить": 2, "нет продаж в периоде": 2.5, "мало остатка на дату снимка": 3, "нет данных об остатке": 4,
                 "нет себестоимости": 5}
FILL = {"развивать": "D9F2D9", "сократить закупку": "FCE8C8", "держать": "E3ECF9", "выводить": "F8D7D7"}


def _period(checks) -> str:
    d0, d1, days = checks["period"]
    return f"{d0:%d.%m.%Y} – {d1:%d.%m.%Y} ({days} дн.)"


def _sheet(ws, df: pd.DataFrame, money=(), pct=(), widths=None, verdict_col=None):
    ws.append(list(df.columns))
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", start_color="DDEBF7")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and pd.isna(v)) else v for v in row])
    cols = list(df.columns)
    for j, name in enumerate(cols, 1):
        L = get_column_letter(j)
        fmt = '#,##0;[Red]-#,##0' if name in money else ('0.0;[Red]-0.0' if name in pct else None)
        if fmt:
            for cell in ws[L][1:]:
                cell.number_format = fmt
        ws.column_dimensions[L].width = (widths or {}).get(name, 14 if name not in ("Артикул",) else 48)
    if verdict_col and verdict_col in cols:
        j = cols.index(verdict_col) + 1
        for r in range(2, ws.max_row + 1):
            v = ws.cell(r, j).value
            if v in FILL:
                ws.cell(r, j).fill = PatternFill("solid", start_color=FILL[v])
    ws.freeze_panes = "B2"


def _summary(t: pd.DataFrame, checks: dict, cfg: dict) -> dict:
    ok = t["Капитал в остатке"].fillna(0) >= cfg["thresholds"]["min_capital_rub"]
    days = checks["period"][2]
    prof = float(t["Прибыль"].sum(skipna=True))
    cap = float(t.loc[ok, "Капитал в остатке"].sum())
    prof_ok = float(t.loc[ok, "Прибыль"].sum(skipna=True))
    real_cap = float(t.loc[ok & (t["Остаток"] == "реальный"), "Капитал в остатке"].sum())
    rev = float(t["Выручка"].sum())
    return {
        "revenue": rev, "profit": prof, "capital": cap,
        "portfolio_return": (prof_ok * (365 if checks.get("basis", "year") == "year" else 365 / 12) / days / cap * 100) if cap else None,
        "real_capital_share": (real_cap / cap * 100) if cap else 0,
        "real_rows": int((t["Остаток"] == "реальный").sum()), "test_rows": int((t["Остаток"] == "ТЕСТ").sum()),
        "nodata_rows": int((t["Остаток"] == "нет данных").sum()),
        "verdicts": t["Вердикт"].value_counts().to_dict(),
        "verdicts_sc": t["Вердикт (сценарий)"].value_counts().to_dict(),
    }


def _rub(v) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _bl(checks) -> str:
    return "годовых" if checks.get("basis", "year") == "year" else "в месяц"


def conclusions(t: pd.DataFrame, s: dict, cfg: dict, checks: dict) -> list[str]:
    """Короткие выводы правилами (скилл Claude дописывает «что делать» поверх них)."""
    th, bl = cfg["thresholds"], _bl(checks)
    Y = "Доходность капитала, %"
    out = []
    w = t[t["Вердикт"] == "выводить"].sort_values("Капитал в остатке", ascending=False)
    if len(w):
        cap = w["Капитал в остатке"].sum()
        out.append(f"Выводить: {len(w)} арт., в них заморожено {_rub(cap)} ₽ ({cap / s['capital'] * 100:.0f}% капитала). "
                   f"Крупнейший — «{w.iloc[0]['Артикул']}»: {_rub(w.iloc[0]['Капитал в остатке'])} ₽ "
                   f"при доходности {w.iloc[0][Y]:.0f}% {bl}.")
    h = t[t["Вердикт"] == "держать"].sort_values("Капитал в остатке", ascending=False)
    if len(h):
        out.append(f"Держать: {len(h)} арт., {_rub(h['Капитал в остатке'].sum())} ₽ в остатке — доходность между "
                   f"{th['withdraw_below_pct']}% и {th['develop_above_pct']}% {bl}, кандидаты на пересмотр цены или запаса.")
    g = t[t["Вердикт"] == "развивать"].sort_values("Прибыль", ascending=False)
    if len(g):
        out.append(f"Развивать: {len(g)} арт. дают {g['Прибыль'].sum() / max(s['profit'], 1) * 100:.0f}% прибыли периода. "
                   f"Лидер по прибыли — «{g.iloc[0]['Артикул']}» ({g.iloc[0][Y]:.0f}% {bl}, "
                   f"{g.iloc[0]['Оборотов в год']:.1f} оборота в год).")
    red = t[t["Вердикт"] == "сократить закупку"].sort_values("Лишний запас, ₽", ascending=False)
    if len(red):
        out.append(f"Сократить закупку: {len(red)} арт. доходны, но запас больше {th['max_stock_days']} дней продаж; "
                   f"лишние деньги в запасе — {_rub(red['Лишний запас, ₽'].sum())} ₽. Больше всего: "
                   + "; ".join(f"«{r['Артикул']}» — {_rub(r['Лишний запас, ₽'])} ₽, запас {r['Запас, дней']:.0f} дн."
                               for _, r in red.head(3).iterrows()).rstrip(".") + ".")
    ch = t[t["Вердикт"] != t["Вердикт (сценарий)"]]
    msg = (f"Комиссия +{checks['commission_pp']:g} п.п.: прибыль периода −{_rub(t['Доп. комиссия (сценарий)'].sum())} ₽ "
           f"({t['Доп. комиссия (сценарий)'].sum() / max(s['profit'], 1) * 100:.0f}% прибыли), вердикт меняют {len(ch)} арт.")
    if len(ch):
        msg += ": " + "; ".join(f"«{r['Артикул']}» {r['Вердикт']} → {r['Вердикт (сценарий)']}" for _, r in ch.head(4).iterrows())
    out.append(msg + ("" if msg.endswith(".") else "."))
    ns = t[t["Вердикт"] == "нет продаж в периоде"].sort_values("Капитал в остатке", ascending=False)
    ns = ns[ns["Капитал в остатке"].fillna(0) > 0]
    if len(ns):
        out.append(f"Нет продаж в периоде при остатке: {len(ns)} арт., {_rub(ns['Капитал в остатке'].sum())} ₽ — "
                   + "; ".join(f"«{r['Артикул']}» {_rub(r['Капитал в остатке'])} ₽" for _, r in ns.head(3).iterrows())
                   + ". Новая поставка или неликвид — проверить дату прихода.")
    snap = t[(t["Вердикт"] == "мало остатка на дату снимка") & (t["Продано, шт"] > 0)].sort_values("Прибыль", ascending=False)
    if len(snap):
        out.append(f"Без оценки доходности: {len(snap)} арт. продавались, но на дату снимка остатка почти не было "
                   f"(прибыль {_rub(snap['Прибыль'].sum())} ₽) — нужен второй снимок остатков.")
    nd = t[t["Вердикт"].isin(["нет данных об остатке", "нет себестоимости"]) & (t["Продано, шт"] > 0)]
    if len(nd):
        out.append(f"Нет данных: {len(nd)} арт. (" + ", ".join(sorted(set(nd["Вердикт"]))) + ") — дать данные, иначе решение вслепую.")
    return out


def write(out: Path, res: dict, meta: dict, cfg: dict) -> list[Path]:
    t = res["table"].copy()
    checks = res["checks"]
    pairs = res["pairs"]
    locs = res.get("locations")
    if locs is not None:
        locs = locs.copy()
    t["_o"] = t["Вердикт"].map(VERDICT_ORDER).fillna(9)
    t = t.sort_values(["_o", "Доходность капитала, %"], ascending=[True, False]).drop(columns="_o")
    s = _summary(t, checks, cfg)
    s["locations"] = locs if locs is not None else pd.DataFrame()
    concl = conclusions(t, s, cfg, checks)
    stem = "доходность-капитала"
    xlsx, htm = out / f"{stem}.xlsx", out / f"{stem}.html"
    _excel(xlsx, t.rename(columns=lambda c: c.replace("Доходность капитала, %", f"Доходность капитала, % {_bl(checks)}")),
           pairs, s, checks, meta, cfg, concl)
    report_html.write_html(htm, t, s, checks, meta, cfg, concl, res)
    return [xlsx, htm]


def _provenance(s, meta, checks) -> list[str]:
    lines = ["Продажи, выручка, расходы WB — из еженедельных детализаций WB (как есть, без правок).",
             "Себестоимость — из каталога цен по поставкам, сопоставление «поставка × артикул»."]
    nloc = len(s.get("locations", [])) if s.get("locations") is not None else 0
    st = f"Остатки — из файлов у {s['real_rows']} арт. ({s['real_capital_share']:.0f}% капитала)"
    if nloc:
        st += f", мест хранения: {nloc}"
    if meta.get("stock_date"):
        st += f", снимок: {meta['stock_date']}"
    if s["test_rows"]:
        st += (f"; ТЕСТОВЫЕ (придуманы программой по ключу --test-stock-days) у {s['test_rows']} арт.: "
               f"запас = {checks['test_stock_days']:g} дн. продаж, в таблице помечены «ТЕСТ»")
    if s["nodata_rows"]:
        st += f"; нет данных у {s['nodata_rows']} арт."
    lines.append(st if st.endswith(".") else st + ".")
    for w in checks.get("stock_warnings", []):
        lines.append("Внимание: " + w + ".")
    return lines


def _excel(path, t, pairs, s, checks, meta, cfg, concl):
    wb = Workbook()
    ws = wb.active
    ws.title = "Итог"
    b = Font(bold=True)
    ws.append(["Доходность вложенного капитала по товарам"])
    ws["A1"].font = Font(bold=True, size=14)
    rows = [("Прогон", meta.get("label") or ""), ("Дата прогона", meta["run_date"]), ("Период продаж", _period(checks)),
            ("Выручка до комиссии, ₽", round(s["revenue"])), ("Прибыль за период, ₽", round(s["profit"])),
            (f"Деньги в остатках по себестоимости, ₽ (артикулы с остатком от {cfg['thresholds']['min_capital_rub']} ₽)", round(s["capital"])),
            (f"Доходность капитала, % {_bl(checks)} (портфель)", round(s["portfolio_return"], 1) if s["portfolio_return"] is not None else "—"),
            ("Налог", f"{checks['tax_pct']:g}% от выручки" if checks["tax_pct"] else "не вычтен — прибыль до налога"),
            ("Пороги", f"развивать > {cfg['thresholds']['develop_above_pct']}%, выводить < {cfg['thresholds']['withdraw_below_pct']}% {_bl(checks)}")]
    ws.append([])
    for k, v in rows:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = b
    ws.append([])
    ws.append(["Вердикт", "сейчас", f"комиссия +{checks['commission_pp']:g} п.п."])
    for c in ws[ws.max_row]:
        c.font = b
    for v in ["развивать", "сократить закупку", "держать", "выводить", "нет продаж в периоде", "мало остатка на дату снимка", "нет данных об остатке", "нет себестоимости"]:
        if s["verdicts"].get(v) or s["verdicts_sc"].get(v):
            ws.append([v, s["verdicts"].get(v, 0), s["verdicts_sc"].get(v, 0)])
    ws.append([])
    ws.append(["Что реальное, что тестовое"])
    ws.cell(ws.max_row, 1).font = b
    for line in _provenance(s, meta, checks):
        ws.append([line])
    ws.append([])
    ws.append(["Выводы"])
    ws.cell(ws.max_row, 1).font = b
    for line in concl:
        ws.append([line])
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 22

    Y = f"Доходность капитала, % {_bl(checks)}"
    pct = [Y, Y + " (сценарий)", "Маржа, %", "Оборотов в год", "Запас, дней"]
    m = t[["Артикул", "Вердикт", Y, "Оборотов в год", "Запас, дней", "Капитал в остатке", "Лишний запас, ₽",
           "Остаток", "Прибыль", "Маржа, %", "Выручка", "Продано, шт", "Вердикт (сценарий)",
           Y + " (сценарий)"]]
    _sheet(wb.create_sheet("Матрица"), m, money=MONEY, pct=pct, verdict_col="Вердикт")

    lc = s.get("locations")
    if lc is not None and len(lc):
        tot = {"Место хранения": "ИТОГО", "Штук": lc["Штук"].sum(), "в т.ч. в пути": lc["в т.ч. в пути"].sum(),
               "Деньги по себестоимости": lc["Деньги по себестоимости"].sum(), "Доля, %": 100.0}
        _sheet(wb.create_sheet("Где лежат деньги"), pd.concat([lc, pd.DataFrame([tot])], ignore_index=True),
               money=["Деньги по себестоимости", "Штук", "в т.ч. в пути"], pct=["Доля, %"],
               widths={"Место хранения": 34, "Даты снимков": 26, "Источник": 70, "Деньги по себестоимости": 20})

    groups = [g["label"] for g in cfg["deduction_groups"]]
    pl_cols = ["Артикул", "Продано, шт", "Возвратов, шт", "Выручка", "Комиссия и эквайринг", "К перечислению за товар",
               "Компенсация лояльности WB", "Логистика", "Хранение", "Штрафы", "Корректировка ВВ", "Платная приёмка",
               "Возмещение издержек", "Лояльность WB (участие, баллы)",
               *groups, "Налог", "Расходы WB и маркетинг", "Себестоимость", "Прибыль", "Маржа, %",
               "Остаток, шт", "В пути, шт", "Цена единицы остатка", "Откуда цена остатка", "Остаток", "Капитал в остатке"]
    pl = t[[c for c in pl_cols if c in t]].copy()
    tot = {c: pl[c].sum() for c in pl.columns if c in MONEY + QTY + groups and c != "Цена единицы остатка"}
    tot["Артикул"] = "ИТОГО"
    pl = pd.concat([pl, pd.DataFrame([tot])], ignore_index=True)
    _sheet(wb.create_sheet("P&L по артикулам"), pl, money=MONEY + groups, pct=pct)

    sc = t[["Артикул", "Выручка", "Прибыль", "Доп. комиссия (сценарий)", "Прибыль (сценарий)",
            Y, Y + " (сценарий)", "Вердикт", "Вердикт (сценарий)"]]
    ws_sc = wb.create_sheet(f"Комиссия +{checks['commission_pp']:g} пп")
    _sheet(ws_sc, sc, money=MONEY, pct=pct, verdict_col="Вердикт (сценарий)")

    if pairs is not None and len(pairs):
        p = pairs.drop(columns=["key", "status"])
        _sheet(wb.create_sheet("Себестоимость"), p, money=["Цена за шт", "Себестоимость"],
               widths={"Артикул поставщика": 48, "Как найдена цена": 36})

    ws = wb.create_sheet("Проверки")
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 40
    chk = [("Сумма по артикулам (до себестоимости) = итог кабинета", "да" if checks["conserved"] else "НЕТ — разобрать"),
           ("Итог кабинета до себестоимости, ₽", checks["cabinet_net_before_cogs"]),
           ("Сумма по артикулам до себестоимости, ₽", checks["articles_net_before_cogs"])]
    if True:
        chk += [("Продаж (Тип документа = Продажа, Кол-во > 0), шт", checks["opiu_sales_qty"]),
                ("Пар «поставка × артикул»", checks["opiu_pairs"]),
                ("Как найдены цены", ", ".join(f"{k}: {v}" for k, v in checks["opiu_status"].items())),
                ("Себестоимость продаж (пары «поставка × артикул»), ₽", checks["opiu_cogs"]),
                ("Строк без артикула, привязанных по коду номенклатуры", checks["filled_by_nm"])]
    for k, v in checks["excluded"].items():
        chk.append((f"Исключено из P&L: {k}, ₽", v))
    ws.append(["Проверка", "Результат"])
    for c in ws[1]:
        c.font = b
    for k, v in chk:
        ws.append([k, v])
    ws.append([])
    ws.append(["Расходы без артикула — как разнесены", ""])
    ws.cell(ws.max_row, 1).font = b
    for a in checks["allocation"]:
        ws.append([f"{a['Статья']}: {a['Сумма без артикула']:,.0f} ₽".replace(",", " "), a["Разнесено"]])
    ws.append([])
    ws.append(["Источники", ""])
    ws.cell(ws.max_row, 1).font = b
    for f in meta["details"]:
        ws.append([str(f.get("источник")), f"строк: {f.get('строк')}"])
    for c in meta["catalog"]:
        ws.append([c, "каталог себестоимости"])
    for c in meta["stock"]:
        ws.append([c, "остатки"])
    for n in meta["notes"] + meta["warnings"]:
        ws.append([n, ""])
    wb.save(path)


def write_errors(out: Path, meta: dict):
    lines = ["Отчёт не собран: входные данные не подходят.", ""]
    lines += [f"– {e}" for e in meta["errors"]]
    if meta["warnings"]:
        lines += ["", "Предупреждения:"] + [f"– {w}" for w in meta["warnings"]]
    if meta["notes"]:
        lines += ["", "Заметки:"] + [f"– {n}" for n in meta["notes"]]
    (out / "ОШИБКИ-входных-данных.txt").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- HTML
def _num(v, d=0):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return round(float(v), d)


