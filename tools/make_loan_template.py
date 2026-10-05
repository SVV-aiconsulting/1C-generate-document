# -*- coding: utf-8 -*-
"""
Создаёт шаблон «Договор процентного займа» из образца в папке «Образцы».

Желтые (highlight) фрагменты образца заменяются полями вида {{Имя.Поля}}.
Подсветка из шаблона убирается, форматирование (жирность, размер) сохраняется.

Запуск:  python tools/make_loan_template.py
Результат: src/templates/ДоговорЗайма.docx
"""
import os
import re
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Образец договора (с желтыми выделениями изменяемых мест) - первый .docx в папке «Образцы».
# Папка не публикуется в репозитории: в образце реальные реквизиты.
SRC = sorted(__import__("glob").glob(os.path.join(ROOT, "Образцы", "*.docx")))[0]
DST = os.path.join(ROOT, "src", "templates", "ДоговорЗайма.docx")

# Номер абзаца (по порядку <w:p> в document.xml) -> список замен для групп
# подряд идущих выделенных фрагментов (по порядку слева направо).
# None  - оставить группу как есть (только снять подсветку).
# "\t"  внутри текста превращается в табуляцию.
REPLACEMENTS = {
    1: ["ДОГОВОР № {{Договор.Номер}}"],
    2: ["процентного займа"],
    6: [
        "{{Организация.Наименование}}, в лице {{Организация.РуководительДолжностьРП}} "
        "{{Организация.РуководительФИОРП}},",
        "{{Организация.Действующего}} на основании {{Организация.ОснованиеПолномочий}},",
        "{{Контрагент.Наименование}}, в лице {{Контрагент.РуководительДолжностьРП}} "
        "{{Контрагент.РуководительФИОРП}}, {{Контрагент.Действующего}} на основании "
        "{{Контрагент.ОснованиеПолномочий}},",
    ],
    9: ["{{Сумма.Полностью}},"],
    10: ["{{Договор.Ставка}} %"],
    13: ["{{Договор.ДатаВозврата}}"],
}

# Абзац «г. Мурманск .... 28 апреля 2026 г.» заменяется целиком (см. place_date_paragraph).
PLACE_DATE_PARAGRAPH = 4
# Абзацы, которые должны держаться вместе с таблицей реквизитов (конец раздела 8 и заголовок 9).
KEEP_WITH_NEXT = [46, 47, 48, 49]
# Абзацы образца с реквизитами сторон (от «Займодавец:» до подписи заемщика) заменяются таблицей.
REQUISITES_FROM, REQUISITES_TO = 50, 70

# Ширина текста страницы образца: 11906 - 1418 (левое поле) - 707 (правое поле).
TEXT_WIDTH = 9781
TABLE_FONT = 22  # 11 пт в таблице реквизитов (основной текст - 12 пт)

HL_RE = re.compile(r'<w:highlight [^>]*/>')
RUN_RE = re.compile(r'<w:r[ >].*?</w:r>|<w:proofErr [^>]*/>|<w:bookmark(?:Start|End) [^>]*/>', re.S)


def make_runs(rpr, text):
    parts = text.split("\t")
    out = []
    for i, part in enumerate(parts):
        if i > 0:
            out.append("<w:r>%s<w:tab/></w:r>" % rpr)
        if part:
            out.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(part)))
    return "".join(out)


