# -*- coding: utf-8 -*-
"""
Предпросмотр шаблона без 1С (для разработчика): подставляет в шаблон .docx тестовые данные
по тем же правилам, что и расширение (поля {{...}}, модификаторы ВРЕГ и ПОДПИСЬ:текст),
и сохраняет результат. Используется вместе с tools/render_docx.py для проверки верстки.

Запуск: python tools/preview_template.py <шаблон.docx> <данные.json> <результат.docx>
"""
import json
import re
import sys
import zipfile
from xml.sax.saxutils import escape


def value(expr, data):
    parts = [p.strip() for p in expr.split("|")]
    val = data.get(parts[0], "")
    for mod in parts[1:]:
        if mod.upper() == "ВРЕГ":
            val = val.upper()
        elif mod.upper().startswith("ПОДПИСЬ:"):
            val = (mod[8:].strip() + " " + val) if val.strip() else ""
        elif mod.upper() == "НОВАЯСТРОКА":
            val = ("\n" + val) if val.strip() else ""
    return val


def main():
    template, data_file, result = sys.argv[1:4]
    data = json.load(open(data_file, encoding="utf-8"))
    with zipfile.ZipFile(template) as z:
        files = {n: z.read(n) for n in z.namelist()}
    xml = files["word/document.xml"].decode("utf-8")
    missing = set()

    def repl(m):
        name = m.group(1).split("|")[0].strip()
        if name not in data:
            missing.add(name)
        return escape(value(m.group(1), data)).replace("\n", '</w:t><w:br/><w:t xml:space="preserve">')

    xml = re.sub(r"\{\{([^{}<]+)\}\}", repl, xml)
    files["word/document.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    if missing:
        print("Нет тестовых данных для полей:", ", ".join(sorted(missing)))
    print("Готово:", result)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
