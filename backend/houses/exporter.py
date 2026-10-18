"""
房源数据导出：CSV（utf-8-sig，便于 Excel 打开）与 XLSX（openpyxl）。
导出字段：id,title,district,community,total_price,unit_price,square,size,room_num,hall_num,floor,decoration,elevator
"""
import csv
import io
from datetime import datetime

from django.http import HttpResponse

# (模型字段名, 导出表头)
EXPORT_COLUMNS = [
    ("id", "房源编号"),
    ("title", "标题"),
    ("district", "区域"),
    ("community", "小区"),
    ("total_price", "总价(万元)"),
    ("unit_price", "单价(元/㎡)"),
    ("square", "面积(㎡)"),
    ("size", "户型"),
    ("room_num", "室"),
    ("hall_num", "厅"),
    ("floor", "楼层"),
    ("decoration", "装修"),
    ("elevator", "电梯"),
]


def _cell(value):
    """单元格取值：None 转空字符串，其余原样（Decimal 统一转 float）。"""
    if value is None:
        return ""
    if hasattr(value, "to_eng_string"):  # Decimal
        return float(value)
    return value


def _to_csv(rows):
    """生成 CSV 字节内容（utf-8-sig）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in EXPORT_COLUMNS])
    for row in rows:
        writer.writerow([_cell(row.get(key)) for key, _ in EXPORT_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


def _to_xlsx(rows):
    """生成 XLSX 字节内容（openpyxl）。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "房源数据"
    ws.append([label for _, label in EXPORT_COLUMNS])
    for row in rows:
        ws.append([_cell(row.get(key)) for key, _ in EXPORT_COLUMNS])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def export_houses(rows, file_type="csv"):
    """根据 file_type 生成附件下载响应（不要用 ok/fail 包装）。"""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if file_type == "xlsx":
        content = _to_xlsx(rows)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"houses_{stamp}.xlsx"
    else:
        content = _to_csv(rows)
        content_type = "text/csv; charset=utf-8"
        filename = f"houses_{stamp}.csv"

    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
