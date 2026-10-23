"""一键生成规范模板与全套真实生产级测试数据集脚本 (generate_test_dataset.py)

1:1 还原用户现场图片真实月计划排版与数据结构：
1. 规范文件：
   - data/车型分类规范.xlsx（包含“直接式”、“间接式”、“独立控制器”、“爆胎”、“胎压监测”等规范 Sheet）
   - data/国家列表.xlsx（含全世界 197+ 个国家及常用中文简称，如沙特阿拉伯/沙特、阿联酋、印尼、澳洲、日本、德国等）
2. 原始单基地月计划文件（真实多 Sheet 结构、含 [基地]基地合计行、常规行、车系合并单元格、合计行、带有效文字之外噪声的车型列）：
   - data/raw/★秘密★长沙-月计划 MXS202637001.xlsx (现场图片真实数据 1:1 还原，Sheet 名为“车型生产”)
   - data/raw/★秘密★常州-月计划 MCZ202637003.xlsx (含出口海外日本/德国定制车型及合并单元格)
   - data/raw/★秘密★抚州-月计划 MFZ202637002.xlsx (含沙特/印尼/阿联酋海外版与爆胎应急车型)
"""

import os
import sys
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from processor.config_manager import ConfigManager


def create_changsha_real_excel(file_path: str):
    """
    根据用户现场真实拍摄图片 1:1 生成《★秘密★长沙-月计划 MXS202637001.xlsx》：
    - 工作表名：“车型生产”
    - 第 1 行：表头 (大车系, 生产车系, 车型, 9月计划排产, 10月计划排产, 11月计划排产)
    - 第 2 行：长沙基地合计 (22794, 23616, 24600)
    - 第 3 行：常规 (22794, 23616, 24600)
    - 第 4 行：合计 (132, 0, 0)
    - 第 5-6 行：STE(海鸥) -> STEAY (STEAY尊贵型Y), STEBU (STEBU-10型)
    - 第 7-8 行：STH(海豚) -> 合计 (610, 400, 600), STHNY (STHNY-15型)
    - 第 9-22 行：UNE -> 合计 (10052, 11206, 13000), UNEC, UNED(带普通), UNEH(带选装激光雷达), UNEJ, UNEK, UNEL
    - 第 23-31 行：UNH -> 合计 (12000, 12010, 11000), UNHC, UNHD(试验), UNHG(选装激光雷达试验)
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "车型生产"

    headers = ["大车系", "生产车系", "车型", "9月计划排产", "10月计划排产", "11月计划排产"]
    ws.append(headers)

    # 样式定义
    red_fill = PatternFill(start_color="D32F2F", end_color="D32F2F", fill_type="solid")
    red_font = Font(name="Microsoft YaHei UI", size=10, bold=True, color="FFFFFF")
    bold_font = Font(name="Microsoft YaHei UI", size=10, bold=True)
    normal_font = Font(name="Microsoft YaHei UI", size=10)
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")

    thin_border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC")
    )

    # 表头样式
    for col_idx in range(1, 7):
        c = ws.cell(row=1, column=col_idx)
        c.fill = red_fill
        c.font = red_font
        c.alignment = center_align

    # 数据行配置: (大车系, 生产车系, 车型, 9月, 10月, 11月, 是否红色汇总行)
    rows_data = [
        # 行 2: 长沙基地合计
        ("长沙基地合计", None, None, 22794, 23616, 24600, True),
        # 行 3: 常规
        (None, "常规", None, 22794, 23616, 24600, True),
        # 行 4: STE 小计
        (None, "合计", None, 132, 0, 0, True),
        # 行 5-6: STE(海鸥)
        ("STE(海鸥)", "STEAY", "STEAY尊贵型Y", 61, 0, 0, False),
        (None, "STEBU", "STEBU-10型", 71, 0, 0, False),
        # 行 7-8: STH(海豚)
        ("STH(海豚)", "合计", None, 610, 400, 600, True),
        (None, "STHNY", "STHNY-15型", 610, 400, 600, False),
        # 行 9-22: UNE
        ("UNE", "合计", None, 10052, 11206, 13000, True),
        (None, "UNEC", "UNEC-10型", 67, 0, 0, False),
        (None, "UNED", "UNED-20型", 182, 0, 0, False),
        (None, "UNED", "UNED-30型(普通)", 2, 0, 0, False),
        (None, "UNEH", "UNEH-20型", 1600, 1500, 2000, False),
        (None, "UNEH", "UNEH-30型", 5550, 8200, 9200, False),
        (None, "UNEH", "UNEH-30型(选装激光雷达)", 950, 800, 600, False),
        (None, "UNEJ", "UNEJ-40型", 1500, 600, 1050, False),
        (None, "UNEJ", "UNEJ-40型(选装激光雷达)", 200, 100, 150, False),
        (None, "UNEK", "UNEK-10型", 1, 0, 0, False),
        (None, "UNEK", "UNEK-10型(选装激光雷达)", 0, 2, 0, False),
        (None, "UNEL", "UNEL-30型(选装激光雷达)", 0, 2, 0, False),
        (None, "UNEL", "UNEL-40型", 0, 1, 0, False),
        (None, "UNEL", "UNEL-40型(选装激光雷达)", 0, 1, 0, False),
        # 行 23-31: UNH
        ("UNH", "合计", None, 12000, 12010, 11000, True),
        (None, "UNHC", "UNHC-10型", 2900, 4100, 2300, False),
        (None, "UNHC", "UNHC-15型", 2100, 2100, 2150, False),
        (None, "UNHC", "UNHC-20型", 4000, 3700, 4400, False),
        (None, "UNHC", "UNHC-20型(选装激光雷达)", 100, 100, 150, False),
        (None, "UNHD", "UNHD-10型试验", 0, 2, 0, False),
        (None, "UNHG", "UNHG-30型试验", 0, 2, 0, False),
        (None, "UNHG", "UNHG-30型(选装激光雷达)试验", 0, 4, 0, False),
        (None, "UNHG", "UNHG-40型试验", 0, 2, 0, False),
    ]

    for r_idx, row_vals in enumerate(rows_data, start=2):
        is_red = row_vals[6]
        for c_idx in range(1, 7):
            val = row_vals[c_idx - 1]
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.border = thin_border
            if is_red:
                cell.fill = red_fill
                cell.font = red_font
                cell.alignment = center_align
            else:
                cell.font = normal_font
                cell.alignment = left_align if c_idx == 3 else center_align

    # 合并单元格还原现场结构
    ws.merge_cells("A2:C2")   # 长沙基地合计
    ws.merge_cells("A3:C3")   # 常规
    ws.merge_cells("B4:C4")   # STE 小计
    ws.merge_cells("A5:A6")   # STE(海鸥)
    ws.merge_cells("A7:A8")   # STH(海豚)
    ws.merge_cells("B7:C7")   # STH 合计
    ws.merge_cells("A9:A22")  # UNE
    ws.merge_cells("B9:C9")   # UNE 合计
    ws.merge_cells("A23:A31") # UNH
    ws.merge_cells("B23:C23") # UNH 合计

    # 列宽设置
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 36
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 16

    # 增加另一个说明 Sheet，验证系统能自动识别“车型生产”
    ws_note = wb.create_sheet(title="编制说明")
    ws_note.append(["项目", "内容"])
    ws_note.append(["生产基地", "长沙基地总装二厂"])
    ws_note.append(["编制部门", "生产计划科"])

    wb.save(file_path)
    return file_path


def create_changzhou_real_excel(file_path: str):
    """生成包含出口日本版、合并单元格及总计行的常州基地月计划文件"""
    wb = Workbook()
    ws = wb.active
    ws.title = "车型汇总"

    headers = ["大车系", "生产车系", "车型", "9月计划排产", "10月计划排产", "11月计划排产"]
    ws.append(headers)

    rows = [
        ("常州基地合计", None, None, 14200, 15300, 16100),
        ("常规", None, None, 14200, 15300, 16100),
        ("CKE", "合计", None, 3200, 3500, 3600),
        ("CKE", "CKEB", "(CKEB-30型-右舵-日标充电-日本79091)", 1200, 1300, 1400), # 命中爆胎(规范)
        (None, "CKEB", "(CKEB-40型-右舵-日标充电-日本79062/79064)", 2000, 2200, 2200), # 命中出口(日本)
        ("海洋", "合计", None, 6500, 6800, 7200),
        ("海洋", "SEAL", "SEAL-08型", 3500, 3600, 3800),                     # 命中独立控制器
        (None, "ATTO", "ATTO-05型", 3000, 3200, 3400),                      # 命中胎压监测
        ("王朝", "合计", None, 4500, 5000, 5300),
        ("王朝", "TANG", "唐DM-p德国定制版", 2500, 2800, 3000),               # 命中出口(德国)
        (None, "D9", "腾势D9尊荣版", 2000, 2200, 2300),                      # 未设计(空白)
    ]

    for r_vals in rows:
        ws.append(list(r_vals))

    ws.merge_cells("A2:C2")
    ws.merge_cells("A3:C3")
    ws.merge_cells("B4:C4")
    ws.merge_cells("A4:A6")
    ws.merge_cells("B7:C7")
    ws.merge_cells("A7:A9")
    ws.merge_cells("B10:C10")
    ws.merge_cells("A10:A12")

    wb.save(file_path)
    return file_path


def create_fuzhou_real_excel(file_path: str):
    """生成包含中东沙特、阿联酋、印尼版及爆胎应急车型的抚州基地月计划文件"""
    wb = Workbook()
    ws = wb.active
    ws.title = "车型汇总"

    headers = ["大车系", "生产车系", "车型", "9月计划排产", "10月计划排产", "11月计划排产"]
    ws.append(headers)

    rows = [
        ("抚州基地合计", None, None, 18500, 19600, 20800),
        ("常规", None, None, 18500, 19600, 20800),
        ("仰望", "合计", None, 5000, 5300, 5600),
        ("仰望", "EWEK", "EWEK-10型", 2000, 2100, 2200),                    # 爆胎
        (None, "EWEK", "EWEK-20型(选装激光雷达)", 1800, 1900, 2000),        # 爆胎且需清洗
        (None, "EWEK", "汉EV 605KM 尊贵型(EWEK-10) 黑色", 1200, 1300, 1400), # 爆胎且需提取
        ("王朝", "合计", None, 7500, 8000, 8500),
        ("王朝", "HAN", "汉EV沙特尊贵版", 4000, 4200, 4500),                # 出口(沙特)
        (None, "QIN", "秦PLUS阿联酋旗舰版", 3500, 3800, 4000),              # 出口(阿联酋)
        ("海洋", "合计", None, 6000, 6300, 6700),
        ("海洋", "SEAL", "海豹印尼右舵版", 3200, 3300, 3500),                # 出口(印尼)
        (None, "SEAL", "海豹06-普通款", 2800, 3000, 3200),                  # 未设计(空白)
    ]

    for r_vals in rows:
        ws.append(list(r_vals))

    ws.merge_cells("A2:C2")
    ws.merge_cells("A3:C3")
    ws.merge_cells("B4:C4")
    ws.merge_cells("A4:A7")
    ws.merge_cells("B8:C8")
    ws.merge_cells("A8:A10")
    ws.merge_cells("B11:C11")
    ws.merge_cells("A11:A13")

    wb.save(file_path)
    return file_path


def generate_all(base_dir: str = None):
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    data_dir = os.path.join(base_dir, "data")
    raw_dir = os.path.join(data_dir, "raw")
    output_dir = os.path.join(data_dir, "output")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 1. 创建规范文件
    model_spec_file = os.path.join(data_dir, "车型分类规范.xlsx")
    region_list_file = os.path.join(data_dir, "地区列表.xlsx")
    country_list_file = os.path.join(data_dir, "国家列表.xlsx")

    ConfigManager.create_default_model_spec(model_spec_file)
    ConfigManager.create_default_country_list(region_list_file)
    ConfigManager.create_default_country_list(country_list_file)
    print(f"[OK] 生成车型分类规范(直接式/间接式/独立控制器/爆胎): {model_spec_file}")
    print(f"[OK] 生成地区列表(含新喀里多尼亚、波利尼西亚、香港、澳门、台湾及中文简称): {region_list_file}")

    # 2. 生成 1:1 现场真实数据图片对应的长沙月计划
    cs_file = os.path.join(raw_dir, "★秘密★长沙-月计划 MXS202637001.xlsx")
    create_changsha_real_excel(cs_file)
    print(f"[OK] 1:1还原图片生成长沙月计划(车型生产Sheet/基地合计/小计/合并单元格): {cs_file}")

    # 3. 生成常州月计划 (含出口日本版/合并单元格)
    cz_file = os.path.join(raw_dir, "★秘密★常州-月计划 MCZ202637003.xlsx")
    create_changzhou_real_excel(cz_file)
    print(f"[OK] 生成常州月计划(含出口日本/德国版及合并单元格): {cz_file}")

    # 4. 生成抚州月计划 (含沙特/阿联酋/印尼及爆胎版)
    fz_file = os.path.join(raw_dir, "★秘密★抚州-月计划 MFZ202637002.xlsx")
    create_fuzhou_real_excel(fz_file)
    print(f"[OK] 生成抚州月计划(含沙特/阿联酋/印尼及爆胎版): {fz_file}")

    # 清理旧的合肥文件，保持数据干净
    hf_old = os.path.join(raw_dir, "★秘密★合肥-月计划 MHF202637004.xlsx")
    if os.path.exists(hf_old):
        try:
            os.remove(hf_old)
        except Exception:
            pass

    print("\n所有真实生产级测试文件与规范模板已全部生成完毕！")
    return {
        "model_spec": model_spec_file,
        "region_list": region_list_file,
        "country_list": region_list_file,
        "raw_files": [cs_file, cz_file, fz_file],
        "output_dir": output_dir,
    }


if __name__ == "__main__":
    generate_all()
