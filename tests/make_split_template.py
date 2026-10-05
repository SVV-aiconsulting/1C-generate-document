# -*- coding: utf-8 -*-
"""
Создает тестовый шаблон, в котором поля {{...}} разорваны XML-разметкой так, как это делает Word
(отдельные фрагменты w:r, пометки проверки орфографии, разрыв даже между фигурными скобками).
Используется в tests/run_tests.py.
"""
import re
import sys
import zipfile

SRC, DST = sys.argv[1], sys.argv[2]

RUN = '</w:t></w:r><w:proofErr w:type="spellStart"/><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">'


def split(match):
    text = match.group(0)
    # {{Договор.Номер}} -> {  {Дог  овор.Ном  ер}  }
    inner = text[2:-2]
    middle = len(inner) // 2
    return "{" + RUN + "{" + inner[:3] + RUN + inner[3:middle] + RUN + inner[middle:] + "}" + RUN + "}"


with zipfile.ZipFile(SRC) as z:
    files = {n: z.read(n) for n in z.namelist()}
xml = files["word/document.xml"].decode("utf-8")
xml, count = re.subn(r"\{\{[^{}<]+\}\}", split, xml)
files["word/document.xml"] = xml.encode("utf-8")
with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
    for name, data in files.items():
        z.writestr(name, data)
print("Разорвано полей:", count)
