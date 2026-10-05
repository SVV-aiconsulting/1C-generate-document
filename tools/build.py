# -*- coding: utf-8 -*-
"""
Сборка расширения 1С «Формирование документов по шаблону» (ШаблоныДокументов.cfe).

Что делает:
  1. Генерирует XML-описание метаданных расширения (формат выгрузки конфигуратора 8.3/8.5)
     в каталог build/extension. UUID объектов детерминированные (uuid5 от имени объекта),
     поэтому при повторной сборке объекты не пересоздаются и данные в базе не теряются.
  2. Копирует модули и формы из src/extension.
  3. Встраивает поставляемые шаблоны из src/templates (описание в src/templates/templates.json).
  4. (опционально) Загружает расширение в информационную базу через конфигуратор
     и выгружает файл dist/ШаблоныДокументов.cfe.

Запуск:
  python tools/build.py                       # только сгенерировать XML
  python tools/build.py --cfe                 # + собрать .cfe (нужна база с БП, см. параметры)
  python tools/build.py --cfe --ib "путь к базе" --user "Имя" [--password "..."] [--v8 "путь к 1cv8.exe"]

Параметры по умолчанию можно задать в tools/build.local.json:
  {"ib": "...", "user": "...", "password": "", "v8": "..."}
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "extension")
TEMPLATES = os.path.join(ROOT, "src", "templates")
OUT = os.path.join(ROOT, "build", "extension")
DIST = os.path.join(ROOT, "dist")

EXT_NAME = "ШаблоныДокументов"
EXT_SYNONYM = "Формирование документов по шаблону"
EXT_VERSION = "1.0.0"
PREFIX = "ШД_"
COMPAT = "Version8_3_27"  # не выше режима совместимости БП 3.0

# UUID объектов основной конфигурации БП 3.0 (одинаковы во всех базах типовой конфигурации).
BASE_UUIDS = {
    "Language.Русский": "db4a9ccb-9ef5-4b3c-8577-b6fe5db1b62e",
    "Document.ПлатежноеПоручение": "1cc042b5-ff65-4629-ae4b-c0bb288ab991",
    "Role.БазовыеПраваБП": "b133d9e7-c8bc-4fd8-8735-8738a785b15b",
}

NAMESPACE = uuid.UUID("3b8f2c71-5d4e-4a6b-9c0d-1e2f3a4b5c6d")


def uid(key):
    return str(uuid.uuid5(NAMESPACE, key))


NS = ('xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" '
      'xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" '
      'xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" '
      'xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" '
      'xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" '
      'xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" '
      'xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" '
      'xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
      'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
      'version="2.21"')


# ---------------------------------------------------------------------------------------------
# Вспомогательные генераторы XML
# ---------------------------------------------------------------------------------------------

def loc(text):
    if not text:
        return ""
    return ("<v8:item><v8:lang>ru</v8:lang><v8:content>%s</v8:content></v8:item>" % escape(text))


def synonym(text, tag="Synonym"):
    return "<%s>%s</%s>" % (tag, loc(text), tag) if text else "<%s/>" % tag


def md_file(body):
    return '<?xml version="1.0" encoding="UTF-8"?>\n<MetaDataObject %s>\n%s\n</MetaDataObject>\n' % (NS, body)


def write(rel_path, content):
    path = os.path.join(OUT, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def generated_types(kind_prefix, name, categories):
    items = []
    for cat_name, category in categories:
        full = "%s%s.%s" % (cat_name, "", name) if "." not in cat_name else cat_name
        key = "%s.%s" % (cat_name, name)
        items.append(
            '<xr:GeneratedType name="%s.%s" category="%s"><xr:TypeId>%s</xr:TypeId><xr:ValueId>%s</xr:ValueId></xr:GeneratedType>'
            % (cat_name, name, category, uid(key + ".TypeId"), uid(key + ".ValueId")))
    return "<InternalInfo>%s</InternalInfo>" % "".join(items)


def type_xml(t):
    """t: 'string:150', 'string', 'bool', 'number:15.2', 'storage', 'cfg:...'"""
    if t.startswith("string"):
        length = t.split(":")[1] if ":" in t else "0"
        return ("<Type><v8:Type>xs:string</v8:Type><v8:StringQualifiers><v8:Length>%s</v8:Length>"
                "<v8:AllowedLength>Variable</v8:AllowedLength></v8:StringQualifiers></Type>" % length)
    if t == "bool":
        return "<Type><v8:Type>xs:boolean</v8:Type></Type>"
    if t == "storage":
        return "<Type><v8:Type>v8:ValueStorage</v8:Type></Type>"
    if t.startswith("cfg:"):
        return "<Type><v8:Type>%s</v8:Type></Type>" % t
    raise ValueError(t)


def attribute_xml(tag, key, name, title, t, multiline=False, extra="", before_indexing=""):
    return ("<%s uuid=\"%s\"><Properties><Name>%s</Name>%s<Comment/>%s"
            "<PasswordMode>false</PasswordMode><Format/><EditFormat/><ToolTip/><MarkNegatives>false</MarkNegatives>"
            "<Mask/><MultiLine>%s</MultiLine><ExtendedEdit>%s</ExtendedEdit>"
            "<MinValue xsi:nil=\"true\"/><MaxValue xsi:nil=\"true\"/>%s"
            "<FillChecking>DontCheck</FillChecking><ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>"
            "<ChoiceParameterLinks/><ChoiceParameters/><QuickChoice>Auto</QuickChoice><CreateOnInput>Auto</CreateOnInput>"
            "<ChoiceForm/><LinkByType/><ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>%s"
            "<Indexing>DontIndex</Indexing><FullTextSearch>Use</FullTextSearch><DataHistory>Use</DataHistory>"
            "</Properties></%s>"
            % (tag, uid(key), name, synonym(title), type_xml(t),
               str(multiline).lower(), str(multiline).lower(), extra, before_indexing, tag))


# ---------------------------------------------------------------------------------------------
# Объекты расширения
# ---------------------------------------------------------------------------------------------

def gen_configuration(child_objects):
    class_ids = ["9cd510cd-abfc-11d4-9434-004095e12fc7", "9fcd25a0-4822-11d4-9414-008048da11f9",
                 "e3687481-0a87-462c-a166-9f34594f9bba", "9de14907-ec23-4a07-96f0-85521cb6b53b",
                 "51f2d5d8-ea4d-4064-8892-82951750031e", "e68182ea-4237-4383-967f-90c1e3370bc7",
                 "fb282519-d103-4dd3-bc12-cb271d631dfc"]
    contained = "".join(
        "<xr:ContainedObject><xr:ClassId>%s</xr:ClassId><xr:ObjectId>%s</xr:ObjectId></xr:ContainedObject>"
        % (c, uid("Configuration.Contained." + c)) for c in class_ids)
    children = "".join("<%s>%s</%s>" % (kind, name, kind) for kind, name in child_objects)
    body = """	<Configuration uuid="%s">
		<InternalInfo>%s</InternalInfo>
		<Properties>
			<ObjectBelonging>Adopted</ObjectBelonging>
			<Name>%s</Name>
			%s
			<Comment/>
			<ConfigurationExtensionPurpose>Customization</ConfigurationExtensionPurpose>
			<KeepMappingToExtendedConfigurationObjectsByIDs>false</KeepMappingToExtendedConfigurationObjectsByIDs>
			<NamePrefix>%s</NamePrefix>
			<ConfigurationExtensionCompatibilityMode>%s</ConfigurationExtensionCompatibilityMode>
			<DefaultRunMode>ManagedApplication</DefaultRunMode>
			<ScriptVariant>Russian</ScriptVariant>
			<Vendor>AI Consulting</Vendor>
			<Version>%s</Version>
			<DefaultLanguage>Language.Русский</DefaultLanguage>
			%s
			<InterfaceCompatibilityMode>TaxiEnableVersion8_2</InterfaceCompatibilityMode>
			<CompatibilityMode>%s</CompatibilityMode>
		</Properties>
		<ChildObjects>%s</ChildObjects>
	</Configuration>""" % (uid("Configuration"), contained, EXT_NAME, synonym(EXT_SYNONYM), PREFIX, COMPAT,
                           EXT_VERSION,
                           synonym("Формирование документов (договоров и др.) по шаблонам Word на основании платежных поручений",
                                   "BriefInformation"),
                           COMPAT, children)
    write("Configuration.xml", md_file(body))


def gen_adopted_language():
    body = """	<Language uuid="%s">
		<Properties>
			<ObjectBelonging>Adopted</ObjectBelonging>
			<Name>Русский</Name>
			<Comment/>
			<ExtendedConfigurationObject>%s</ExtendedConfigurationObject>
			<LanguageCode>ru</LanguageCode>
		</Properties>
	</Language>""" % (uid("Language.Русский"), BASE_UUIDS["Language.Русский"])
    write("Languages/Русский.xml", md_file(body))


def gen_adopted_document():
    name = "ПлатежноеПоручение"
    gt = generated_types("", name, [("DocumentObject", "Object"), ("DocumentRef", "Ref"),
                                    ("DocumentSelection", "Selection"), ("DocumentList", "List"),
                                    ("DocumentManager", "Manager")])
    body = """	<Document uuid="%s">
		%s
		<Properties>
			<ObjectBelonging>Adopted</ObjectBelonging>
			<Name>%s</Name>
			<Comment/>
			<ExtendedConfigurationObject>%s</ExtendedConfigurationObject>
		</Properties>
		<ChildObjects/>
	</Document>""" % (uid("Document." + name), gt, name, BASE_UUIDS["Document." + name])
    write("Documents/%s.xml" % name, md_file(body))


def gen_adopted_role(name, rights):
    body = """	<Role uuid="%s">
		<Properties>
			<ObjectBelonging>Adopted</ObjectBelonging>
			<Name>%s</Name>
			<Comment/>
			<ExtendedConfigurationObject>%s</ExtendedConfigurationObject>
		</Properties>
	</Role>""" % (uid("Role." + name), name, BASE_UUIDS["Role." + name])
    write("Roles/%s.xml" % name, md_file(body))

    objects = []
    for obj, names in rights:
        r = "".join("<right><name>%s</name><value>true</value></right>" % n for n in names)
        objects.append("<object><name>%s</name>%s</object>" % (obj, r))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<Rights xmlns="http://v8.1c.ru/8.2/roles" '
           'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:type="Rights" version="2.21"><setForNewObjects>false</setForNewObjects>'
           '<setForAttributesByDefault>true</setForAttributesByDefault>'
           '<independentRightsOfChildObjects>false</independentRightsOfChildObjects>%s</Rights>\n' % "".join(objects))
    write("Roles/%s/Ext/Rights.xml" % name, xml)


def gen_common_module(name, title, server=True, client=False, server_call=False):
    body = """	<CommonModule uuid="%s">
		<Properties>
			<Name>%s</Name>
			%s
			<Comment/>
			<Global>false</Global>
			<ClientManagedApplication>%s</ClientManagedApplication>
			<Server>%s</Server>
			<ExternalConnection>false</ExternalConnection>
			<ClientOrdinaryApplication>%s</ClientOrdinaryApplication>
			<ServerCall>%s</ServerCall>
			<Privileged>false</Privileged>
			<ReturnValuesReuse>DontUse</ReturnValuesReuse>
		</Properties>
	</CommonModule>""" % (uid("CommonModule." + name), name, synonym(title), str(client).lower(),
                          str(server).lower(), str(client).lower(), str(server_call).lower())
    write("CommonModules/%s.xml" % name, md_file(body))
    copy_src("CommonModules/%s/Ext/Module.bsl" % name)


def gen_common_command(name, title, tooltip, parameter_type):
    body = """	<CommonCommand uuid="%s">
		<Properties>
			<Name>%s</Name>
			%s
			<Comment/>
			<Group>FormCommandBarImportant</Group>
			<Representation>Text</Representation>
			%s
			<Picture/>
			<Shortcut/>
			<IncludeHelpInContents>false</IncludeHelpInContents>
			<CommandParameterType><v8:Type>%s</v8:Type></CommandParameterType>
			<ParameterUseMode>Single</ParameterUseMode>
			<ModifiesData>false</ModifiesData>
			<OnMainServerUnavalableBehavior>Auto</OnMainServerUnavalableBehavior>
		</Properties>
	</CommonCommand>""" % (uid("CommonCommand." + name), name, synonym(title), synonym(tooltip, "ToolTip"),
                           parameter_type)
    write("CommonCommands/%s.xml" % name, md_file(body))
    copy_src("CommonCommands/%s/Ext/CommandModule.bsl" % name)


def form_md(key, name, title, tag="Form", extra=""):
    return """	<%s uuid="%s">
		<Properties>
			<Name>%s</Name>
			%s
			<Comment/>
			<FormType>Managed</FormType>
			<IncludeHelpInContents>false</IncludeHelpInContents>
			<UsePurposes><v8:Value xsi:type="app:ApplicationUsePurpose">PlatformApplication</v8:Value></UsePurposes>
			<UseInInterfaceCompatibilityMode>Any</UseInInterfaceCompatibilityMode>%s
		</Properties>
	</%s>""" % (tag, uid(key), name, synonym(title), extra, tag)


def gen_common_form(name, title):
    extra = "<UseStandardCommands>false</UseStandardCommands><ExtendedPresentation/><Explanation/>"
    write("CommonForms/%s.xml" % name, md_file(form_md("CommonForm." + name, name, title, "CommonForm", extra)))
    copy_src("CommonForms/%s/Ext/Form.xml" % name)
    copy_src("CommonForms/%s/Ext/Form/Module.bsl" % name)


def gen_catalog_templates():
    name = PREFIX + "ШаблоныДокументов"
    key = "Catalog." + name
    gt = generated_types("", name, [("CatalogObject", "Object"), ("CatalogRef", "Ref"),
                                    ("CatalogSelection", "Selection"), ("CatalogList", "List"),
                                    ("CatalogManager", "Manager")])
    attrs = [
        ("ИдентификаторПоставляемого", "Идентификатор поставляемого шаблона", "string:100", False),
        ("ВерсияПоставки", "Контрольная сумма поставленной версии", "string:64", False),
        ("ФайлШаблона", "Файл шаблона (Word)", "storage", False),
        ("ИмяФайлаШаблона", "Имя файла шаблона", "string:255", False),
        ("ШаблонИмениФайла", "Имя формируемого файла", "string:255", False),
        ("Описание", "Описание", "string", True),
    ]
    attrs_xml = "".join(attribute_xml("Attribute", key + ".Attribute." + n, n, t, ty, ml) for n, t, ty, ml in attrs)

    ts_name = "Параметры"
    ts_key = key + ".TabularSection." + ts_name
    ts_gt = ("<InternalInfo>"
             '<xr:GeneratedType name="CatalogTabularSection.%s.%s" category="TabularSection"><xr:TypeId>%s</xr:TypeId><xr:ValueId>%s</xr:ValueId></xr:GeneratedType>'
             '<xr:GeneratedType name="CatalogTabularSectionRow.%s.%s" category="TabularSectionRow"><xr:TypeId>%s</xr:TypeId><xr:ValueId>%s</xr:ValueId></xr:GeneratedType>'
             "</InternalInfo>" % (name, ts_name, uid(ts_key + ".T1"), uid(ts_key + ".V1"),
                                  name, ts_name, uid(ts_key + ".T2"), uid(ts_key + ".V2")))
    ts_attrs = [
        ("Имя", "Имя поля в шаблоне", "string:150", False),
        ("Представление", "Представление", "string:150", False),
        ("ЗначениеПоУмолчанию", "Значение по умолчанию", "string", False),
        ("Запоминать", "Запоминать введенное значение", "bool", False),
        ("Проверять", "Выделять для проверки", "bool", False),
    ]
    ts_attrs_xml = "".join(attribute_xml("Attribute", ts_key + ".Attribute." + n, n, t, ty, ml)
                           for n, t, ty, ml in ts_attrs)
    ts_xml = ("<TabularSection uuid=\"%s\">%s<Properties><Name>%s</Name>%s<Comment/><ToolTip/>"
              "<FillChecking>DontCheck</FillChecking><Use>ForItem</Use><LineNumberLength>5</LineNumberLength>"
              "</Properties><ChildObjects>%s</ChildObjects></TabularSection>"
              % (uid(ts_key), ts_gt, ts_name, synonym("Параметры (поля, вводимые при формировании)"), ts_attrs_xml))

    body = """	<Catalog uuid="%s">
		%s
		<Properties>
			<Name>%s</Name>
			%s
			<Comment/>
			<Hierarchical>false</Hierarchical>
			<HierarchyType>HierarchyFoldersAndItems</HierarchyType>
			<LimitLevelCount>false</LimitLevelCount>
			<LevelCount>2</LevelCount>
			<FoldersOnTop>true</FoldersOnTop>
			<UseStandardCommands>true</UseStandardCommands>
			<Owners/>
			<SubordinationUse>ToItems</SubordinationUse>
			<CodeLength>0</CodeLength>
			<DescriptionLength>150</DescriptionLength>
			<CodeType>String</CodeType>
			<CodeAllowedLength>Variable</CodeAllowedLength>
			<CodeSeries>WholeCatalog</CodeSeries>
			<CheckUnique>false</CheckUnique>
			<Autonumbering>false</Autonumbering>
			<DefaultPresentation>AsDescription</DefaultPresentation>
			<Characteristics/>
			<PredefinedDataUpdate>Auto</PredefinedDataUpdate>
			<EditType>InDialog</EditType>
			<QuickChoice>true</QuickChoice>
			<ChoiceMode>BothWays</ChoiceMode>
			<InputByString><xr:Field>Catalog.%s.StandardAttribute.Description</xr:Field></InputByString>
			<SearchStringModeOnInputByString>Begin</SearchStringModeOnInputByString>
			<FullTextSearchOnInputByString>DontUse</FullTextSearchOnInputByString>
			<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>
			<DefaultObjectForm>Catalog.%s.Form.ФормаЭлемента</DefaultObjectForm>
			<DefaultFolderForm/>
			<DefaultListForm/>
			<DefaultChoiceForm/>
			<DefaultFolderChoiceForm/>
			<AuxiliaryObjectForm/>
			<AuxiliaryFolderForm/>
			<AuxiliaryListForm/>
			<AuxiliaryChoiceForm/>
			<AuxiliaryFolderChoiceForm/>
			<IncludeHelpInContents>false</IncludeHelpInContents>
			<BasedOn/>
			<DataLockFields/>
			<DataLockControlMode>Managed</DataLockControlMode>
			<FullTextSearch>DontUse</FullTextSearch>
			%s
			<ExtendedObjectPresentation/>
			%s
			<ExtendedListPresentation/>
			<Explanation/>
			<CreateOnInput>DontUse</CreateOnInput>
			<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>
			<DataHistory>DontUse</DataHistory>
			<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>
			<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>
		</Properties>
		<ChildObjects>%s%s<Form>ФормаЭлемента</Form></ChildObjects>
	</Catalog>""" % (uid(key), gt, name, synonym("Шаблоны документов"), name, name,
                     synonym("Шаблон документа", "ObjectPresentation"),
                     synonym("Шаблоны документов", "ListPresentation"), attrs_xml, ts_xml)
    write("Catalogs/%s.xml" % name, md_file(body))

    form_key = key + ".Form.ФормаЭлемента"
    write("Catalogs/%s/Forms/ФормаЭлемента.xml" % name,
          md_file(form_md(form_key, "ФормаЭлемента", "Шаблон документа")))
    copy_src("Catalogs/%s/Forms/ФормаЭлемента/Ext/Form.xml" % name)
    copy_src("Catalogs/%s/Forms/ФормаЭлемента/Ext/Form/Module.bsl" % name)


def gen_register_values():
    name = PREFIX + "ЗапомненныеЗначения"
    key = "InformationRegister." + name
    gt = generated_types("", name, [("InformationRegisterRecord", "Record"),
                                    ("InformationRegisterManager", "Manager"),
                                    ("InformationRegisterSelection", "Selection"),
                                    ("InformationRegisterList", "List"),
                                    ("InformationRegisterRecordSet", "RecordSet"),
                                    ("InformationRegisterRecordKey", "RecordKey"),
                                    ("InformationRegisterRecordManager", "RecordManager")])
    dim_extra = ("<FillFromFillingValue>false</FillFromFillingValue><FillValue xsi:nil=\"true\"/>")
    dims = "".join(
        attribute_xml("Dimension", key + ".Dimension." + n, n, t, "string:150", False, dim_extra,
                      "<Master>false</Master><MainFilter>true</MainFilter><DenyIncompleteValues>false</DenyIncompleteValues>")
        for n, t in [("Владелец", "Владелец (организация, контрагент или шаблон)"), ("ИмяПоля", "Имя поля")])
    res = attribute_xml("Resource", key + ".Resource.Значение", "Значение", "Значение", "string", True, dim_extra)
    res += attribute_xml("Resource", key + ".Resource.ИсходноеЗначение", "ИсходноеЗначение",
                         "Исходное значение (из 1С, которое исправили)", "string", True, dim_extra)
    body = """	<InformationRegister uuid="%s">
		%s
		<Properties>
			<Name>%s</Name>
			%s
			<Comment/>
			<UseStandardCommands>false</UseStandardCommands>
			<EditType>InDialog</EditType>
			<DefaultRecordForm/>
			<DefaultListForm/>
			<AuxiliaryRecordForm/>
			<AuxiliaryListForm/>
			<InformationRegisterPeriodicity>Nonperiodical</InformationRegisterPeriodicity>
			<WriteMode>Independent</WriteMode>
			<MainFilterOnPeriod>false</MainFilterOnPeriod>
			<IncludeHelpInContents>false</IncludeHelpInContents>
			<DataLockControlMode>Managed</DataLockControlMode>
			<FullTextSearch>DontUse</FullTextSearch>
			<EnableTotalsSliceFirst>false</EnableTotalsSliceFirst>
			<EnableTotalsSliceLast>false</EnableTotalsSliceLast>
			<RecordPresentation/>
			<ExtendedRecordPresentation/>
			<ListPresentation/>
			<ExtendedListPresentation/>
			<Explanation/>
			<DataHistory>DontUse</DataHistory>
			<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>
			<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>
		</Properties>
		<ChildObjects>%s%s</ChildObjects>
	</InformationRegister>""" % (uid(key), gt, name, synonym("Запомненные значения полей шаблонов"), res, dims)
    write("InformationRegisters/%s.xml" % name, md_file(body))


def gen_binary_template(name, title, data):
    body = """	<CommonTemplate uuid="%s">
		<Properties>
			<Name>%s</Name>
			%s
			<Comment/>
			<TemplateType>BinaryData</TemplateType>
		</Properties>
	</CommonTemplate>""" % (uid("CommonTemplate." + name), name, synonym(title))
    write("CommonTemplates/%s.xml" % name, md_file(body))
    path = os.path.join(OUT, "CommonTemplates", name, "Ext", "Template.bin")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def copy_src(rel_path):
    src = os.path.join(SRC, rel_path)
    if not os.path.exists(src):
        raise SystemExit("Не найден исходный файл: " + src)
    dst = os.path.join(OUT, rel_path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    # Модули 1С хранятся в UTF-8 с BOM - так их выгружает конфигуратор.
    if rel_path.endswith(".bsl"):
        with open(src, "r", encoding="utf-8-sig") as f:
            text = f.read()
        with open(dst, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(text.replace("\r\n", "\n"))
    else:
        shutil.copyfile(src, dst)


def gen_templates():
    """Поставляемые шаблоны: src/templates/templates.json + файлы .docx."""
    with open(os.path.join(TEMPLATES, "templates.json"), encoding="utf-8") as f:
        descriptions = json.load(f)
    manifest = []
    names = []
    for d in descriptions:
        template_name = PREFIX + "Шаблон_" + d["Идентификатор"]
        with open(os.path.join(TEMPLATES, d["Файл"]), "rb") as f:
            gen_binary_template(template_name, d["Наименование"], f.read())
        names.append(template_name)
        manifest.append({
            "Идентификатор": d["Идентификатор"],
            "Наименование": d["Наименование"],
            "Описание": d.get("Описание", ""),
            "ШаблонИмениФайла": d.get("ШаблонИмениФайла", ""),
            "ИмяФайла": d["Файл"],
            "Макет": template_name,
            "Параметры": [{
                "Имя": p["Имя"],
                "Представление": p.get("Представление", ""),
                "ЗначениеПоУмолчанию": p.get("ЗначениеПоУмолчанию", ""),
                "Запоминать": bool(p.get("Запоминать", False)),
                "Проверять": bool(p.get("Проверять", False)),
            } for p in d.get("Параметры", [])],
        })
    data = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
    gen_binary_template(PREFIX + "ПоставляемыеШаблоны", "Поставляемые шаблоны (описание)", data)
    names.append(PREFIX + "ПоставляемыеШаблоны")
    return names


def generate():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    catalog = PREFIX + "ШаблоныДокументов"
    register = PREFIX + "ЗапомненныеЗначения"
    form = PREFIX + "ФормированиеДокумента"
    command = PREFIX + "СформироватьДокумент"
    module = PREFIX + "ФормированиеДокументов"

    gen_adopted_language()
    gen_adopted_document()
    gen_common_module(module, "Формирование документов по шаблону")
    gen_common_command(command, "Сформировать документ",
                       "Сформировать документ (договор и т.п.) по шаблону на основании платежного поручения",
                       "cfg:DocumentRef.ПлатежноеПоручение")
    gen_common_form(form, "Формирование документа по шаблону")
    gen_catalog_templates()
    gen_register_values()
    template_names = gen_templates()

    catalog_rights = ["Read", "Insert", "Update", "Delete", "View", "Edit", "InputByString",
                      "InteractiveInsert", "InteractiveSetDeletionMark", "InteractiveClearDeletionMark"]
    gen_adopted_role("БазовыеПраваБП", [
        ("Catalog." + catalog, catalog_rights),
        ("InformationRegister." + register, ["Read", "Update", "View", "Edit"]),
        ("CommonForm." + form, ["View"]),
        ("CommonCommand." + command, ["View"]),
    ])

    children = [("Language", "Русский"), ("Role", "БазовыеПраваБП"), ("CommonModule", module),
                ("CommonCommand", command), ("CommonForm", form)]
    children += [("CommonTemplate", n) for n in template_names]
    children += [("Catalog", catalog), ("Document", "ПлатежноеПоручение"), ("InformationRegister", register)]
    gen_configuration(children)
    print("XML расширения сгенерирован:", OUT)


# ---------------------------------------------------------------------------------------------
# Сборка .cfe через конфигуратор
# ---------------------------------------------------------------------------------------------

def run_designer(args, ib, user, password, v8, log_name):
    log = os.path.join(ROOT, "build", log_name)
    cmd = [v8, "DESIGNER", "/F", ib]
    if user:
        cmd += ["/N", user]
    if password:
        cmd += ["/P", password]
    cmd += args + ["/Out", log, "/DisableStartupDialogs", "/DisableStartupMessages"]
    code = subprocess.call(cmd)
    text = ""
    if os.path.exists(log):
        with open(log, encoding="utf-8-sig", errors="replace") as f:
            text = f.read().strip()
    if text:
        print(text)
    if code != 0:
        raise SystemExit("Конфигуратор завершился с ошибкой (код %s), см. %s" % (code, log))


def build_cfe(ib, user, password, v8, update_db):
    os.makedirs(DIST, exist_ok=True)
    cfe = os.path.join(DIST, EXT_NAME + ".cfe")
    print("Загрузка XML в базу...")
    run_designer(["/LoadConfigFromFiles", OUT, "-Extension", EXT_NAME], ib, user, password, v8, "load.log")
    if update_db:
        print("Обновление конфигурации базы данных (расширение)...")
        run_designer(["/UpdateDBCfg", "-Extension", EXT_NAME], ib, user, password, v8, "update.log")
    print("Выгрузка .cfe...")
    run_designer(["/DumpCfg", cfe, "-Extension", EXT_NAME], ib, user, password, v8, "dump.log")
    print("Готово:", cfe)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--cfe", action="store_true", help="собрать .cfe через конфигуратор")
    parser.add_argument("--update-db", action="store_true", help="применить расширение к базе")
    parser.add_argument("--ib")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--v8")
    args = parser.parse_args()

    local = {}
    local_path = os.path.join(ROOT, "tools", "build.local.json")
    if os.path.exists(local_path):
        with open(local_path, encoding="utf-8") as f:
            local = json.load(f)

    generate()
    if args.cfe:
        ib = args.ib or local.get("ib")
        v8 = args.v8 or local.get("v8") or r"C:\Program Files\1cv8\common\1cestart.exe"
        if not ib:
            raise SystemExit("Укажите базу: --ib или tools/build.local.json")
        build_cfe(ib, args.user or local.get("user"), args.password or local.get("password"), v8, args.update_db)


if __name__ == "__main__":
    main()
