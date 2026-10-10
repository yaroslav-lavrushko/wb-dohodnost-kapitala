"""Проверка на утечки перед публикацией: реквизиты, контакты, личные слова.

    python scripts/check_leaks.py [--history]

Общие шаблоны — здесь. Личный список запретных слов (бренды, юрлица, номера кабинетов) держите в файле
.leakwords в корне репозитория: он в .gitignore и в репозиторий не попадает. С --history проверяется
вся история git, а не только текущие файлы. Код выхода 1 — найдено.
"""
from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "ИНН/ОГРН": re.compile(r"(ИНН|ОГРН|КПП)\s*:?\s*\d{9,15}", re.I),
    "юрлицо": re.compile(r"\b(ООО|ОАО|ЗАО|АО|ИП)\s+[«\"“]?[А-ЯЁA-Z][а-яёa-z]+", re.U),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "телефон": re.compile(r"(?<![\d.,])(\+7|\+375|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?![\d.])"),
    "supplier_id": re.compile(r"supplier_id\s*[:=]?\s*\d{5,}", re.I),
}
ALLOW = {"e-mail": {"noreply@anthropic.com"}}


def words() -> list[str]:
    f = ROOT / ".leakwords"
    return [w.strip().lower() for w in f.read_text(encoding="utf-8").splitlines() if w.strip()] if f.exists() else []


def texts(name: str, data: bytes):
    if name.endswith(".xlsx"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as z:
                for n in z.namelist():
                    if n.endswith(".xml"):
                        yield z.read(n).decode("utf-8", "ignore")
        except zipfile.BadZipFile:
            return
    elif not name.endswith((".png", ".jpg", ".whl", ".zip", ".gif")):
        yield data.decode("utf-8", "ignore")


def scan(name: str, data: bytes, ws: list[str]) -> list[str]:
    found = []
    for t in texts(name, data):
        tl = t.lower()
        for label, rx in PATTERNS.items():
            for m in rx.finditer(t):
                if m.group(0) not in ALLOW.get(label, set()):
                    found.append(f"{name}: {label}: {m.group(0)[:60]!r}")
        for w in ws:
            if w in tl or w in name.lower():
                found.append(f"{name}: запретное слово из .leakwords")
    return found


def main() -> int:
    ws = words()
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True).stdout.split("\0")
    found = []
    for f in filter(None, files):
        if f in ("scripts/check_leaks.py",):
            continue
        found += scan(f, (ROOT / f).read_bytes(), ws)
    if "--history" in sys.argv:
        objs = subprocess.run(["git", "-c", "core.quotepath=off", "rev-list", "--objects", "--all"], cwd=ROOT,
                              capture_output=True, text=True).stdout
        for line in objs.splitlines():
            sha, _, path = line.partition(" ")
            if not path or path == "scripts/check_leaks.py":
                continue
            kind = subprocess.run(["git", "cat-file", "-t", sha], cwd=ROOT, capture_output=True, text=True).stdout.strip()
            if kind == "blob":
                data = subprocess.run(["git", "cat-file", "-p", sha], cwd=ROOT, capture_output=True).stdout
                found += [f"[история] {x}" for x in scan(path, data, ws)]
        msgs = subprocess.run(["git", "log", "--all", "--format=%B"], cwd=ROOT, capture_output=True, text=True).stdout
        found += [f"[сообщения коммитов] {x}" for x in scan("log.txt", msgs.encode(), ws)]
    for x in sorted(set(found)):
        print("⚠", x)
    print("утечек не найдено" if not found else f"найдено: {len(set(found))}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
