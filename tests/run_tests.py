# -*- coding: utf-8 -*-
"""
Интеграционный тест на копии базы (для разработчика).

  1. Собирает расширение и применяет его к тестовой базе (tools/build.py --cfe --update-db).
  2. Собирает служебную обработку tests/epf/ШД_Тест.xml -> build/ШД_Тест.epf.
  3. Запускает 1С:Предприятие с этой обработкой: она формирует документы по всем шаблонам
     для нескольких платежных поручений и пишет протокол в build/test_out/test_log.txt.

Параметры базы берутся из tools/build.local.json.
"""
import json
import os
import shutil
import subprocess
import sys
import xml.dom.minidom
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with open(os.path.join(ROOT, "tools", "build.local.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    auth = ["/N", cfg["user"]] + (["/P", cfg["password"]] if cfg.get("password") else [])

    if "--no-build" not in sys.argv:
        code = subprocess.call([sys.executable, os.path.join(ROOT, "tools", "build.py"), "--cfe", "--update-db"],
                               stdout=subprocess.DEVNULL)
        if code:
            raise SystemExit("Сборка расширения не удалась, см. build/load.log")

    epf = os.path.join(ROOT, "build", "ШД_Тест.epf")
    code = subprocess.call([cfg["v8"], "DESIGNER", "/F", cfg["ib"]] + auth + [
        "/LoadExternalDataProcessorOrReportFromFiles", os.path.join(ROOT, "tests", "epf", "ШД_Тест.xml"), epf,
        "/Out", os.path.join(ROOT, "build", "epf.log"), "/DisableStartupDialogs", "/DisableStartupMessages"])
    if code:
        raise SystemExit("Сборка тестовой обработки не удалась, см. build/epf.log")

    out = os.path.join(ROOT, "build", "test_out")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    subprocess.check_call([sys.executable, os.path.join(ROOT, "tests", "make_split_template.py"),
                           os.path.join(ROOT, "src", "templates", "ДоговорЗайма.docx"),
                           os.path.join(out, "split_template.docx")])
    log = os.path.join(out, "test_log.txt")
    for attempt in range(2):
        proc = subprocess.Popen([cfg["v8"], "ENTERPRISE", "/F", cfg["ib"]] + auth + [
            "/Execute", epf, "/C", out, "/DisableStartupDialogs", "/DisableStartupMessages",
            # Только для этого запуска тестовой копии: без предупреждения об открытии обработки из файла.
            "/DisableUnsafeActionProtection", ".*ТестоваяБаза.*",
            "/Out", os.path.join(ROOT, "build", "enterprise.log")])
        # Платформа спрашивает подтверждение при открытии измененной тестовой обработки из файла
        # («Предупреждение безопасности»). Подтверждаем только это окно и только для нашего процесса.
        helper = os.path.join(ROOT, "tests", "ui_helper.ps1")
        for _ in range(30):
            try:
                proc.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", helper,
                                "-ProcId", str(proc.pid), "-Action", "confirmsecurity"], capture_output=True)
        else:
            proc.kill()
            raise SystemExit("1С:Предприятие не завершилось за 5 минут (возможно, открыто окно с вопросом)")
        if not os.path.exists(log):
            raise SystemExit("Протокол теста не создан, см. build/enterprise.log")
        with open(log, encoding="utf-8-sig") as f:
            if "ПЕРЕЗАПУСК" not in f.read():
                break

    if not os.path.exists(log):
        raise SystemExit("Протокол теста не создан")
    with open(log, encoding="utf-8-sig") as f:
        text = f.read()
    print("\n".join(l for l in text.splitlines() if not l.startswith("Расширение: EF_")))
    print("\nФайлы:", ", ".join(n for n in os.listdir(out) if n.endswith(".docx")))

    # Сформированные файлы должны быть корректными документами Word без незаполненных полей.
    failed = "ОШИБКА" in text
    for name in os.listdir(out):
        if name.endswith(".docx") and name != "split_template.docx":
            with zipfile.ZipFile(os.path.join(out, name)) as z:
                body = z.read("word/document.xml")
            xml.dom.minidom.parseString(body)
            if b"{{" in body or b"}}" in body:
                failed = True
                print("ОШИБКА: незаполненные поля в", name)
    print("Проверка XML сформированных файлов выполнена")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
