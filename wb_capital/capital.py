"""Расчёт: P&L по артикулу → деньги в остатках → годовая доходность капитала → вердикт → сценарий комиссии."""
from __future__ import annotations

import math
import re

import pandas as pd

from . import stock_io
from .cogs import STATUS_RU, find_price, latest_price, norm

MONEY_COST = ["logistics", "penalty", "vv_corr", "storage", "acceptance", "rebill", "loyalty_cost", "loyalty_points"]


def _eq(s: pd.Series, text: str) -> pd.Series:
    return s.fillna("").astype(str).str.strip().str.lower() == text.lower()


def _group_of(kind: str, groups: list[dict]) -> str:
    k = (kind or "").lower()
    for g in groups:
        if not g["kind"] or re.search(g["kind"], k, re.I):
            return g["id"]
    return groups[-1]["id"]


def attach_keys(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Ключ артикула на каждую строку; строки без артикула, но с кодом номенклатуры — по коду."""
    df = df.copy()
    df["key"] = df["article"].map(lambda a: (norm(a) or None) if isinstance(a, str) else None)
    nmv = pd.to_numeric(df["nm"], errors="coerce")
    pairs = df.loc[df["key"].notna() & nmv.notna() & (nmv != 0)].assign(nmv=nmv)
    # товар = код WB: если под одним кодом в детализациях несколько названий артикула — это один товар.
    # Склеиваем такие названия (объединение по общим кодам), ключ — самое частое название.
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for _, g in pairs.groupby("nmv")["key"]:
        ks = list(dict.fromkeys(g))
        for k in ks[1:]:
            parent[find(k)] = find(ks[0])
    freq = df["key"].value_counts()
    groups_ = {}
    for k in list(parent):
        groups_.setdefault(find(k), []).append(k)
    canon = {}
    merged = []
    for members in groups_.values():
        best = max(members, key=lambda k: (freq.get(k, 0), k))
        for k in members:
            canon[k] = best
        if len(members) > 1:
            merged.append(members)
    df["key"] = df["key"].map(lambda k: canon.get(k, k) if k else k)
    pairs = df.loc[df["key"].notna() & nmv.notna() & (nmv != 0)].assign(nmv=nmv)
    nm2key = pairs.groupby("nmv")["key"].agg(lambda s: s.mode().iat[0]).to_dict()
    fill = df["key"].isna() & nmv.isin(list(nm2key))
    df.loc[fill, "key"] = nmv[fill].map(nm2key)
    names = (df.loc[df["key"].notna()].groupby("key")["article"]
             .agg(lambda s: s.dropna().iat[0] if s.notna().any() else None).to_dict())
    return df, {"nm2key": nm2key, "names": names, "filled_by_nm": int(fill.sum()), "canon": canon,
                "merged": [sorted(m) for m in merged]}


def cogs_pairs(df: pd.DataFrame, catalog: dict, aliases: dict, canon: dict | None = None) -> pd.DataFrame:
    """Пары (поставка, артикул) с ценой — «Тип документа = Продажа», Кол-во > 0.
    Возвраты («Тип документа = Возврат») идут отдельными парами со знаком минус."""
    qty = pd.to_numeric(df["qty"], errors="coerce").fillna(0)
    rows = []
    for sign, mask in ((1, _eq(df["doc"], "Продажа")), (-1, _eq(df["doc"], "Возврат"))):
        sub = df[mask & (qty > 0) & df["article"].notna()].assign(q=qty)
        sub = sub.assign(sup=pd.to_numeric(sub["supply"], errors="coerce").fillna(0).astype(int))
        for (sup, art), g in sub.groupby(["sup", "article"]):
            price, used, st = find_price(int(sup), art, catalog, aliases)
            q = float(g["q"].sum())
            rows.append({"Знак": "продажа" if sign > 0 else "возврат", "Номер поставки": int(sup),
                         "Артикул поставщика": art, "key": (canon or {}).get(norm(art), norm(art)), "Кол-во": sign * q,
                         "Цена за шт": price, "Цена взята из поставки": used, "status": st,
                         "Как найдена цена": STATUS_RU[st],
                         "Себестоимость": (sign * q * price) if price is not None else None})
    return pd.DataFrame(rows)


def compute(df: pd.DataFrame, catalog: dict, aliases: dict, stock: pd.DataFrame | None,
            cfg: dict, test_stock_days: float | None = None, commission_pp: float | None = None,
            stock_label: str = "") -> dict:
    """stock — записи остатков из stock_io.load (место × дата × артикул) или None."""
    th, alloc = cfg["thresholds"], cfg["allocation"]
    groups = cfg["deduction_groups"]
    excluded_groups = {g["id"] for g in groups if g.get("exclude")}
    comm_pp = cfg["scenario"]["commission_pp"] if commission_pp is None else commission_pp
    tax = float(cfg.get("tax_pct_of_revenue", 0)) / 100

    df, km = attach_keys(df)
    sale, ret = _eq(df["doc"], "Продажа"), _eq(df["doc"], "Возврат")
    qty = pd.to_numeric(df["qty"], errors="coerce").fillna(0)
    df["_rev"] = df["retail"].where(sale, 0) - df["retail"].where(ret, 0)
    df["_pay"] = df["pay"].where(sale, 0) - df["pay"].where(ret, 0)
    df["_qty_sold"] = qty.where(sale & _eq(df["reason"], "Продажа"), 0)
    df["_qty_ret"] = qty.where(ret, 0)
    storno = df["reason"].fillna("").str.contains("сторно", case=False)
    df["logistics"] = df["logistics"].where(~storno, -df["logistics"])
    df["_dgroup"] = [(_group_of(k, groups) if d else None) for k, d in zip(df["kind"], df["deduction"] != 0)]
    for g in groups:
        df["ded_" + g["id"]] = df["deduction"].where(df["_dgroup"] == g["id"], 0.0)

    # --- период
    sd = df.loc[sale, "date"].dropna()
    d0, d1 = (sd.min(), sd.max()) if len(sd) else (df["date"].min(), df["date"].max())
    days = max(1, int((d1 - d0).days) + 1) if pd.notna(d0) and pd.notna(d1) else 30
    basis = cfg.get("return_basis", "year")
    ann = (365.0 if basis == "year" else 365.0 / 12) / days   # к году или к месяцу
    turn_ann = 365.0 / days                                   # оборачиваемость — всегда в год

    # --- суммы по артикулу (прямые) и без артикула (общие)
    val_cols = ["_rev", "_pay", "_qty_sold", "_qty_ret", "loyalty_comp"] + MONEY_COST + ["ded_" + g["id"] for g in groups]
    has = df["key"].notna()
    direct = df[has].groupby("key")[val_cols].sum()
    common = df.loc[~has, val_cols].sum()

    # --- себестоимость
    pairs = cogs_pairs(df, catalog, aliases, km["canon"])
    if len(pairs):
        cg = pairs.groupby("key").agg(cogs=("Себестоимость", lambda s: s.sum(min_count=1)),
                                      cogs_missing=("status", lambda s: int((s == "missing").sum())),
                                      cogs_fallback=("status", lambda s: int((~s.isin(["exact", "alias_exact", "missing"])).sum())))
    else:
        cg = pd.DataFrame(columns=["cogs", "cogs_missing", "cogs_fallback"])

    # --- остатки
    keys = set(direct.index)
    def keyed(x: pd.DataFrame) -> pd.DataFrame:
        x = x.copy()
        # код WB надёжнее названия: если он есть и встречался в детализациях — ключ по нему
        by_nm = pd.to_numeric(x["nm"], errors="coerce").map(km["nm2key"]) if "nm" in x else None
        if by_nm is not None:
            x["key"] = by_nm.where(by_nm.notna(), x["key"])
        return x[x["key"].notna()]

    st = pd.DataFrame(columns=["key", "qty_stock", "qty_transit", "value_file", "article"])
    loc_key = pd.DataFrame(columns=["location", "key", "units", "transit"])
    snaps = pd.DataFrame(columns=["location", "dates", "n_dates", "sources"])
    unmatched = []
    stock_warn = []
    if stock is not None and len(stock):
        rec = stock.copy()
        by_nm = pd.to_numeric(rec["nm"], errors="coerce").map(km["nm2key"])
        rec["key"] = by_nm.where(by_nm.notna(), rec["key"].map(lambda k: km["canon"].get(k, k) if isinstance(k, str) else k))
        rec = rec[rec["key"].notna()]
        rec, stock_warn = stock_io.dedupe(rec)
        st, loc_key, snaps = stock_io.combine(rec)
    # нулевой остаток в файле — тоже факт («на дату снимка товара нет»), но новые строки отчёта он не создаёт
    stk = st.set_index("key") if len(st) else st
    keys |= set(st.loc[(st["qty_stock"] + st["qty_transit"]) > 0, "key"]) if len(st) else set()

    rows = []
    for k in sorted(keys):
        r = direct.loc[k] if k in direct.index else pd.Series(0.0, index=val_cols)
        # имя для отчёта: из файла остатков (там обычно «человеческий» регистр), иначе из детализации
        sname = stk.at[k, "article"] if len(st) and k in stk.index and isinstance(stk.at[k, "article"], str) else None
        if sname and norm(sname) != k and k in km["names"]:
            sname = None   # в остатках связали по коду WB, а название другое — показываем название из детализации
        name = sname or km["names"].get(k) or k
        sold, retq = float(r["_qty_sold"]), float(r["_qty_ret"])
        cogs = cg.at[k, "cogs"] if k in cg.index else (0.0 if sold == 0 else None)
        cogs = None if cogs is None or (isinstance(cogs, float) and math.isnan(cogs)) else float(cogs)
        # стоимость единицы остатка
        up, up_sup = latest_price(k, catalog, aliases)
        up_src = f"цена поставки {up_sup}" if up is not None else None
        if up is None and cogs and sold > 0:
            up, up_src = cogs / max(sold - retq, 1), "средняя себестоимость проданной единицы"
        if len(st) and k in stk.index:
            q_st, q_tr = float(stk.at[k, "qty_stock"]), float(stk.at[k, "qty_transit"])
            vf = stk.at[k, "value_file"]
            stock_src = "реальный"
            if up is None and pd.notna(vf) and (q_st + q_tr) > 0:
                up, up_src = float(vf) / (q_st + q_tr), "из файла остатков"
        elif test_stock_days and sold > 0:
            q_st = math.ceil(sold / days * test_stock_days)
            q_tr, stock_src = 0.0, "ТЕСТ"
        else:
            q_st, q_tr, stock_src = 0.0, 0.0, "нет данных"
        units = q_st + q_tr
        capital = units * up if up is not None else None
        rows.append({"key": k, "Артикул": name, "Продано, шт": sold, "Возвратов, шт": retq,
                     "Выручка": float(r["_rev"]), "К перечислению за товар": float(r["_pay"]),
                     "Логистика": float(r["logistics"]), "Штрафы": float(r["penalty"]),
                     "Корректировка ВВ": float(r["vv_corr"]), "Хранение": float(r["storage"]),
                     "Платная приёмка": float(r["acceptance"]), "Возмещение издержек": float(r["rebill"]),
                     **{"ded_" + g["id"]: float(r["ded_" + g["id"]]) for g in groups},
                     "Себестоимость": cogs, "_cogs_missing": int(cg.at[k, "cogs_missing"]) if k in cg.index else 0,
                     "_cogs_fallback": int(cg.at[k, "cogs_fallback"]) if k in cg.index else 0,
                     "Компенсация лояльности WB": float(r["loyalty_comp"]),
                     "Лояльность WB (участие, баллы)": float(r["loyalty_cost"]) + float(r["loyalty_points"]),
                     "Остаток, шт": q_st, "В пути, шт": q_tr, "Цена единицы остатка": up,
                     "Откуда цена остатка": up_src, "Остаток": stock_src, "Капитал в остатке": capital})
    t = pd.DataFrame(rows).set_index("key")

    # --- разнесение общих расходов
    base_rev = t["Выручка"].clip(lower=0)
    base_cap = t["Капитал в остатке"].fillna(0)
    col_of = {"logistics": "Логистика", "penalty": "Штрафы", "vv_corr": "Корректировка ВВ", "storage": "Хранение",
              "acceptance": "Платная приёмка", "rebill": "Возмещение издержек",
              "loyalty_comp": "Компенсация лояльности WB", "loyalty_cost": "Лояльность WB (участие, баллы)",
              "loyalty_points": "Лояльность WB (участие, баллы)",
              **{g["id"]: "ded_" + g["id"] for g in groups}}
    alloc_log = []
    for bucket, col in col_of.items():
        src = "ded_" + bucket if bucket in {g["id"] for g in groups} else bucket
        amt = float(common.get(src, 0.0))
        if abs(amt) < 0.005:
            continue
        how = alloc.get(bucket, "revenue")
        base = base_cap if how == "capital" and base_cap.sum() > 0 else base_rev
        if base.sum() <= 0:
            base = pd.Series(1.0, index=t.index)
        share = base / base.sum()
        t["_alloc_" + bucket] = amt * share
        t[col] = t[col] + t["_alloc_" + bucket]
        if bucket in excluded_groups:
            continue
        label = next((g["label"] for g in groups if g["id"] == bucket), col)
        alloc_log.append({"Статья": label, "Сумма без артикула": round(amt, 2),
                          "Разнесено": "по деньгам в остатке" if base is base_cap else "по выручке"})

    # --- P&L
    for g in groups:
        t[g["label"]] = t.pop("ded_" + g["id"])
    t["Комиссия и эквайринг"] = t["Выручка"] - t["К перечислению за товар"]
    t["Налог"] = t["Выручка"] * tax
    cost_cols = ["Логистика", "Штрафы", "Корректировка ВВ", "Хранение", "Платная приёмка", "Возмещение издержек",
                 "Лояльность WB (участие, баллы)"] + \
                [g["label"] for g in groups if g["id"] not in excluded_groups]
    t["Расходы WB и маркетинг"] = t[cost_cols].sum(axis=1)
    t["Прибыль"] = t["К перечислению за товар"] + t["Компенсация лояльности WB"] - t["Расходы WB и маркетинг"] - t["Себестоимость"].fillna(0) - t["Налог"]
    t.loc[t["Себестоимость"].isna(), "Прибыль"] = float("nan")
    t["Маржа, %"] = (t["Прибыль"] / t["Выручка"].where(t["Выручка"] > 0)) * 100
    cap_ok = t["Капитал в остатке"].fillna(0) >= th["min_capital_rub"]
    t["Доходность капитала, %"] = (t["Прибыль"] * ann / t["Капитал в остатке"].where(cap_ok)) * 100
    cogs_year = t["Себестоимость"].fillna(0).clip(lower=0) * turn_ann
    t["Оборотов в год"] = cogs_year / t["Капитал в остатке"].where(cap_ok)
    t["Запас, дней"] = t["Капитал в остатке"].where(cap_ok) / (t["Себестоимость"].where(t["Себестоимость"] > 0) / days)
    max_days = th["max_stock_days"]
    # лишний запас — деньги сверх запаса на max_stock_days дней продаж
    t["Лишний запас, ₽"] = (t["Капитал в остатке"].where(cap_ok) -
                            t["Себестоимость"].fillna(0).clip(lower=0) / days * max_days).clip(lower=0)

    def verdict(r, col):
        if pd.isna(r["Себестоимость"]) and r["Продано, шт"] > 0:
            return "нет себестоимости"
        if not (r["Капитал в остатке"] or 0) >= th["min_capital_rub"]:
            return "мало остатка на дату снимка" if r["Остаток"] != "нет данных" else "нет данных об остатке"
        if r["Продано, шт"] <= 0 and r["Выручка"] <= 0:
            return "нет продаж в периоде"   # неликвид или только что пришёл — решает человек
        v = r[col]
        if v > th["develop_above_pct"]:
            # доходный, но денег в запасе больше, чем на max_stock_days продаж
            slow = (r["Запас, дней"] or 0) > max_days and (r["Лишний запас, ₽"] or 0) >= th["min_excess_rub"]
            return "сократить закупку" if slow else "развивать"
        if v < th["withdraw_below_pct"]:
            return "выводить"
        return "держать"

    t["Вердикт"] = t.apply(lambda r: verdict(r, "Доходность капитала, %"), axis=1)

    # --- сценарий «комиссия +N п.п.»
    t["Доп. комиссия (сценарий)"] = t["Выручка"].clip(lower=0) * comm_pp / 100
    t["Прибыль (сценарий)"] = t["Прибыль"] - t["Доп. комиссия (сценарий)"]
    t["Доходность капитала, % (сценарий)"] = (t["Прибыль (сценарий)"] * ann /
                                                  t["Капитал в остатке"].where(cap_ok)) * 100
    tmp = t.assign(**{"Доходность капитала, %": t["Доходность капитала, % (сценарий)"],
                      "Себестоимость": t["Себестоимость"]})
    t["Вердикт (сценарий)"] = tmp.apply(lambda r: verdict(r, "Доходность капитала, %"), axis=1)

    # --- снимки остатков против периода продаж
    if stock is not None and len(stock):
        for dd in sorted({pd.Timestamp(x) for x in stock["date"].dropna()}):
            if pd.notna(d0) and dd < d0:
                stock_warn.append(f"снимок остатков {dd:%d.%m.%Y} — до начала периода продаж ({d0:%d.%m.%Y}): "
                                  f"это остаток на начало, а не средний за период")
            elif pd.notna(d1) and dd > d1:
                stock_warn.append(f"снимок остатков {dd:%d.%m.%Y} — после конца периода продаж ({d1:%d.%m.%Y})")
        if len(snaps) > 1 and snaps["dates"].nunique() > 1:
            stock_warn.append("у мест хранения разные наборы дат: каждое место усреднено по своим снимкам; "
                              "если товар переезжал между местами между датами, капитал может быть посчитан неточно")

    # --- проверки
    tot_direct = direct[["_pay"] + MONEY_COST + ["ded_" + g["id"] for g in groups]].sum()
    cab_net = float(df["_pay"].sum()) + float(df["loyalty_comp"].sum()) - float(df[MONEY_COST].sum().sum()) - \
        sum(float(df["ded_" + g["id"]].sum()) for g in groups if g["id"] not in excluded_groups)
    art_net = float((t["К перечислению за товар"] + t["Компенсация лояльности WB"] - t["Расходы WB и маркетинг"]).sum())
    opiu_q = pairs.loc[pairs["Знак"] == "продажа"] if len(pairs) else pairs
    checks = {
        "period": (d0, d1, days),
        "cabinet_net_before_cogs": round(cab_net, 2),
        "articles_net_before_cogs": round(art_net, 2),
        "conserved": abs(cab_net - art_net) < 1.0,
        "opiu_sales_qty": float(opiu_q["Кол-во"].sum()) if len(opiu_q) else 0,
        "opiu_pairs": int(len(opiu_q)),
        "opiu_status": opiu_q["status"].value_counts().to_dict() if len(opiu_q) else {},
        "opiu_cogs": round(float(opiu_q["Себестоимость"].sum()), 2) if len(opiu_q) else 0.0,
        "excluded": {g["label"]: round(float(df["ded_" + g["id"]].sum()), 2) for g in groups if g["id"] in excluded_groups},
        "filled_by_nm": km["filled_by_nm"],
        "allocation": alloc_log,
        "commission_pp": comm_pp,
        "stock_label": stock_label,
        "test_stock_days": test_stock_days,
        "tax_pct": tax * 100,
        "basis": basis,
        "merged_articles": km["merged"],
        "stock_warnings": stock_warn,
    }
    # --- сколько денег где лежит
    locs = pd.DataFrame(columns=["Место хранения", "Даты снимков", "Штук", "Деньги по себестоимости", "Доля, %", "Источник"])
    if len(loc_key):
        lk = loc_key.copy()
        lk["price"] = lk["key"].map(t["Цена единицы остатка"])
        lk["cap"] = (lk["units"] + lk["transit"]) * lk["price"]
        g = lk.groupby("location").agg(units=("units", "sum"), transit=("transit", "sum"), cap=("cap", "sum"))
        g = g[(g["units"] + g["transit"]) > 0]   # пустые места (например, «свои склады» с нулями) не показываем
        g = g.join(snaps.set_index("location"))
        tot = g["cap"].sum()
        locs = pd.DataFrame({"Место хранения": g.index,
                             "Даты снимков": g["dates"].to_numpy(),
                             "Штук": (g["units"] + g["transit"]).round().to_numpy(),
                             "в т.ч. в пути": g["transit"].round().to_numpy(),
                             "Деньги по себестоимости": g["cap"].round(2).to_numpy(),
                             "Доля, %": (g["cap"] / tot * 100 if tot else g["cap"] * 0).round(1).to_numpy(),
                             "Источник": g["sources"].to_numpy()}).sort_values("Деньги по себестоимости", ascending=False)
    lk_out = pd.DataFrame(columns=["location", "key", "cap"])
    if len(loc_key):
        lk_out = loc_key.assign(cap=(loc_key["units"] + loc_key["transit"]) * loc_key["key"].map(t["Цена единицы остатка"]))
        lk_out = lk_out[lk_out["cap"].fillna(0) > 0][["location", "key", "cap"]]
    return {"table": t.reset_index(), "pairs": pairs, "checks": checks, "days": days, "locations": locs,
            "loc_key": lk_out}
