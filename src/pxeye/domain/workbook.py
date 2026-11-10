"""Read bounded, plain XLSX inventory data into the existing CSV import path."""

import base64
import binascii
import csv
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def interface_workbook(headers, rows):
    """Produce a plain-text, styled XLSX that workbook_csv can read unchanged."""
    namespace = NS["s"]

    def column_name(index):
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def node(parent, name, **attrs):
        return ET.SubElement(
            parent, "{" + namespace + "}" + name, {key: str(value) for key, value in attrs.items()}
        )

    sheet = ET.Element("{" + namespace + "}worksheet")
    last = f"{column_name(len(headers))}{len(rows) + 1}"
    node(sheet, "dimension", ref="A1:" + last)
    view = node(node(sheet, "sheetViews"), "sheetView", workbookViewId=0, showGridLines=1)
    node(
        view, "pane", xSplit=2, ySplit=1, topLeftCell="C2", activePane="bottomRight", state="frozen"
    )
    node(view, "selection", pane="bottomRight", activeCell="C2", sqref="C2")
    node(sheet, "sheetFormatPr", defaultRowHeight=32)
    widths = [
        min(64, max(32, max(len(str(row[i])) for row in [headers, *rows]) + 3))
        for i in range(len(headers))
    ]
    columns = node(sheet, "cols")
    for i, width in enumerate(widths, 1):
        node(columns, "col", min=i, max=i, width=width, customWidth=1)
    data = node(sheet, "sheetData")
    for index, values in enumerate([headers, *rows], 1):
        height = (
            40
            if index == 1
            else max(
                32,
                max((len(str(value)) + width - 1) // width for value, width in zip(values, widths))
                * 18
                + 8,
            )
        )
        row = node(data, "row", r=index, ht=height, customHeight=1)
        for column, value in enumerate(values, 1):
            cell = node(
                row, "c", r=f"{column_name(column)}{index}", t="inlineStr", s=1 if index == 1 else 0
            )
            text = node(node(cell, "is"), "t")
            text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            text.text = str(value)
    node(sheet, "autoFilter", ref="A1:" + last)
    styles = f'''<styleSheet xmlns="{namespace}">
      <fonts count="2"><font><sz val="13"/><name val="Calibri"/></font>
      <font><b/><sz val="14"/><name val="Calibri"/></font></fonts>
      <fills count="3"><fill><patternFill patternType="none"/></fill>
      <fill><patternFill patternType="gray125"/></fill>
      <fill><patternFill patternType="solid"><fgColor rgb="FFE2F0D9"/>
      <bgColor indexed="64"/></patternFill></fill></fills>
      <borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
      <border><left style="thin"><color rgb="FFB8C2CC"/></left>
      <right style="thin"><color rgb="FFB8C2CC"/></right>
      <top style="thin"><color rgb="FFB8C2CC"/></top>
      <bottom style="thin"><color rgb="FFB8C2CC"/></bottom><diagonal/></border></borders>
      <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
      <cellXfs count="2"><xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0"
      applyNumberFormat="1" applyBorder="1" applyAlignment="1">
      <alignment vertical="center" wrapText="1"/></xf>
      <xf numFmtId="49" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1"
      applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1">
      <alignment vertical="center" wrapText="1"/></xf></cellXfs>
      <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
    </styleSheet>'''
    files = {
        "[Content_Types].xml": """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
          <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
          <Default Extension="xml" ContentType="application/xml"/>
          <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
          <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
          <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
        </Types>""",
        "_rels/.rels": f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>
        </Relationships>''',
        "xl/workbook.xml": f'''<workbook xmlns="{namespace}" xmlns:r="{REL}">
          <sheets><sheet name="设备网卡列表" sheetId="1" r:id="rId1"/></sheets></workbook>''',
        "xl/_rels/workbook.xml.rels": f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>
          <Relationship Id="rId2" Type="{REL}/styles" Target="styles.xml"/>
        </Relationships>''',
        "xl/styles.xml": styles,
        "xl/worksheets/sheet1.xml": ET.tostring(sheet, encoding="utf-8", xml_declaration=True),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return base64.b64encode(output.getvalue()).decode("ascii")


def workbook_csv(encoded):
    if not isinstance(encoded, str) or len(encoded) > 1400000:
        raise ValueError("Excel 最大 1 MiB。")
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 1024 * 1024:
            raise ValueError("Excel 最大 1 MiB。")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 200
                or len({e.filename for e in entries}) != len(entries)
                or sum(e.file_size for e in entries) > 12 * 1024 * 1024
            ):
                raise ValueError("Excel 内容过大，请减少行数后导入。")

            def xml(name):
                raw = archive.read(name)
                if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                    raise ValueError("Excel 包含不支持的 XML 内容。")
                return ET.fromstring(raw)

            workbook = xml("xl/workbook.xml")
            sheets = workbook.findall("s:sheets/s:sheet", NS)
            if not sheets:
                raise ValueError("Excel 中没有设备清单。")
            sheet = next((s for s in sheets if s.get("name") == "设备清单"), sheets[0])
            rel_id = sheet.get("{" + REL + "}id")
            relations = xml("xl/_rels/workbook.xml.rels")
            relation = next((r for r in relations if r.get("Id") == rel_id), None)
            if relation is None or relation.get("TargetMode") == "External":
                raise ValueError("无法读取 Excel 工作表。")
            target = relation.get("Target", "")
            name = posixpath.normpath(
                target.lstrip("/") if target.startswith("/") else "xl/" + target
            )
            if not name.startswith("xl/worksheets/"):
                raise ValueError("无法读取 Excel 工作表。")
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = [
                    "".join(t.text or "" for t in s.iter("{" + NS["s"] + "}t"))
                    for s in xml("xl/sharedStrings.xml").findall("s:si", NS)
                ]
            rows = []
            for row in xml(name).findall("s:sheetData/s:row", NS):
                if len(rows) >= 5001:
                    raise ValueError("Excel 最多支持 5000 条数据。")
                cells = {}
                for cell in row.findall("s:c", NS):
                    ref = re.fullmatch(r"([A-Z]{1,3})[1-9][0-9]*", cell.get("r", ""))
                    if not ref:
                        raise ValueError("Excel 单元格位置无效。")
                    col = 0
                    for ch in ref[1]:
                        col = col * 26 + ord(ch) - 64
                    if col > 64 or col in cells:
                        raise ValueError("Excel 列数超出范围或存在重复单元格。")
                    if cell.find("s:f", NS) is not None:
                        raise ValueError("设备清单不支持公式，请改为文本值。")
                    kind = cell.get("t", "")
                    value = cell.findtext("s:v", "", NS)
                    if kind == "s":
                        if not value.isascii() or not value.isdecimal():
                            raise ValueError("Excel 文本索引无效。")
                        value = strings[int(value)]
                    elif kind == "inlineStr":
                        value = "".join(
                            t.text or ""
                            for t in cell.findall("s:is/s:t", NS) + cell.findall("s:is/s:r/s:t", NS)
                        )
                    elif kind == "b":
                        value = "true" if value == "1" else "false"
                    elif kind in {"e", "d"}:
                        raise ValueError("设备清单包含错误值或日期，请改为文本。")
                    cells[col] = value
                if any(v.strip() for v in cells.values()):
                    rows.append(cells)
            if not rows:
                raise ValueError("Excel 中没有设备清单。")
            width = max(rows[0])
            if any(max(r) > width for r in rows):
                raise ValueError("Excel 数据超出表头列范围。")
            output = io.StringIO(newline="")
            csv.writer(output).writerows(
                [[r.get(c, "") for c in range(1, width + 1)] for r in rows]
            )
            return output.getvalue()
    except (
        binascii.Error,
        zipfile.BadZipFile,
        KeyError,
        ET.ParseError,
        IndexError,
        TypeError,
        RuntimeError,
        NotImplementedError,
    ):
        raise ValueError("无法读取 Excel，请使用下载的 .xlsx 模板。") from None