def process_paragraph(p, repl):
    """Заменяет группы выделенных прогонов в абзаце."""
    tokens = []  # (text, is_highlighted_run)
    pos = 0
    for m in RUN_RE.finditer(p):
        if m.start() > pos:
            tokens.append((p[pos:m.start()], None))
        tok = m.group(0)
        if tok.startswith("<w:r"):
            tokens.append((tok, "w:highlight" in tok and "<w:rPr>" in tok))
        else:
            tokens.append((tok, "neutral"))  # proofErr/bookmark - не разрывают группу
        pos = m.end()
    tokens.append((p[pos:], None))

    out = []
    groups = []
    cur = None
    for tok, hl in tokens:
        if hl is True:
            if cur is None:
                cur = []
                groups.append(cur)
                out.append(cur)
            cur.append(tok)
        elif hl == "neutral" and cur is not None:
            continue  # выбрасываем proofErr внутри группы
        else:
            cur = None
            out.append(tok)

    if len(groups) != len(repl):
        raise SystemExit("Абзац: найдено групп %d, замен %d\n%s" % (len(groups), len(repl), p[:300]))

    gi = 0
    res = []
    for item in out:
        if isinstance(item, list):
            new_text = repl[gi]
            gi += 1
            rpr_m = re.search(r'<w:rPr>.*?</w:rPr>', item[0], re.S)
            rpr = HL_RE.sub("", rpr_m.group(0)) if rpr_m else ""
            if new_text is None:
                res.append(HL_RE.sub("", "".join(item)))
            else:
                res.append(make_runs(rpr, new_text))
        else:
            res.append(item)
    return "".join(res)


def run(text, size=24, bold=False):
    rpr = "<w:rPr>%s<w:sz w:val=\"%d\"/><w:szCs w:val=\"%d\"/></w:rPr>" % ("<w:b/><w:bCs/>" if bold else "", size, size)
    return make_runs(rpr, text)


def paragraph(text, size=TABLE_FONT, bold=False, keep_next=False, align=None):
    ppr = "<w:pPr>%s<w:spacing w:before=\"0\" w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/>%s"           "<w:rPr><w:sz w:val=\"%d\"/><w:szCs w:val=\"%d\"/></w:rPr></w:pPr>" % (
              "<w:keepNext/>" if keep_next else "", '<w:jc w:val="%s"/>' % align if align else "", size, size)
    return "<w:p>%s%s</w:p>" % (ppr, run(text, size, bold) if text else "")


def place_date_paragraph():
    """Место и дата в одной строке: дата прижата к правому полю табуляцией (не переносится)."""
    ppr = ('<w:pPr><w:tabs><w:tab w:val="right" w:pos="%d"/></w:tabs>'
           '<w:rPr><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:pPr>' % TEXT_WIDTH)
    return "<w:p>%s%s%s%s</w:p>" % (ppr, run("{{Договор.Место}}"), run("	"), run("{{Договор.Дата}}", bold=True))


def side_cells(side):
    """Содержимое ячеек таблицы реквизитов для стороны: Организация или Контрагент."""
    title = "Заимодавец:" if side == "Организация" else "Заемщик:"
    p = side + "."
    head = paragraph(title, bold=True, keep_next=True)
    requisites = "".join([
        paragraph("{{%sНаименование}}" % p, bold=True, keep_next=True),
        paragraph("ИНН {{%sИНН}} {{%sКПП|ПОДПИСЬ:КПП}}" % (p, p), keep_next=True),
        paragraph("ОГРН {{%sОГРН}} {{%sОКПО|ПОДПИСЬ:ОКПО}}" % (p, p), keep_next=True),
        # Фактический адрес выводится с новой строки только если он заполнен (без пустой строки).
        paragraph("Юридический адрес: {{%sЮридическийАдрес}}{{%sФактическийАдрес|ПОДПИСЬ:Фактический адрес:|НОВАЯСТРОКА}}"
                  % (p, p), keep_next=True),
        paragraph("Р/счет {{%sРасчетныйСчет}}" % p, keep_next=True),
        paragraph("Банк: {{%sБанк}}" % p, keep_next=True),
        paragraph("К/счет {{%sКоррСчет}}" % p, keep_next=True),
        paragraph("БИК {{%sБИК}}" % p, keep_next=True),
        paragraph("", keep_next=True),
    ])
    signature = "".join([
        paragraph("{{%sРуководительДолжность}}" % p, keep_next=True),
        paragraph("", keep_next=True),
        paragraph("________________ {{%sРуководительИнициалыФамилия}}" % p),
    ])
    return head, requisites, signature


