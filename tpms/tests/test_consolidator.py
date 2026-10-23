"""测试单基地文件打标与全基地数据汇总合并逻辑 (test_consolidator.py)

涵盖：
1. 单基地文件名基地提取 (★秘密★抚州-月计划 MFZ202637002.xlsx -> 抚州)
2. 多 Sheet 智能识别：准确选取【车型汇总】Sheet
3. 剔除合计/总计行：确保处理后文件不含合计行
4. 单基地处理后生成 _processed.xlsx，表尾追加“配置”列
5. 全基地汇总表格式规范: {基地}+{大车系}+{生产车系}+{车型}+{后续排产数据...}+{配置}
6. 汇总表尾部备注行写入：验证精确到“年月日小时分钟”
"""

import os
import datetime
import pytest
import pandas as pd
from openpyxl import load_workbook

from processor.config_manager import ConfigManager
from processor.tagger import ModelTagger
from processor.consolidator import DataConsolidator


@pytest.fixture
def consolidator(tmp_path):
    spec_path = str(tmp_path / "车型分类规范.xlsx")
    country_path = str(tmp_path / "国家列表.xlsx")
    ConfigManager.create_default_model_spec(spec_path)
    ConfigManager.create_default_country_list(country_path)

    cfg = ConfigManager(spec_path, country_path)
    tagger = ModelTagger(cfg)
    return DataConsolidator(tagger)


class TestDataConsolidator:

    def test_extract_base_name(self):
        """测试从各类规范文件名中准确提取生产基地"""
        fn1 = "★秘密★抚州-月计划 MFZ202637002.xlsx"
        assert DataConsolidator.extract_base_name_from_filename(fn1) == "抚州"

        fn2 = "常州-月计划 MCZ202637003.xlsx"
        assert DataConsolidator.extract_base_name_from_filename(fn2) == "常州"

        fn3 = "★秘密★合肥-月计划.xlsx"
        assert DataConsolidator.extract_base_name_from_filename(fn3) == "合肥"

        fn4 = "郑州_月计划_202609.xlsx"
        assert DataConsolidator.extract_base_name_from_filename(fn4) == "郑州"

    def test_select_target_sheet_multi_sheets(self, consolidator, tmp_path):
        """测试多 Sheet 情况下智能优先匹配【车型汇总】Sheet"""
        multi_file = str(tmp_path / "多表测试.xlsx")
        with pd.ExcelWriter(multi_file, engine="openpyxl") as writer:
            pd.DataFrame({"基地信息": ["抚州"]}).to_excel(writer, sheet_name="基本信息", index=False)
            pd.DataFrame({"大车系": ["仰望"], "生产车系": ["EWEK"], "车型": ["EWEK-10"]}).to_excel(writer, sheet_name="车型汇总", index=False)
            pd.DataFrame({"设备": ["A1"]}).to_excel(writer, sheet_name="车间清单", index=False)

        excel = pd.ExcelFile(multi_file)
        selected = DataConsolidator.select_target_sheet(excel)
        assert selected == "车型汇总"

    def test_process_single_base_file_filters_total_row(self, consolidator, tmp_path):
        """测试单基地处理自动选取车型汇总 Sheet、剔除‘合计’行并在末尾追加‘配置’列"""
        in_file = str(tmp_path / "★秘密★抚州-月计划 MFZ202637002.xlsx")
        with pd.ExcelWriter(in_file, engine="openpyxl") as writer:
            pd.DataFrame({"说明": ["前言信息"]}).to_excel(writer, sheet_name="基地封面", index=False)
            df_in = pd.DataFrame({
                "大车系": ["仰望", "海洋", "合计"],
                "生产车系": ["EWEK", "HAN", "合计"],
                "车型": ["EWEK-10型", "汉EV沙特版", "合计"],
                "9月计划排产": [1000, 2000, 3000]
            })
            df_in.to_excel(writer, sheet_name="车型汇总", index=False)

        out_path, df_out = consolidator.process_single_base_file(in_file)

        assert os.path.exists(out_path)
        assert out_path.endswith("★秘密★抚州-月计划 MFZ202637002_processed.xlsx")

        # 验证合计行已被剔除，仅保留2行有效车型
        assert len(df_out) == 2
        assert "合计" not in df_out["车型"].values
        assert "配置" in df_out.columns
        assert df_out["配置"].tolist() == ["爆胎", "出口"]

        # 检查首列为基地，配置列在最后
        expected_cols = ["基地", "大车系", "生产车系", "车型", "9月计划排产", "配置"]
        assert list(df_out.columns) == expected_cols

    def test_consolidate_bases_and_footer_timestamp(self, consolidator, tmp_path):
        """测试跨基地合并汇总及尾部年月日小时分钟备注"""
        f1 = str(tmp_path / "★秘密★抚州-月计划 MFZ202637002.xlsx")
        df1 = pd.DataFrame({
            "大车系": ["仰望", "合计"],
            "生产车系": ["EWEK", "合计"],
            "车型": ["-10型", "总计/合计"],
            "9月计划排产": [500, 500],
            "10月计划排产": [600, 600]
        })
        df1.to_excel(f1, sheet_name="车型汇总", index=False, engine="openpyxl")

        f2 = str(tmp_path / "★秘密★常州-月计划 MCZ202637003.xlsx")
        df2 = pd.DataFrame({
            "大车系": ["海洋", "总计"],
            "生产车系": ["ATTO", "总计"],
            "车型": ["日本旗舰版", "总计"],
            "9月计划排产": [800, 800],
            "10月计划排产": [900, 900]
        })
        df2.to_excel(f2, sheet_name="车型汇总", index=False, engine="openpyxl")

        out_dir = str(tmp_path / "output")
        test_time = datetime.datetime(2026, 9, 15, 4, 30, 0)

        summary_path, df_summary = consolidator.consolidate_bases(
            file_paths=[f1, f2],
            output_dir=out_dir,
            summary_filename="★秘密★全基地车型数据汇总.xlsx",
            custom_time=test_time
        )

        assert os.path.exists(summary_path)
        # 验证返回的文件路径直接为带时间戳的文件
        assert "20260915_0430" in summary_path
        # 验证输出目录下仅生成并保留这 1 份带有时间标注的汇总文件
        xlsx_files = [f for f in os.listdir(out_dir) if f.endswith(".xlsx")]
        assert len(xlsx_files) == 1
        assert xlsx_files[0] == "★秘密★全基地车型数据汇总_20260915_0430.xlsx"

        # 验证表头规范排列: {基地}+{大车系}+{生产车系}+{车型}+{排产后续数据}+{配置}
        expected_order = ["基地", "大车系", "生产车系", "车型", "9月计划排产", "10月计划排产", "配置"]
        assert list(df_summary.columns) == expected_order

        # 验证合计行已被剔除，内容行数严格等于各基地有效车型数 (1 + 1 = 2)
        assert len(df_summary) == 2
        assert "总计" not in df_summary["车型"].values
        assert "合计" not in df_summary["车型"].values
        assert df_summary["基地"].tolist() == ["抚州", "常州"]
        assert df_summary["配置"].tolist() == ["爆胎", "出口"]

        # 验证 Excel 表格尾部的“年月日小时分钟”备注行
        wb = load_workbook(summary_path)
        ws = wb["车型汇总表"]

        footer_found = False
        for row in ws.iter_rows(values_only=True):
            for val in row:
                if val and "备注：数据汇总生成时间 2026年09月15日 04时30分" in str(val):
                    footer_found = True
                    break

        assert footer_found, "汇总表尾部必须包含指定格式的年月日小时分钟生成时间备注！"
