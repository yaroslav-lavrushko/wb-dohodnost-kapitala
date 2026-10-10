"""Демо-магазин «Северная косметика» — полностью выдуманный.

Бренды, товары, коды, поставки, склады и цифры придуманы. Совпадения с реальными магазинами случайны.
Экономика подобрана правдоподобной для маркетплейса косметики: 30 товаров, 13 недель продаж
(29.06–27.09.2026), выручка ~2,5 млн ₽ в месяц, комиссия 24–31%, реклама ~7% выручки.
Остатки — три места хранения на две даты (начало и конец периода) в трёх разных форматах:
отчёт WB «Остатки по складам», учётная выгрузка своего склада (1С-подобная), выгрузка фулфилмента
(строка = артикул × склад × дата).

Запуск: python demo/make_demo.py  → файлы в demo/data/
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "data"
START = pd.Timestamp("2026-06-29")          # понедельник
WEEKS = 13
END = START + pd.Timedelta(days=WEEKS * 7 - 1)
rng = random.Random(20261010)

BRANDS = ["Миранта", "Аэлита", "Сольвейг", "Кедровый край", "Ладушка"]
KINDS = [
    ("Крем для рук питательный", "75 мл", 590), ("Крем для лица увлажняющий", "50 мл", 1290),
    ("Сыворотка с витамином C", "30 мл", 1490), ("Шампунь мягкий детский", "250 мл", 690),
    ("Бальзам для губ", "4,5 г", 290), ("Гель для душа", "400 мл", 520), ("Маска для волос", "200 мл", 890),
    ("Крем для ног от трещин", "75 мл", 790), ("Мицеллярная вода", "400 мл", 640), ("Скраб для тела", "300 мл", 760),
    ("Тоник для лица", "200 мл", 710), ("Детское молочко для тела", "300 мл", 980),
]

# профиль → (спрос шт/день, наценка цены к себестоимости, комиссия, запас на начало дн., запас на конец дн., доля возвратов)
PROFILES = {
    "звезда":       (7.5, 2.45, 0.27, 55, 50, 0.03),
    "крепкий":      (4.2, 2.35, 0.28, 70, 65, 0.04),
    "затоварен":    (3.3, 2.60, 0.27, 160, 190, 0.03),
    "средний":      (1.8, 2.45, 0.28, 110, 120, 0.05),
    "слабый":       (0.9, 1.75, 0.31, 260, 300, 0.08),
    "новинка":      (0.0, 2.50, 0.27, 0, 120, 0.00),
    "распродан":    (5.0, 2.60, 0.27, 0.3, 0.2, 0.02),
}
PLAN = (["звезда"] * 5 + ["крепкий"] * 7 + ["затоварен"] * 6 + ["средний"] * 5 + ["слабый"] * 4
        + ["новинка"] * 2 + ["распродан"] * 1)


def make_items():
    items = []
    used = set()
    for i, prof in enumerate(PLAN):
        while True:
            brand, (kind, vol, base) = rng.choice(BRANDS), rng.choice(KINDS)
            if (brand, kind) not in used:
                used.add((brand, kind))
                break
        price = round(base * rng.uniform(0.9, 1.15) / 10) * 10 - 1
        demand, markup, comm, d0, d1, ret = PROFILES[prof]
        cost = round(price / markup * rng.uniform(0.95, 1.05), 2)
        name = f"{brand} {kind} {vol}"
        items.append({"name": name, "brand": brand, "kind": kind, "article": name.lower(), "nm": 7100001 + i * 37, "price": price,
                      "cost": cost, "demand": demand * rng.uniform(0.85, 1.15), "comm": comm + rng.uniform(-0.02, 0.02),
                      "d0": d0, "d1": d1, "ret": ret, "profile": prof,
                      "logi": round(rng.uniform(38, 55) if price < 450 else rng.uniform(58, 95), 2), "supplies": []})
    # поставки: 2–3 на товар, цена закупки плавает ±6%
    sup = 41000
    for it in items:
        for k in range(rng.choice([2, 3])):
            sup += rng.randint(3, 40)
            it["supplies"].append((sup, round(it["cost"] * rng.uniform(0.94, 1.06), 2)))
    return items


COLS = ["Номер поставки", "Предмет", "Код номенклатуры", "Бренд", "Артикул поставщика", "Название", "Баркод",
        "Тип документа", "Обоснование для оплаты", "Дата заказа покупателем", "Дата продажи", "Кол-во",
        "Цена розничная с учетом согласованной скидки", "Вайлдберриз реализовал Товар (Пр)",
        "К перечислению Продавцу за реализованный Товар", "Услуги по доставке товара покупателю",
        "Общая сумма штрафов", "Корректировка Вознаграждения Вайлдберриз (ВВ)",
        "Виды логистики, штрафов и корректировок ВВ", "Хранение", "Удержания", "Операции на приемке",
        "Возмещение издержек по перевозке/по складским операциям с товаром",
        "Компенсация скидки по программе лояльности", "Склад", "Srid"]
WAREHOUSES = ["Коледино", "Электросталь", "Казань", "Краснодар", "Екатеринбург"]


def week_rows(items, w):
    ws = START + pd.Timedelta(days=7 * w)
    rows, revenue = [], 0.0
    for it in items:
        if it["demand"] <= 0:
            continue
        season = 1 + 0.15 * (w - WEEKS / 2) / WEEKS                # лёгкий рост к осени
        n = sum(1 for _ in range(7) for _ in range(int(it["demand"] * season * rng.uniform(0.6, 1.4) + rng.random())))
        sup = it["supplies"][min(len(it["supplies"]) - 1, w * len(it["supplies"]) // WEEKS)][0]
        for j in range(n):
            d = ws + pd.Timedelta(days=rng.randrange(7))
            srid = f"d{it['nm']}{w:02d}{j:03d}"
            base = {"Номер поставки": sup, "Предмет": it["kind"], "Код номенклатуры": it["nm"],
                    "Бренд": it["brand"], "Артикул поставщика": it["article"], "Название": it["name"],
                    "Баркод": 4600000000000 + it["nm"], "Дата заказа покупателем": d - pd.Timedelta(days=2),
                    "Дата продажи": d, "Склад": rng.choice(WAREHOUSES), "Srid": srid}
            price = it["price"] * rng.uniform(0.93, 1.0)
            ret = rng.random() < it["ret"]
            rows.append({**base, "Тип документа": "Возврат" if ret else "Продажа",
                         "Обоснование для оплаты": "Возврат" if ret else "Продажа", "Кол-во": 1,
                         "Цена розничная с учетом согласованной скидки": round(price, 2),
                         "Вайлдберриз реализовал Товар (Пр)": round(price * 0.78, 2),
                         "К перечислению Продавцу за реализованный Товар": round(price * (1 - it["comm"]), 2)})
            rows.append({**base, "Обоснование для оплаты": "Логистика", "Кол-во": 0,
                         "Услуги по доставке товара покупателю": round(it["logi"] * rng.uniform(0.85, 1.2) * (2 if ret else 1), 2)})
            revenue += 0 if ret else price
            if rng.random() < 0.004:
                rows.append({**base, "Обоснование для оплаты": "Коррекция логистики", "Кол-во": 0,
                             "Услуги по доставке товара покупателю": round(rng.uniform(20, 120), 2)})
    end = ws + pd.Timedelta(days=6)
    rows.append({"Обоснование для оплаты": "Хранение", "Хранение": round(revenue * rng.uniform(0.012, 0.018), 2),
                 "Дата продажи": end, "Srid": f"st{w}"})
    rows.append({"Обоснование для оплаты": "Удержание", "Удержания": round(revenue * rng.uniform(0.06, 0.08), 2),
                 "Виды логистики, штрафов и корректировок ВВ": f"Оказание услуг «WB Продвижение», документ №D{w:04d}",
                 "Дата продажи": end, "Srid": f"ad{w}"})
    rows.append({"Обоснование для оплаты": "Компенсация скидки по программе лояльности", "Тип документа": "Продажа",
                 "Компенсация скидки по программе лояльности": round(revenue * 0.002, 2), "Дата продажи": end,
                 "Srid": f"lo{w}"})
    if w % 4 == 1:
        rows.append({"Обоснование для оплаты": "Штраф", "Общая сумма штрафов": 1000.0,
                     "Виды логистики, штрафов и корректировок ВВ": "Штраф за неправильную упаковку товара",
                     "Дата продажи": end, "Srid": f"pn{w}"})
    return pd.DataFrame(rows, columns=COLS), ws, end


def units_for(it, days):
    return int(round(it["demand"] * days)) if it["demand"] > 0 else 0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.xlsx"):
        f.unlink()
    items = make_items()
    for w in range(WEEKS):
        df, ws, we = week_rows(items, w)
        df.to_excel(OUT / f"Еженедельный детализированный отчет №D{1000 + w}_demo.xlsx", index=False)
    # каталог себестоимости по поставкам
    cat = [{"Номер поставки": s, "Название товара": it["article"], "Себестоимость": c, "Кол-во в поставке": 300}
           for it in items for s, c in it["supplies"]]
    with pd.ExcelWriter(OUT / "каталог-себестоимости.xlsx") as w:
        pd.DataFrame(cat).to_excel(w, sheet_name="Каталог (себестоимость)", index=False)
    # остатки: запас дней → штуки, раскладка: WB 55%, свой склад 30%, фулфилмент 15%
    for date, key in ((START, "d0"), (END, "d1")):
        wb, own, ff = [], [], []
        for it in items:
            days = it[key] if it["profile"] != "новинка" or key == "d1" else 0
            base_units = units_for(it, days) if it["demand"] > 0 else (420 if key == "d1" else 0)
            if it["profile"] == "распродан":
                base_units = 0
            a, b = round(base_units * 0.55), round(base_units * 0.30)
            c = max(base_units - a - b, 0)
            if it["profile"] == "новинка":
                a, b, c = 0, base_units, 0              # новинка только что пришла на свой склад
            wb.append({"Бренд": it["brand"], "Предмет": "Косметика", "Артикул продавца": it["name"],
                       "В пути до получателей": 0 if it["profile"] == "распродан" else round(it["demand"] * 2),
                       "В пути возвраты на склад WB": 0 if it["profile"] == "распродан" else round(it["demand"] * 0.1),
                       "Всего находится на складах": a})
            own.append({"Код": it["nm"] % 1000, "Артикул": it["nm"], "Наименование": it["name"], "Ед.изм.": "шт",
                        "Остаток": b})
            ff.append({"Дата": date.strftime("%d.%m.%Y"), "Склад": "Фулфилмент Подольск",
                       "Артикул поставщика": it["article"], "Остаток, шт": c})
        pd.DataFrame(wb).to_excel(OUT / f"остатки-WB-{date:%Y-%m-%d}.xlsx", index=False)
        with pd.ExcelWriter(OUT / f"остатки-склад-Москва-{date:%Y-%m-%d}.xlsx") as w:
            pd.DataFrame(own).to_excel(w, sheet_name="Склад Москва", index=False)
        ff_path = OUT / "остатки-фулфилмент.xlsx"
        prev = pd.read_excel(ff_path) if ff_path.exists() else pd.DataFrame()
        pd.concat([prev, pd.DataFrame(ff)], ignore_index=True).to_excel(ff_path, index=False)
    print(f"готово: {len(items)} товаров, {WEEKS} недель, файлы в {OUT}")


if __name__ == "__main__":
    main()
