"""Интерактивный HTML-отчёт: один самодостаточный файл, работает без интернета.

Python отдаёт в страницу базовые цифры по каждому товару; пороги, сценарий комиссии и вердикты
пересчитываются в браузере по тем же правилам, что в capital.py (при значениях по умолчанию страница
сверяет свои вердикты с расчётом Python и предупреждает при расхождении).
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import pandas as pd


def _f(v, d=2):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, d)


def build_data(t: pd.DataFrame, s: dict, checks: dict, meta: dict, cfg: dict, concl: list[str], res: dict,
               provenance: list[str]) -> dict:
    th = cfg["thresholds"]
    days = checks["period"][2]
    basis = checks.get("basis", "year")
    ads_label = next((g["label"] for g in cfg["deduction_groups"] if g["id"] == "ads"), None)
    lk = res.get("loc_key")
    locs_by_key: dict = {}
    if lk is not None and len(lk):
        for _, r in lk.iterrows():
            locs_by_key.setdefault(r["key"], {})[r["location"]] = round(float(r["cap"]), 2)
    items = []
    for _, r in t.iterrows():
        costs = float(r["Расходы WB и маркетинг"])
        logi, stor = float(r["Логистика"]), float(r["Хранение"])
        ads = float(r[ads_label]) if ads_label and ads_label in r else 0.0
        items.append({
            "n": r["Артикул"], "v": r["Вердикт"], "st": r["Остаток"], "sold": _f(r["Продано, шт"], 0),
            "rev": _f(r["Выручка"]), "comm": _f(r["Комиссия и эквайринг"]), "logi": _f(logi), "stor": _f(stor),
            "ads": _f(ads), "other": _f(costs - logi - stor - ads), "loy": _f(r["Компенсация лояльности WB"]),
            "tax": _f(r["Налог"]), "cogs": _f(r["Себестоимость"]), "profit": _f(r["Прибыль"]),
            "cap": _f(r["Капитал в остатке"]), "locs": locs_by_key.get(r["key"], {}),
        })
    loc_names = list(s["locations"]["Место хранения"]) if s.get("locations") is not None and len(s["locations"]) else []
    d0, d1, _ = checks["period"]
    return {
        "meta": {"label": meta.get("label") or "", "period": f"{d0:%d.%m.%Y} – {d1:%d.%m.%Y}", "days": days,
                 "runDate": meta.get("run_date", ""), "provenance": provenance,
                 "warnings": checks.get("stock_warnings", []), "conclusions": concl,
                 "test": bool(s.get("test_rows")), "tax": checks.get("tax_pct", 0)},
        "cfg": {"dev": th["develop_above_pct"], "wd": th["withdraw_below_pct"], "maxd": th["max_stock_days"],
                "minEx": th["min_excess_rub"], "minCap": th["min_capital_rub"], "pp": checks["commission_pp"],
                "ann": (365.0 if basis == "year" else 365.0 / 12) / days, "turnAnn": 365.0 / days,
                "bl": "годовых" if basis == "year" else "в месяц"},
        "locs": loc_names, "items": items,
    }


def write_html(path: Path, t, s, checks, meta, cfg, concl, res):
    from .report import _provenance  # локально, чтобы не было циклического импорта
    data = build_data(t, s, checks, meta, cfg, concl, res, _provenance(s, meta, checks))
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(meta.get("label") or "Доходность капитала")
    path.write_text(TEMPLATE.replace("%%DATA%%", js).replace("%%TITLE%%", title), encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Доходность капитала</title>
<meta name="description" content="%%TITLE%%">
<style>
:root{--plane:#f4f4f1;--surface:#fff;--surface-2:#fafaf8;--surface-3:#f0f0eb;--ink:#0b0b0b;--ink-2:#4d4c49;--ink-3:#73716c;--ink-4:#9a988f;
--line:#e6e5df;--line-2:#d6d5ce;--good:#0ca30c;--good-t:#0a7d0a;--good-s:rgba(12,163,12,.10);--warn:#d98a00;--warn-t:#9a6100;--warn-s:rgba(217,138,0,.12);
--crit:#d03b3b;--crit-t:#b02a2a;--crit-s:rgba(208,59,59,.10);--hold:#2a78d6;--hold-t:#1f62b3;--hold-s:rgba(42,120,214,.10);--mute:#9a988f;--mute-s:rgba(120,120,110,.12);
--accent:#2a78d6;--shadow:0 1px 2px rgba(0,0,0,.05),0 10px 30px rgba(0,0,0,.08);
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,"Helvetica Neue",Arial,sans-serif;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--plane:#0e0f11;--surface:#16171a;--surface-2:#1b1c20;--surface-3:#23252a;--ink:#f5f5f3;--ink-2:#c6c8cc;--ink-3:#8e9196;--ink-4:#6b6e74;
--line:#26282d;--line-2:#34373d;--good-t:#3ccf3c;--good-s:rgba(12,163,12,.16);--warn:#fab219;--warn-t:#fab219;--warn-s:rgba(250,178,25,.14);--crit:#e05252;--crit-t:#ff7a7a;--crit-s:rgba(224,82,82,.15);
--hold:#3f8ff0;--hold-t:#6aa9ff;--hold-s:rgba(63,143,240,.15);--mute-s:rgba(200,200,190,.10);--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 34px rgba(0,0,0,.4);color-scheme:dark}}
:root[data-theme="dark"]{--plane:#0e0f11;--surface:#16171a;--surface-2:#1b1c20;--surface-3:#23252a;--ink:#f5f5f3;--ink-2:#c6c8cc;--ink-3:#8e9196;--ink-4:#6b6e74;
--line:#26282d;--line-2:#34373d;--good-t:#3ccf3c;--good-s:rgba(12,163,12,.16);--warn:#fab219;--warn-t:#fab219;--warn-s:rgba(250,178,25,.14);--crit:#e05252;--crit-t:#ff7a7a;--crit-s:rgba(224,82,82,.15);
--hold:#3f8ff0;--hold-t:#6aa9ff;--hold-s:rgba(63,143,240,.15);--mute-s:rgba(200,200,190,.10);--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 34px rgba(0,0,0,.4);color-scheme:dark}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--plane);color:var(--ink);font:15px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 72px}
h1{font-size:clamp(22px,3.2vw,30px);letter-spacing:-.02em;margin:0;line-height:1.15}h2{font-size:17px;margin:0;letter-spacing:-.01em}
.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.top>div{flex:1}
.sub{color:var(--ink-3);font-size:13.5px;margin-top:6px}
.btn{font:inherit;font-size:13px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2);padding:7px 12px;border-radius:10px;cursor:pointer}
.btn:hover{border-color:var(--ink-4);color:var(--ink)}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:99px;background:var(--warn-s);color:var(--warn-t);margin-left:6px;vertical-align:middle}
.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow)}
.hero{margin:20px 0 14px;display:grid;grid-template-columns:1.25fr 2fr;gap:14px}
.hero .big{display:flex;flex-direction:column;justify-content:space-between;background:linear-gradient(135deg,var(--good-s),transparent 70%),var(--surface)}
.big .k{font-size:13px;color:var(--ink-3);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.big .v{font-size:clamp(34px,5vw,46px);font-weight:700;letter-spacing:-.03em;line-height:1.05;margin:8px 0 6px;font-variant-numeric:tabular-nums}
.big .d{font-size:13.5px;color:var(--ink-2)}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border-radius:16px;overflow:hidden;border:1px solid var(--line);box-shadow:var(--shadow)}
.steps div{background:var(--surface);padding:16px}
.steps .n{font-size:12px;color:var(--ink-4);font-weight:700}.steps b{display:block;font-size:22px;letter-spacing:-.02em;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.steps span{font-size:13px;color:var(--ink-3);line-height:1.4;display:block}
.ctrl{display:grid;grid-template-columns:repeat(4,1fr) auto;gap:16px;align-items:end;margin-bottom:14px}
.ctrl label{display:block;font-size:12.5px;color:var(--ink-3);font-weight:600}
.ctrl output{float:right;color:var(--ink);font-variant-numeric:tabular-nums}
.ctrl input[type=range]{width:100%;accent-color:var(--accent);margin-top:8px}
.ctrl .changed output{color:var(--accent)}
.grid2{display:grid;grid-template-columns:1.6fr 1fr;gap:14px;margin-bottom:14px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 4px}
.chip{font:inherit;font-size:12.5px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2);border-radius:99px;padding:4px 10px;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.chip i{width:9px;height:9px;border-radius:50%;display:inline-block}.chip b{font-variant-numeric:tabular-nums;color:var(--ink)}
.chip[aria-pressed="false"]{opacity:.45}
#quad{position:relative}#quad svg{display:block;width:100%;height:auto;overflow:visible}
#quad text{font-size:11px;fill:var(--ink-3);font-family:var(--sans)}
.zg{fill:var(--good-s)}.zr{fill:var(--crit-s)}.ax{stroke:var(--line-2)}.thl{stroke:var(--ink-4);stroke-dasharray:4 4}
g.b{transition:transform .6s cubic-bezier(.2,.7,.3,1),opacity .3s;cursor:pointer}g.b circle{transition:fill .35s;stroke:var(--surface);stroke-width:2;fill-opacity:.88}
g.b.t circle{stroke:var(--ink-3);stroke-dasharray:3 2}g.b.dim{opacity:.12}g.b.hi circle{stroke:var(--ink);stroke-width:2.5}
.tip{position:absolute;pointer-events:none;background:var(--surface-3);border:1px solid var(--line-2);border-radius:10px;padding:8px 10px;font-size:12.5px;color:var(--ink-2);opacity:0;transition:opacity .12s;z-index:5;max-width:280px;box-shadow:var(--shadow)}
.tip.on{opacity:1}.tip b{color:var(--ink)}
.loc{margin:12px 0}.loc .h{display:flex;justify-content:space-between;font-size:13.5px;gap:8px}.loc .h b{font-variant-numeric:tabular-nums}
.bar{display:flex;height:12px;border-radius:6px;overflow:hidden;background:var(--surface-3);margin-top:6px}
.bar i{display:block;height:100%;transition:width .5s}
.small{font-size:12.5px;color:var(--ink-3)}
.tw{overflow:auto;max-height:560px;border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{position:sticky;top:0;background:var(--surface);color:var(--ink-3);font-weight:600;font-size:12px;cursor:pointer;user-select:none;z-index:1}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:220px}
tbody tr{cursor:pointer}tbody tr:hover,tbody tr.hi{background:var(--surface-3)}
.pill{display:inline-block;font-size:12px;font-weight:600;padding:2px 9px;border-radius:99px;white-space:nowrap}
.neg{color:var(--crit-t)}.test{color:var(--warn-t);font-weight:600}
.search{font:inherit;font-size:13px;border:1px solid var(--line-2);background:var(--surface);color:var(--ink);border-radius:10px;padding:7px 10px;min-width:220px}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
details{margin-top:14px}summary{cursor:pointer;font-weight:600}details ul{margin:10px 0 0;padding-left:20px}details li{margin:4px 0;color:var(--ink-2)}
.warn{background:var(--warn-s);border-radius:12px;padding:10px 14px;font-size:13.5px;margin-bottom:14px;color:var(--ink)}
/* карточка товара */
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.35);opacity:0;pointer-events:none;transition:opacity .2s;z-index:20}
.scrim.on{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;height:100%;width:min(460px,100%);background:var(--surface);z-index:21;transform:translateX(105%);transition:transform .28s cubic-bezier(.2,.7,.3,1);
box-shadow:var(--shadow);overflow-y:auto;padding:22px 20px 40px;border-left:1px solid var(--line)}
.drawer.on{transform:none}.drawer h3{font-size:19px;margin:6px 0 10px;line-height:1.25;letter-spacing:-.01em}
.kp{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}.kp div{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.kp b{display:block;font-size:18px;font-variant-numeric:tabular-nums}.kp span{font-size:12px;color:var(--ink-3)}
.why{background:var(--surface-2);border-left:3px solid var(--accent);padding:10px 12px;border-radius:8px;font-size:13.5px;margin:10px 0}
.wf text{font-size:11.5px;fill:var(--ink-2);font-family:var(--sans)}.wf .lab{fill:var(--ink-3)}
.close{position:absolute;right:14px;top:14px}
@media (max-width:900px){.hero,.grid2{grid-template-columns:1fr}.ctrl{grid-template-columns:1fr 1fr}.ctrl .btn{grid-column:1/-1}}
@media (max-width:560px){.steps{grid-template-columns:1fr}.ctrl{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>Доходность вложенного капитала по товарам<span id="badge"></span></h1>
<div class="sub" id="sub"></div></div>
<button class="btn" id="theme" type="button" aria-label="Сменить тему">◐ Тема</button></div>
<div id="warns"></div>
<div class="hero">
 <div class="card big"><div><div class="k">Можно высвободить</div><div class="v" id="free">—</div>
 <div class="d" id="freeD"></div></div><div class="small" style="margin-top:10px">Лишний запас у доходных товаров + весь капитал в товарах «выводить».</div></div>
 <div class="steps">
  <div><span class="n">1 · ДЕНЬГИ В ТОВАРЕ</span><b id="s1">—</b><span id="s1d"></span></div>
  <div><span class="n">2 · ГДЕ ЛЕЖАТ</span><b id="s2">—</b><span id="s2d"></span></div>
  <div><span class="n">3 · ЧТО С НИМИ ДЕЛАТЬ</span><b id="s3">—</b><span id="s3d"></span></div>
 </div>
</div>
<div class="card ctrl" id="ctrl">
 <div><label>Комиссия маркетплейса <output id="o-pp"></output><input type="range" id="pp" min="0" max="10" step="0.5"></label></div>
 <div><label>Запас, после которого «сократить» <output id="o-maxd"></output><input type="range" id="maxd" min="30" max="180" step="5"></label></div>
 <div><label>Порог «развивать» <output id="o-dev"></output><input type="range" id="dev" min="10" max="150" step="5"></label></div>
 <div><label>Порог «выводить» <output id="o-wd"></output><input type="range" id="wd" min="0" max="30" step="1"></label></div>
 <button class="btn" id="reset" type="button">Сбросить</button>
</div>
<div class="grid2">
 <div class="card"><div class="row"><h2>Доходность × оборачиваемость</h2><span class="small">клик по кругу — карточка товара</span></div>
  <div class="chips" id="chips"></div>
  <div id="quad"><div class="tip" id="tip"></div></div>
  <div class="small" style="margin-top:6px">Размер круга — выручка. Пунктирный контур — тестовый остаток. Ось доходности логарифмическая.</div></div>
 <div class="card"><h2>Где лежат деньги</h2><div class="small" style="margin-top:4px">Деньги по себестоимости, цвет — вердикт товара</div><div id="locs"></div></div>
</div>
<div class="card"><div class="row"><h2>Все товары</h2><input class="search" id="q" type="search" placeholder="Найти товар…" aria-label="Поиск товара"></div>
 <div class="tw" style="margin-top:10px"><table id="tb"><thead><tr>
 <th data-k="n">Товар</th><th data-k="vo">Вердикт</th><th data-k="ret">Доходность, %</th><th data-k="days">Запас, дн.</th>
 <th data-k="cap">Капитал, ₽</th><th data-k="ex">Лишний запас, ₽</th><th data-k="p">Прибыль, ₽</th><th data-k="m">Маржа, %</th><th data-k="rev">Выручка, ₽</th><th data-k="st">Остаток</th>
 </tr></thead><tbody></tbody></table></div>
 <details><summary>Как считается и откуда данные</summary><ul id="prov"></ul></details>
</div>
</div>
<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" aria-hidden="true" role="dialog" aria-label="Карточка товара"><button class="btn close" id="close" type="button">✕</button><div id="dc"></div></aside>
<script>
var D=%%DATA%%;
var C=D.cfg, M=D.meta, IT=D.items;
var VERD=[["развивать","--good","--good-t","--good-s"],["сократить закупку","--warn","--warn-t","--warn-s"],["держать","--hold","--hold-t","--hold-s"],["выводить","--crit","--crit-t","--crit-s"],
["нет продаж в периоде","--mute","--ink-3","--mute-s"],["мало остатка на дату снимка","--mute","--ink-3","--mute-s"],["нет данных об остатке","--mute","--ink-3","--mute-s"],["нет себестоимости","--mute","--ink-3","--mute-s"]];
var VI={};VERD.forEach(function(v,i){VI[v[0]]=i;});
function col(v,k){var e=VERD[VI[v]]||VERD[4];return "var("+e[k||1]+")";}
var S={pp:0,maxd:C.maxd,dev:C.dev,wd:C.wd,off:{},sel:null,sk:"vo",sd:1,q:""};
function fmt(n,d){if(n===null||n===undefined||!isFinite(n))return "—";return n.toLocaleString("ru-RU",{maximumFractionDigits:d||0,minimumFractionDigits:d||0});}
function rub(n){return fmt(n)+" ₽";}
function mln(n){return Math.abs(n)>=1e6?fmt(n/1e6,2)+" млн ₽":rub(n);}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}

/* пересчёт — те же правила, что в capital.py */
function calc(it){
 var r={cap:it.cap,ret:null,days:null,ex:null,p:it.profit,turns:null};
 if(it.profit!==null) r.p=it.profit-Math.max(it.rev,0)*S.pp/100;
 var capOk=(it.cap||0)>=C.minCap;
 if(capOk&&r.p!==null){r.ret=r.p*C.ann/it.cap*100;}
 if(capOk){var cg=Math.max(it.cogs||0,0); r.turns=cg*C.turnAnn/it.cap;
  if((it.cogs||0)>0){r.days=it.cap/(it.cogs/M.days);} r.ex=Math.max(0,it.cap-cg/M.days*S.maxd);}
 var v;
 if(it.cogs===null&&it.sold>0)v="нет себестоимости";
 else if(!capOk)v=(it.st!=="нет данных")?"мало остатка на дату снимка":"нет данных об остатке";
 else if(it.sold<=0&&it.rev<=0)v="нет продаж в периоде";
 else if(r.ret>S.dev){v=(r.days!==null&&r.days>S.maxd&&(r.ex||0)>=C.minEx)?"сократить закупку":"развивать";}
 else if(r.ret<S.wd)v="выводить"; else v="держать";
 r.v=v; r.m=(it.rev>0&&r.p!==null)?r.p/it.rev*100:null; return r;}
var R=[];function recalc(){R=IT.map(calc);}

/* шапка */
function head(){
 document.getElementById("sub").textContent=(M.label?M.label+" · ":"")+"период продаж "+M.period+" ("+M.days+" дн.) · прибыль "+(M.tax?"после налога "+M.tax+"%":"до налога")+" · доходность — % "+C.bl+" на деньги в товаре по себестоимости";
 if(M.test)document.getElementById("badge").innerHTML='<span class="badge">есть тестовые остатки</span>';
 var w=document.getElementById("warns"); if(M.warnings.length)w.insertAdjacentHTML("afterbegin",'<div class="warn">⚠ '+M.warnings.map(esc).join("<br>⚠ ")+"</div>");
 document.getElementById("prov").innerHTML=M.provenance.concat([
  "Доходность = прибыль за период, приведённая к "+(C.bl==="годовых"?"году":"месяцу")+", ÷ деньги в остатке по себестоимости (цена последней поставки).",
  "Запас, дней = деньги в остатке ÷ себестоимость продаж в день. Лишний запас = деньги сверх запаса на выбранное число дней.",
  "Вердикты: выше порога «развивать» — развивать (или «сократить закупку», если запас больше порога и лишнего от "+fmt(C.minEx)+" ₽); ниже порога «выводить» — выводить; между — держать.",
  "Одна дата — места хранения складываются; одно место на разные даты — среднее по его снимкам. Расходы без артикула разнесены по выручке (хранение — по деньгам в остатке).",
  "Ползунки пересчитывают вердикты в браузере; исходные цифры не меняются. Отчёт — один файл, работает без интернета."]).map(function(x){return "<li>"+esc(x)+"</li>";}).join("");}

/* сводка */
function hero(){
 var cap=0,capOk=0,p=0,pOk=0,ex=0,wd=0,cnt={};
 IT.forEach(function(it,i){var r=R[i];cnt[r.v]=(cnt[r.v]||0)+1; if(it.cap)cap+=it.cap; if(r.p!==null)p+=r.p;
  if((it.cap||0)>=C.minCap){capOk+=it.cap; if(r.p!==null)pOk+=r.p;}
  if(r.v==="сократить закупку")ex+=r.ex; if(r.v==="выводить")wd+=it.cap;});
 document.getElementById("free").textContent=mln(ex+wd);
 document.getElementById("freeD").innerHTML="лишний запас <b>"+mln(ex)+"</b> у "+(cnt["сократить закупку"]||0)+" тов. · выводить <b>"+mln(wd)+"</b> у "+(cnt["выводить"]||0)+" тов.";
 document.getElementById("s1").textContent=mln(cap);
 document.getElementById("s1d").textContent="прибыль за период "+mln(p)+" · доходность портфеля "+(capOk?fmt(pOk*C.ann/capOk*100):"—")+"% "+C.bl;
 var L=locTotals(),top=L[0];
 document.getElementById("s2").textContent=top?fmt(top.share)+"%":"—";
 document.getElementById("s2d").textContent=top?("на «"+top.n+"»"+(L.length>1?" · мест хранения: "+L.length:"")):"нет данных об остатках";
 document.getElementById("s3").textContent=(cnt["развивать"]||0)+" / "+(cnt["сократить закупку"]||0)+" / "+(cnt["держать"]||0)+" / "+(cnt["выводить"]||0);
 document.getElementById("s3d").textContent="развивать / сократить закупку / держать / выводить";}

/* ползунки */
function ctrl(){
 [["pp",function(v){return "+"+fmt(v,1)+" п.п.";}],["maxd",function(v){return fmt(v)+" дн.";}],["dev",function(v){return "> "+fmt(v)+"%";}],["wd",function(v){return "< "+fmt(v)+"%";}]].forEach(function(a){
  var el=document.getElementById(a[0]),o=document.getElementById("o-"+a[0]);el.value=S[a[0]];o.textContent=a[1](S[a[0]]);
  el.oninput=function(){S[a[0]]=+el.value;o.textContent=a[1](S[a[0]]);el.parentNode.parentNode.classList.toggle("changed",S[a[0]]!==(a[0]==="pp"?0:C[a[0]]));update();};});
 document.getElementById("reset").onclick=function(){S.pp=0;S.maxd=C.maxd;S.dev=C.dev;S.wd=C.wd;document.querySelectorAll("#ctrl .changed").forEach(function(x){x.classList.remove("changed");});ctrl();update();};}

/* фильтры */
function chips(){var cnt={};R.forEach(function(r){cnt[r.v]=(cnt[r.v]||0)+1;});
 document.getElementById("chips").innerHTML=VERD.filter(function(v){return cnt[v[0]];}).map(function(v){
  return '<button class="chip" type="button" data-v="'+esc(v[0])+'" aria-pressed="'+(S.off[v[0]]?"false":"true")+'"><i style="background:var('+v[1]+')"></i>'+esc(v[0])+" <b>"+cnt[v[0]]+"</b></button>";}).join("");
 document.querySelectorAll("#chips .chip").forEach(function(b){b.onclick=function(){var v=b.dataset.v;S.off[v]=!S.off[v];update();};});}
function shown(i){return !S.off[R[i].v]&&(!S.q||IT[i].n.toLowerCase().indexOf(S.q)>=0);}

/* квадрант */
var W=760,H=420,L=58,RR=16,T=24,B=44,iw,ih,yMin,yMax,xMax;
function dims(){var el=document.getElementById("quad");W=Math.max(320,Math.min(1000,el.clientWidth||760));H=Math.max(300,Math.round(W*(W<560?0.85:0.56)));
 L=W<560?44:58;iw=W-L-RR;ih=H-T-B;}
function sl(v){return (v<0?-1:1)*Math.log10(1+Math.abs(v)/5);}
function X(v){return L+Math.max(0,Math.min(v,xMax))/xMax*iw;}
function Y(v){var s=Math.max(yMin,Math.min(sl(v),yMax));return T+(yMax-s)/(yMax-yMin)*ih;}
function scales(){var ys=[],xs=[];R.forEach(function(r){if(r.ret!==null){ys.push(sl(r.ret));xs.push(r.turns||0);}});
 ys.push(sl(S.dev*3),sl(-10)); yMax=Math.max.apply(null,ys)*1.06; yMin=Math.min.apply(null,ys)*1.08;
 var xs2=xs.slice().sort(function(a,b){return a-b;}); var q=xs2[Math.floor(.92*(xs2.length-1))]||1;
 xMax=Math.max(365/S.maxd*2,q*1.25,1);}
function quad(){
 dims();scales(); var el=document.getElementById("quad"),old=el.querySelector("svg"); if(old)old.remove();
 var s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Доходность и оборачиваемость товаров">';
 s+='<rect class="zg" x="'+L+'" y="'+T+'" width="'+iw+'" height="'+(Y(S.dev)-T)+'"/>';
 s+='<rect class="zr" x="'+L+'" y="'+Y(S.wd)+'" width="'+iw+'" height="'+(T+ih-Y(S.wd))+'"/>';
 [S.dev,S.wd].forEach(function(v){s+='<line class="thl" x1="'+L+'" x2="'+(W-RR)+'" y1="'+Y(v)+'" y2="'+Y(v)+'"/>';});
 [-100,-30,0,S.wd,S.dev,100,300,1000,3000].forEach(function(v){var y=sl(v);if(y<yMin||y>yMax)return;
  s+='<text x="'+(L-6)+'" y="'+(Y(v)+4)+'" text-anchor="end"'+((v===S.dev||v===S.wd)?' style="font-weight:700;fill:var(--ink-2)"':'')+'>'+fmt(v)+'%</text>';});
 if(yMin<0)s+='<line class="ax" x1="'+L+'" x2="'+(W-RR)+'" y1="'+Y(0)+'" y2="'+Y(0)+'"/>';
 var xs=365/S.maxd; s+='<line class="thl" x1="'+X(xs)+'" x2="'+X(xs)+'" y1="'+T+'" y2="'+(T+ih)+'"/><text x="'+(X(xs)+5)+'" y="'+(T+12)+'">запас '+S.maxd+' дн.</text>';
 s+='<path class="ax" fill="none" d="M'+L+' '+T+'V'+(T+ih)+'H'+(W-RR)+'"/>';
 for(var i=0;i<=4;i++){var v=xMax*i/4;s+='<text x="'+X(v)+'" y="'+(T+ih+17)+'" text-anchor="middle">'+fmt(v,1)+'</text>';}
 s+='<text x="'+(L+iw/2)+'" y="'+(H-6)+'" text-anchor="middle">оборотов капитала в год →</text>';
 s+='<text x="'+(W-RR-6)+'" y="'+(Y(S.dev)-7)+'" text-anchor="end" style="font-weight:700;fill:var(--good-t)">развивать ↑</text>';
 s+='<text x="'+(W-RR-6)+'" y="'+(Y(S.wd)+15)+'" text-anchor="end" style="font-weight:700;fill:var(--crit-t)">выводить ↓</text>';
 var rmax=Math.max.apply(null,IT.map(function(it){return Math.max(it.rev||0,0);}).concat([1]));
 var order=IT.map(function(_,i){return i;}).sort(function(a,b){return (IT[b].rev||0)-(IT[a].rev||0);});
 order.forEach(function(i){var r=R[i];if(r.ret===null)return;
  s+='<g class="b'+(IT[i].st==="ТЕСТ"?" t":"")+'" data-i="'+i+'" style="transform:translate('+X(r.turns||0)+'px,'+Y(r.ret)+'px)"><circle r="'+((4+Math.sqrt(Math.max(IT[i].rev,0)/rmax)*19)*Math.min(1,W/760)+1)+'"/></g>';});
 el.insertAdjacentHTML("afterbegin",s+"</svg>");
 var tip=document.getElementById("tip");
 el.querySelectorAll("g.b").forEach(function(g){var i=+g.dataset.i;
  g.addEventListener("mouseenter",function(){var r=R[i],it=IT[i];hl(i,true);
   tip.innerHTML="<b>"+esc(it.n)+"</b><br>"+esc(r.v)+" · доходность "+fmt(r.ret)+"% · запас "+fmt(r.days)+" дн.<br>капитал "+rub(it.cap)+" · прибыль "+rub(r.p);
   tip.classList.add("on");var bb=el.getBoundingClientRect(),cb=g.getBoundingClientRect();
   tip.style.left=Math.max(0,Math.min(cb.left-bb.left+cb.width/2+12,bb.width-285))+"px";tip.style.top=Math.max(0,cb.top-bb.top-12)+"px";});
  g.addEventListener("mouseleave",function(){tip.classList.remove("on");hl(i,false);});
  g.addEventListener("click",function(){open(i);});});
 paintQuad();}
function paintQuad(){document.querySelectorAll("#quad g.b").forEach(function(g){var i=+g.dataset.i,r=R[i];
 g.style.transform="translate("+X(r.turns||0)+"px,"+Y(r.ret)+"px)"; g.querySelector("circle").style.fill=col(r.v);
 g.classList.toggle("dim",!shown(i));});}
function hl(i,on){var g=document.querySelector('#quad g.b[data-i="'+i+'"]');if(g)g.classList.toggle("hi",on);
 var tr=document.querySelector('#tb tr[data-i="'+i+'"]');if(tr)tr.classList.toggle("hi",on);}

/* где лежат деньги */
function locTotals(){var tot={},all=0;IT.forEach(function(it){for(var l in it.locs){tot[l]=(tot[l]||0)+it.locs[l];all+=it.locs[l];}});
 return Object.keys(tot).map(function(l){return{n:l,v:tot[l],share:all?tot[l]/all*100:0};}).sort(function(a,b){return b.v-a.v;});}
function locs(){var L=locTotals(),mx=L.length?L[0].v:1,el=document.getElementById("locs");
 if(!L.length){el.innerHTML='<p class="small">Нет данных об остатках.</p>';return;}
 el.innerHTML=L.map(function(l){var by={};IT.forEach(function(it,i){var c=it.locs[l.n];if(c)by[R[i].v]=(by[R[i].v]||0)+c;});
  var seg=VERD.filter(function(v){return by[v[0]];}).map(function(v){return '<i title="'+esc(v[0])+": "+rub(by[v[0]])+'" style="width:'+(by[v[0]]/mx*100)+'%;background:var('+v[1]+')"></i>';}).join("");
  return '<div class="loc"><div class="h"><span>'+esc(l.n)+'</span><b>'+mln(l.v)+" · "+fmt(l.share)+'%</b></div><div class="bar">'+seg+"</div></div>";}).join("")+
  '<div class="chips" style="margin-top:14px">'+VERD.slice(0,5).map(function(v){return '<span class="small"><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:var('+v[1]+')"></i> '+esc(v[0])+"</span>";}).join(" ")+"</div>";}

/* таблица */
function table(){var rows=IT.map(function(it,i){var r=R[i];return{i:i,n:it.n,vo:VI[r.v],v:r.v,ret:r.ret,days:r.days,cap:it.cap,ex:r.ex,p:r.p,m:r.m,rev:it.rev,st:it.st};})
 .filter(function(x){return shown(x.i);}).sort(function(a,b){var x=a[S.sk],y=b[S.sk];if(x===null||x===undefined)return 1;if(y===null||y===undefined)return -1;
  if(typeof x==="string")return x.localeCompare(y,"ru")*S.sd;return (x-y)*S.sd||((b.cap||0)-(a.cap||0));});
 document.querySelector("#tb tbody").innerHTML=rows.map(function(x){
  return '<tr data-i="'+x.i+'"><td>'+esc(x.n)+'</td><td><span class="pill" style="color:'+col(x.v,2)+';background:'+col(x.v,3)+'">'+esc(x.v)+"</span></td><td"+(x.ret<0?' class="neg"':"")+">"+fmt(x.ret)+"</td><td>"+fmt(x.days)+"</td><td>"+fmt(x.cap)+"</td><td>"+fmt(x.ex)+"</td><td"+(x.p<0?' class="neg"':"")+">"+fmt(x.p)+"</td><td>"+fmt(x.m,1)+"</td><td>"+fmt(x.rev)+"</td><td"+(x.st==="ТЕСТ"?' class="test"':"")+">"+esc(x.st)+"</td></tr>";}).join("")||'<tr><td colspan="10" class="small">Ничего не найдено</td></tr>';
 document.querySelectorAll("#tb tbody tr[data-i]").forEach(function(tr){var i=+tr.dataset.i;
  tr.onmouseenter=function(){hl(i,true);};tr.onmouseleave=function(){hl(i,false);};tr.onclick=function(){open(i);};});}
document.querySelectorAll("#tb th").forEach(function(th){th.onclick=function(){var k=th.dataset.k;S.sd=(S.sk===k)?-S.sd:(k==="n"||k==="vo"||k==="st"?1:-1);S.sk=k;table();};});
document.getElementById("q").oninput=function(e){S.q=e.target.value.trim().toLowerCase();update();};

/* карточка товара */
function why(it,r){var bl=C.bl;switch(r.v){
 case "развивать":return "Доходность "+fmt(r.ret)+"% "+bl+" выше порога "+S.dev+"%, запас "+fmt(r.days)+" дн. — в пределах "+S.maxd+". Деньги в товаре работают: держать в наличии, можно наращивать.";
 case "сократить закупку":return "Товар доходный ("+fmt(r.ret)+"% "+bl+"), но запаса на "+fmt(r.days)+" дн. при пороге "+S.maxd+": лишние "+rub(r.ex)+" заморожены. Не дозаказывать, пока запас не снизится.";
 case "держать":return "Доходность "+fmt(r.ret)+"% "+bl+" — между "+S.wd+"% и "+S.dev+"%: окупается, но слабо. Пересмотреть цену, рекламу или объём закупки.";
 case "выводить":return "Доходность "+fmt(r.ret)+"% "+bl+" ниже "+S.wd+"%: деньги в товаре работают хуже депозита. Распродать остаток, не дозаказывать.";
 case "нет продаж в периоде":return "На складе "+rub(it.cap)+", а продаж за период нет. Новинка или неликвид — проверить дату прихода, прежде чем решать.";
 case "мало остатка на дату снимка":return "На дату снимка остатка почти нет — доходность не считается. Нужен снимок остатков на другую дату.";
 case "нет данных об остатке":return "В файлах остатков товара нет — доходность не посчитать. Добавить выгрузку остатков.";
 default:return "Нет себестоимости в каталоге — прибыль не посчитать. Добавить товар в каталог или в aliases.json.";}}
function wf(it,r){if(it.profit===null)return "";
 var steps=[["Выручка",it.rev,1],["Комиссия",-it.comm],["Логистика",-it.logi],["Хранение",-it.stor],["Реклама",-it.ads],["Прочее WB",-(it.other+(it.tax||0))]];
 if(it.loy)steps.push(["Компенсации WB",it.loy]); if(S.pp)steps.push(["Комиссия +"+fmt(S.pp,1)+" п.п.",-Math.max(it.rev,0)*S.pp/100]);
 steps.push(["Себестоимость",-it.cogs]); steps.push(["Прибыль",r.p,1]);
 var w=400,rh=24,lw=110,h=steps.length*rh+6,mx=Math.max(it.rev,1),x0=lw,sc=(w-lw-70)/mx,acc=0,s='<svg class="wf" viewBox="0 0 '+w+" "+h+'" width="100%">';
 steps.forEach(function(st,k){var y=k*rh+3,v=st[1],a,b,c;
  if(st[2]){a=x0;b=x0+Math.max(v,0)*sc;c=v>=0?"var(--hold)":"var(--crit)";if(k===0)acc=v;}
  else{var n=acc+v;a=x0+Math.min(acc,n)*sc;b=x0+Math.max(acc,n)*sc;c=v<0?"var(--crit)":"var(--good)";acc=n;}
  s+='<text class="lab" x="0" y="'+(y+15)+'">'+esc(st[0])+'</text><rect x="'+Math.min(a,b)+'" y="'+(y+3)+'" width="'+Math.max(Math.abs(b-a),1.5)+'" height="'+(rh-8)+'" rx="3" fill="'+c+'" fill-opacity="'+(st[2]?.9:.75)+'"/>'+
   '<text x="'+(Math.max(a,b)+5)+'" y="'+(y+15)+'">'+(v<0?"−":"")+fmt(Math.abs(v))+"</text>";});
 return s+"</svg>";}
function open(i){S.sel=i;var it=IT[i],r=R[i];
 var locs=Object.keys(it.locs).sort(function(a,b){return it.locs[b]-it.locs[a];});
 document.getElementById("dc").innerHTML='<span class="pill" style="color:'+col(r.v,2)+';background:'+col(r.v,3)+'">'+esc(r.v)+"</span><h3>"+esc(it.n)+"</h3>"+
  '<div class="why">'+esc(why(it,r))+"</div>"+
  '<div class="kp"><div><b>'+fmt(r.ret)+'%</b><span>доходность, '+C.bl+'</span></div><div><b>'+fmt(r.days)+'</b><span>запас, дней продаж</span></div>'+
  '<div><b>'+rub(it.cap)+'</b><span>деньги в товаре</span></div><div><b>'+rub(r.ex)+'</b><span>лишний запас (сверх '+S.maxd+' дн.)</span></div>'+
  '<div><b>'+rub(r.p)+'</b><span>прибыль за период</span></div><div><b>'+fmt(it.sold)+'</b><span>продано, шт</span></div></div>'+
  (it.profit!==null?'<h2 style="margin-top:16px">От выручки к прибыли</h2><div class="small">₽ за период</div>'+wf(it,r):"")+
  (locs.length?'<h2 style="margin-top:16px">Где лежит</h2>'+locs.map(function(l){return '<div class="loc"><div class="h"><span>'+esc(l)+"</span><b>"+rub(it.locs[l])+'</b></div><div class="bar"><i style="width:'+(it.locs[l]/it.cap*100)+'%;background:var(--hold)"></i></div></div>';}).join(""):"")+
  (it.st==="ТЕСТ"?'<p class="small test">Остаток тестовый — подставлен программой для проверки.</p>':"");
 document.getElementById("drawer").classList.add("on");document.getElementById("drawer").setAttribute("aria-hidden","false");document.getElementById("scrim").classList.add("on");}
function close(){S.sel=null;document.getElementById("drawer").classList.remove("on");document.getElementById("drawer").setAttribute("aria-hidden","true");document.getElementById("scrim").classList.remove("on");}
document.getElementById("close").onclick=close;document.getElementById("scrim").onclick=close;
document.addEventListener("keydown",function(e){if(e.key==="Escape")close();});

/* тема */
(function(){var root=document.documentElement,saved=null;try{saved=localStorage.getItem("wbcap-theme");}catch(e){}
 if(saved)root.setAttribute("data-theme",saved);
 document.getElementById("theme").onclick=function(){var dark=root.getAttribute("data-theme")?root.getAttribute("data-theme")==="dark":matchMedia("(prefers-color-scheme: dark)").matches;
  var t=dark?"light":"dark";root.setAttribute("data-theme",t);try{localStorage.setItem("wbcap-theme",t);}catch(e){}};})();

function update(){recalc();hero();chips();scales();quad();locs();table();if(S.sel!==null)open(S.sel);}
/* самопроверка: при порогах по умолчанию вердикты страницы = вердикты Python */
recalc();var bad=IT.filter(function(it,i){return R[i].v!==it.v;});
if(bad.length){console.warn("Расхождение вердиктов JS/Python:",bad.map(function(x){return x.n;}));
 document.getElementById("warns").insertAdjacentHTML("beforeend",'<div class="warn">⚠ Пересчёт в браузере разошёлся с расчётом программы у '+bad.length+" товаров — опирайтесь на Excel.</div>");}
window.__selfcheck={mismatch:bad.length};
head();ctrl();update();
var rz;window.addEventListener("resize",function(){clearTimeout(rz);rz=setTimeout(function(){quad();},150);});
</script></body></html>
"""
