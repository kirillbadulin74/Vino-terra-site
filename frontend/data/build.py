# -*- coding: utf-8 -*-
"""
Сборка data/wine-data.js из читаемых исходников data/*.json.

Порядок работы с данными сайта:
  1. Правите data/academy.json / russia.json / world.json / islands.json
  2. Запускаете:  python data/build.py
  3. Скрипт собирает их в data/wine-data.js (минифицированный однострочник)

Обратная операция (если wine-data.js правился скриптом напрямую):
  python data/build.py --unpack   # пересоздаёт *.json из wine-data.js
"""
import json, os, sys

DIR = os.path.dirname(os.path.abspath(__file__))
PARTS = ["academy", "russia", "world", "islands"]
OUT = os.path.join(DIR, "wine-data.js")


def read_out():
    src = open(OUT, encoding="utf-8").read()
    return json.loads(src.split("=", 1)[1].rstrip().rstrip(";"))


def build():
    data = {}
    for name in PARTS:
        with open(os.path.join(DIR, name + ".json"), encoding="utf-8") as f:
            data[name] = json.load(f)
    js = "window.WINE = " + json.dumps(data, ensure_ascii=False, separators=(", ", ": ")) + ";"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(js)
    print("OK: wine-data.js rebuilt (%d KB)" % (len(js.encode("utf-8")) // 1024))


def unpack():
    data = read_out()
    for name in PARTS:
        with open(os.path.join(DIR, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(data[name], f, ensure_ascii=False, indent=2)
            f.write("\n")
    print("OK: %s regenerated from wine-data.js" % ", ".join(n + ".json" for n in PARTS))


if __name__ == "__main__":
    unpack() if "--unpack" in sys.argv else build()
