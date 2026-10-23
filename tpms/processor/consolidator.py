"""数据处理与全基地汇总合并引擎 (DataConsolidator)

负责：
1. 单基地月计划文件处理：
   - 智能识别多 Sheet 中代表“车型汇总”的 Sheet 作为标准处理对象
   - 自动剔除“合计”、“总计”、“小计”行
   - 从文件名识别基地（eg: ★秘密★抚州-月计划 MFZ202637002.xlsx -> 抚州）
   - 调用打标引擎在原始表格后追加“配置”列
   - 导出为 ★秘密★抚州-月计划 MFZ202637002_processed.xlsx
2. 全基地数据合并与汇总：
   - 按照 {基地} + {大车系} + {生产车系} + {车型} + {排产后续数据...} + {配置} 进行统一标准化合并
   - 剔除任何跨基地汇总时残留的合计行
   - 导出为 ★秘密★全基地车型数据汇总.xlsx（及带时间戳版本）
   - 满足用户要求：在汇总表末尾追加生成时间备注行，格式精确到“年月日小时分钟”
"""

import os
import re
import datetime
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from .config_manager import ConfigManager
from .tagger import ModelTagger


class DataConsolidator:
    """负责单基地打标处理与跨基地数据合并汇总"""

    def __init__(self, tagger: Optional[ModelTagger] = None):
        self.tagger = tagger or ModelTagger()

    @classmethod
    def select_target_sheet(cls, excel_file: pd.ExcelFile) -> str:
        """
        智能选取用于数据打标的标准车型汇总 sheet：
        用户明确需求：“另外月计划表格中可能还有多个sheet，要选取车型汇总的sheet是作为数据达标的标准文件。”
        优先级：
        1. sheet 名包含 '车型汇总' (最高优先级，如 '车型汇总', '车型汇总表', '9月车型汇总')
        2. sheet 名同时包含 '车型' 与 '汇总'
        3. sheet 名包含 '车型'
        4. sheet 名包含 '汇总'
        5. sheet 名包含 '月计划' 或 '计划'
        6. 解析各 sheet 表头，选取包含 '车型' 列的 sheet
        7. 回退至第 1 个 sheet
        """
        names = excel_file.sheet_names
        if len(names) == 1:
            return names[0]

        # 1. 优先完全匹配或包含 '车型汇总'
        for s in names:
            if "车型汇总" in s:
                return s

        # 2. 包含 '车型生产' (现场生产实际常见工作表名)
        for s in names:
            if "车型生产" in s:
                return s

        # 3. 同时包含 '车型' 和 '汇总'
        for s in names:
            if "车型" in s and "汇总" in s:
                return s

        # 3. 包含 '车型'
        for s in names:
            if "车型" in s:
                return s

        # 4. 包含 '汇总'
        for s in names:
            if "汇总" in s:
                return s

        # 5. 包含 '月计划' 或 '计划'
        for s in names:
            if "月计划" in s or "计划" in s:
                return s

        # 6. 检查各 sheet 列名是否包含 '车型'
        for s in names:
            try:
                df_head = excel_file.parse(s, nrows=2)
                cols_clean = [str(c).strip() for c in df_head.columns]
                if any("车型" in c for c in cols_clean):
                    return s
            except Exception:
                continue

        # 7. 回退至第 1 个 sheet
        return names[0]

    @staticmethod
    def extract_base_name_from_filename(filename: str) -> str:
        """
        从文件名中解析所属生产基地。
        支持示例：
        - ★秘密★抚州-月计划 MFZ202637002.xlsx -> 抚州
        - 抚州-月计划 MFZ202637002.xlsx -> 抚州
        - 常州-月计划 MCZ202637003.xlsx -> 常州
        - ★秘密★合肥-月计划.xlsx -> 合肥
        """
        base_name = os.path.basename(filename)
        stem = os.path.splitext(base_name)[0]

        # 模式 1: ★秘密★{基地}-月计划
        m1 = re.search(r'★?秘密★?\s*([^-_\s]+)\s*[-_]月计划', stem)
        if m1:
            return m1.group(1).strip()

        # 模式 2: {基地}-月计划
        m2 = re.search(r'([^-_\s]+)\s*[-_]月计划', stem)
        if m2:
            return m2.group(1).strip()

        # 模式 3: 提取第一个破折号前或下划线前文字
        parts = re.split(r'[-_]', stem)
        if parts:
            clean_part = re.sub(r'[★秘密\s]', '', parts[0])
            if clean_part:
                return clean_part

        return "未知基地"

    def process_single_base_file(
        self,
        file_path: str,
        output_dir: Optional[str] = None
    ) -> Tuple[str, pd.DataFrame]:
        """
        处理单基地月计划文件：
        1. 选取“车型汇总” sheet
        2. 剔除“合计”行
        3. 追加“配置”列
        4. 保存为 _processed.xlsx
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        base_filename = os.path.basename(file_path)
        stem, ext = os.path.splitext(base_filename)

        processed_stem = stem if stem.endswith("_processed") else f"{stem}_processed"
        out_name = f"{processed_stem}{ext if ext else '.xlsx'}"

        target_dir = output_dir or os.path.dirname(file_path)
        os.makedirs(target_dir, exist_ok=True)
        out_path = os.path.join(target_dir, out_name)

        # 提取基地
        base_name = self.extract_base_name_from_filename(file_path)

        # 读取 Excel 文件并智能选择车型汇总 Sheet
        excel = pd.ExcelFile(file_path)
        sheet_to_process = self.select_target_sheet(excel)
        df = excel.parse(sheet_to_process)

        # 执行打标（内置自动剔除合计/总计行）
        df_tagged = self.tagger.tag_dataframe(df, drop_totals=True)

        # 满足用户要求：基地放在第一列（首列）
        if "基地" not in df_tagged.columns:
            df_tagged.insert(0, "基地", base_name)
        else:
            cols = ["基地"] + [c for c in df_tagged.columns if c != "基地"]
            df_tagged = df_tagged[cols]

        # 导出为 Excel
        df_tagged.to_excel(out_path, sheet_name=sheet_to_process, index=False, engine="openpyxl")

        return out_path, df_tagged

    def batch_process_files(
        self,
        file_paths: List[str],
        output_dir: Optional[str] = None
    ) -> List[Tuple[str, str, int]]:
        """
        批量处理多个单基地文件

        返回:
            [(原始路径, 处理后路径, 行数), ...]
        """
        results = []
        for fp in file_paths:
            out_path, df = self.process_single_base_file(fp, output_dir=output_dir)
            results.append((fp, out_path, len(df)))
        return results

    def consolidate_bases(
        self,
        file_paths: List[str],
        output_dir: str,
        summary_filename: str = "★秘密★全基地车型汇总表.xlsx",
        include_timestamp_copy: bool = True,
        custom_time: Optional[datetime.datetime] = None
    ) -> Tuple[str, pd.DataFrame]:
        """
        将多个单基地的文件汇总合并为一个全基地汇总表。

        按照规范排序列：
        {基地} + {大车系} + {生产车系} + {车型} + {原始排产月份等后续列...} + {配置}

        并在表格尾部添加“年月日小时分钟”汇总生成备注行。
        """
        if not file_paths:
            raise ValueError("汇总文件列表为空，无法进行汇总。")

        now = custom_time or datetime.datetime.now()
        timestamp_str = now.strftime("%Y年%m月%d日 %H时%M分")
        file_timestamp = now.strftime("%Y%m%d_%H%M")

        consolidated_rows = []
        subsequent_cols_order: List[str] = []

        for fp in file_paths:
            # 提取基地
            base_name = self.extract_base_name_from_filename(fp)

            # 读取表格并选择合适 Sheet
            excel = pd.ExcelFile(fp)
            target_sheet = self.select_target_sheet(excel)
            df = excel.parse(target_sheet)

            # 统一使用当前最新激活的规范规则重新打标（更新或追加“配置”列，内置处理合并单元格、剔除合计行、保留车型列完整信息）
            df = self.tagger.tag_dataframe(df, drop_totals=True)

            # 智能全兼容确定大车系、生产车系、车型列（去除空格，兼容所有新老表头变体）
            def _map_col(candidates):
                for cand in candidates:
                    cand_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', cand).lower()
                    for c in df.columns:
                        c_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c)).lower()
                        if c_clean == cand_clean:
                            return c
                for cand in candidates:
                    cand_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', cand).lower()
                    for c in df.columns:
                        c_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c)).lower()
                        if cand_clean and (cand_clean in c_clean or c_clean in cand_clean):
                            return c
                return None

            col_map = {
                "大车系": _map_col(["一级大车系筛选代码", "1级大车系筛选代码", "大车系筛选代码", "一级大车系", "1级大车系", "大车系代码", "大车系", "车系分类", "车系大类"]),
                "生产车系": _map_col(["二级生产车系筛选代码", "2级生产车系筛选代码", "生产车系筛选代码", "生产车系代码", "二级生产车系", "2级生产车系", "生产车系", "一级车型代码", "一级车系", "车系代号", "生产车型", "车型代码", "车系代码", "车系名称", "车系"]),
                "车型": _map_col(["车型", "车型名称", "车型全称", "完整车型", "三级车型筛选代码", "3级车型筛选代码", "车型筛选代码", "二级车型代码", "二级车型"]),
            }

            # 收集排产等后续数据列（排除大车系、生产车系、车型、配置、基地）
            core_cols = set(col_map.values()) | {"配置", "基地"}
            data_cols = [c for c in df.columns if c not in core_cols]

            for dc in data_cols:
                if dc not in subsequent_cols_order:
                    subsequent_cols_order.append(dc)

            # 转换为标准行
            for _, row in df.iterrows():
                row_dict = {
                    "基地": base_name,
                    "大车系": row.get(col_map.get("大车系", "大车系"), ""),
                    "生产车系": row.get(col_map.get("生产车系", "生产车系"), ""),
                    "车型": row.get(col_map.get("车型", "车型"), ""),
                    "配置": row.get("配置", ""),
                }
                for dc in data_cols:
                    row_dict[dc] = row.get(dc, "")
                consolidated_rows.append(row_dict)

        # 构建汇总 DataFrame，严格按照列顺序排列
        final_cols = ["基地", "大车系", "生产车系", "车型"] + subsequent_cols_order + ["配置"]
        df_summary = pd.DataFrame(consolidated_rows)

        # 补全可能缺失的列
        for fc in final_cols:
            if fc not in df_summary.columns:
                df_summary[fc] = ""

        df_summary = df_summary[final_cols]

        os.makedirs(output_dir, exist_ok=True)

        # 仅生成并保留标注时间的那一份汇总文件 (eg: ★秘密★全基地车型数据汇总_YYYYMMDD_HHMM.xlsx)
        stem, ext = os.path.splitext(summary_filename)
        if re.search(r'_\d{8}_\d{4}', stem):
            actual_filename = summary_filename
        else:
            actual_filename = f"{stem}_{file_timestamp}{ext if ext else '.xlsx'}"

        summary_path = os.path.join(output_dir, actual_filename)

        # 写入 Excel 并美化尾部备注行
        self._write_summary_excel_with_footer(
            df_summary,
            summary_path,
            timestamp_str=timestamp_str
        )

        return summary_path, df_summary

    def _write_summary_excel_with_footer(
        self,
        df: pd.DataFrame,
        save_path: str,
        timestamp_str: str
    ):
        """
        使用 openpyxl 写入汇总数据并追加样式精美的尾部备注行（精确到年月日小时分钟）。
        """
        with pd.ExcelWriter(save_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="车型汇总表", index=False)

        # 加载工作簿追加尾部备注
        wb = load_workbook(save_path)
        ws = wb["车型汇总表"]

        max_row = ws.max_row
        max_col = ws.max_column

        # 表头样式美化（采用深商务蓝背景 #0D47A1，白色字体，居中）
        header_font = Font(name="Microsoft YaHei UI", size=10, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="0D47A1", end_color="0D47A1", fill_type="solid")
        border_thin = Border(
            left=Side(style="thin", color="CCCCCC"),
            right=Side(style="thin", color="CCCCCC"),
            top=Side(style="thin", color="CCCCCC"),
            bottom=Side(style="thin", color="CCCCCC")
        )

        for c in range(1, max_col + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border_thin

        # 内容行边框与字体
        data_font = Font(name="Microsoft YaHei UI", size=10)
        for r in range(2, max_row + 1):
            for c in range(1, max_col + 1):
                cell = ws.cell(row=r, column=c)
                cell.font = data_font
                cell.border = border_thin
                # 基地与配置列居中
                if c in [1, max_col]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

        # 追加空行隔开
        footer_row_idx = max_row + 2
        ws.cell(row=footer_row_idx, column=1, value=f"备注：数据汇总生成时间 {timestamp_str}")

        # 合并尾部备注行单元格
        ws.merge_cells(start_row=footer_row_idx, start_column=1, end_row=footer_row_idx, end_column=max_col)
        footer_cell = ws.cell(row=footer_row_idx, column=1)
        footer_cell.font = Font(name="Microsoft YaHei UI", size=10, italic=True, bold=True, color="37474F")
        footer_cell.alignment = Alignment(horizontal="left", vertical="center")
        footer_cell.fill = PatternFill(start_color="F0F4F8", end_color="F0F4F8", fill_type="solid")

        # 调整列宽自适应
        for col in ws.columns:
            col_letter = col[0].column_letter
            max_len = 0
            for cell in col:
                val = str(cell.value or "")
                val_len = sum(2 if ord(ch) > 127 else 1 for ch in val)
                if val_len > max_len and cell.row <= max_row:
                    max_len = val_len
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        wb.save(save_path)
