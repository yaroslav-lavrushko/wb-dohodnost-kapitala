"""Командная строка: wb-capital --in <папка> --out <папка>."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .pipeline import Options, run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="wb-capital",
        description="Доходность вложенного капитала по товарам Wildberries: P&L по артикулу, деньги в остатках, "
                    "вердикты «развивать / сократить закупку / держать / выводить», отчёт Excel + HTML.")
    ap.add_argument("--in", dest="inputs", action="append", default=[], metavar="ПУТЬ",
                    help="папка или файл с выгрузками (можно несколько раз); тип файла определяется по колонкам")
    ap.add_argument("--out", required=True, metavar="ПАПКА", help="куда положить отчёт")
    ap.add_argument("--detail", action="append", default=[], metavar="ФАЙЛ", help="детализация WB явно")
    ap.add_argument("--catalog", action="append", default=[], metavar="ФАЙЛ", help="каталог себестоимости явно")
    ap.add_argument("--stock", action="append", default=[], metavar="ФАЙЛ[@ДАТА]",
                    help="остатки явно, можно с датой снимка: «остатки.xlsx@2026-03-24»; сколько угодно")
    ap.add_argument("--config", help="свой config.json (пороги, правила разнесения)")
    ap.add_argument("--aliases", help="aliases.json: артикул WB → название в каталоге себестоимости")
    ap.add_argument("--commission-pp", type=float, help="сценарий «комиссия маркетплейса +N п.п.»")
    ap.add_argument("--stock-date", default="", help="дата снимка для файлов остатков без даты")
    ap.add_argument("--test-stock-days", type=float,
                    help="артикулам без остатка подставить ТЕСТОВЫЙ запас на N дней продаж (только для проверки)")
    ap.add_argument("--label", default="", help="подпись прогона в отчёте")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = ap.parse_args(argv)
    opts = Options(inputs=a.inputs, detail=a.detail, catalog=a.catalog, stock=a.stock, config=a.config,
                   aliases=a.aliases, commission_pp=a.commission_pp, stock_date=a.stock_date,
                   test_stock_days=a.test_stock_days, label=a.label)
    res = run(opts, a.out)
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
