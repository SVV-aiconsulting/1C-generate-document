# -*- coding: utf-8 -*-
"""
Отрисовка документа Word в картинки для проверки верстки (для разработчика).

Word запускается в фоне (невидимо) только для экспорта в PDF, документ открывается
только для чтения и не сохраняется. Затем страницы PDF сохраняются в PNG.

Запуск: python tools/render_docx.py <файл.docx> <каталог вывода>
Нужны: Microsoft Word, pip install pymupdf pywin32 (или PowerShell для COM).
"""
import os
import subprocess
import sys

import pymupdf


def docx_to_pdf(docx, pdf):
    script = r'''
$ErrorActionPreference = "Stop"
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open("%s", $false, $true)
    $doc.ExportAsFixedFormat("%s", 17)
    $doc.Close(0)
} finally {
    $word.Quit()
}
''' % (os.path.abspath(docx), os.path.abspath(pdf))
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)


def main():
    docx, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    pdf = os.path.join(out, os.path.splitext(os.path.basename(docx))[0] + ".pdf")
    docx_to_pdf(docx, pdf)
    doc = pymupdf.open(pdf)
    print("Страниц:", doc.page_count)
    for i, page in enumerate(doc):
        png = os.path.join(out, "page%d.png" % (i + 1))
        page.get_pixmap(dpi=70).save(png)
        print(png)


if __name__ == "__main__":
    main()