def requisites_table():
    """Раздел 9: таблица без рамок, 2 колонки (Заимодавец / Заемщик) x 3 строки
    (стороны, реквизиты, подписи). Строки не разрываются между страницами."""
    left = side_cells("Организация")
    right = side_cells("Контрагент")
    col1 = TEXT_WIDTH // 2
    col2 = TEXT_WIDTH - col1
    borders = "".join('<w:%s w:val="nil"/>' % b for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
    rows = []
    for i in range(3):
        cells = "".join('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr>%s</w:tc>' % (w, c[i])
                        for w, c in ((col1, left), (col2, right)))
        rows.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>%s</w:tr>' % cells)
    return ('<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
            '<w:tblBorders>%s</w:tblBorders><w:tblCellMar><w:left w:w="0" w:type="dxa"/>'
            '<w:right w:w="170" w:type="dxa"/></w:tblCellMar><w:tblLook w:val="0000"/></w:tblPr>'
            '<w:tblGrid><w:gridCol w:w="%d"/><w:gridCol w:w="%d"/></w:tblGrid>%s</w:tbl>'
            % (TEXT_WIDTH, borders, col1, col2, "".join(rows))) + paragraph("", size=4)


def main():
    with zipfile.ZipFile(SRC) as z:
        files = {n: z.read(n) for n in z.namelist()}
    xml = files["word/document.xml"].decode("utf-8")

    paras = list(re.finditer(r'<w:p[ >].*?</w:p>', xml, re.S))
    pieces = []
    last = 0
    for i, m in enumerate(paras):
        pieces.append(xml[last:m.start()])
        p = m.group(0)
        if REQUISITES_FROM <= i <= REQUISITES_TO:
            if i == REQUISITES_FROM:
                pieces.append(requisites_table())
            last = m.end()
            continue
        if i == PLACE_DATE_PARAGRAPH:
            p = place_date_paragraph()
        elif i in REPLACEMENTS:
            p = process_paragraph(p, REPLACEMENTS[i])
        p = HL_RE.sub("", p)  # подсветка в свойствах абзаца
        if i in KEEP_WITH_NEXT and "<w:keepNext/>" not in p:
            p = p.replace("<w:pPr>", "<w:pPr><w:keepNext/>", 1) if "<w:pPr>" in p else p.replace(">", "><w:pPr><w:keepNext/></w:pPr>", 1)
        pieces.append(p)
        last = m.end()
    pieces.append(xml[last:])
    xml = "".join(pieces)

    left = re.findall(r'w:highlight|<w:shd ', xml)
    if left:
        raise SystemExit("Ошибка: в шаблоне осталась цветовая подсветка (%d)" % len(left))
    from xml.dom import minidom
    minidom.parseString(xml.encode("utf-8"))  # проверка корректности XML
    files["word/document.xml"] = xml.encode("utf-8")

    # Служебные свойства документа образца (автор, компания, даты печати) в шаблон не переносим.
    core = files["docProps/core.xml"].decode("utf-8")
    core = re.sub(r"<dc:creator>.*?</dc:creator>", "<dc:creator>Формирование документов по шаблону</dc:creator>", core)
    core = re.sub(r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>", "<cp:lastModifiedBy>Формирование документов по шаблону</cp:lastModifiedBy>", core)
    core = re.sub(r"<cp:lastPrinted>.*?</cp:lastPrinted>", "", core)
    files["docProps/core.xml"] = core.encode("utf-8")
    app = files["docProps/app.xml"].decode("utf-8")
    app = re.sub(r"<Company>.*?</Company>", "<Company></Company>", app)
    app = re.sub(r"<Manager>.*?</Manager>", "", app)
    files["docProps/app.xml"] = app.encode("utf-8")

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in files.items():
            z.writestr(n, data)

    fields = sorted(set(re.findall(r'\{\{([^}]+)\}\}', xml)))
    print("Шаблон создан:", DST)
    print("Поля (%d):" % len(fields))
    for f in fields:
        print("  ", f)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
