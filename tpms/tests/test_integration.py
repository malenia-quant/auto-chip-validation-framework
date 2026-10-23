"""端到端集成测试 (test_integration.py)

测试全流程：
1. 载入车型分类规范与包含全世界国家及中文简称的国家参考库
2. 批量处理包含真实结构（车型生产Sheet、基地合计、常规、合并单元格大车系、小计合计、带有效文字之外噪声的车型列）的各基地月计划文件
3. 验证自动选取标准 Sheet，清洗车型列噪声文字，自动剔除各类汇总行
4. 聚合全基地处理文件，导出 ★秘密★全基地车型数据汇总.xlsx
5. 校验各基地打标准确度、车型列净化效果、表头规范顺序及尾部生成时间备注
"""

import os
import glob
import pytest
import pandas as pd
from openpyxl import load_workbook

from processor.config_manager import ConfigManager
from processor.tagger import ModelTagger
from processor.consolidator import DataConsolidator
from generate_test_dataset import generate_all


class TestEndToEndIntegration:

    @pytest.fixture(scope="module", autouse=True)
    def setup_dataset(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        paths = generate_all(base_dir)
        return paths

    def test_full_pipeline(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "data")
        raw_dir = os.path.join(data_dir, "raw")
        output_dir = os.path.join(data_dir, "output")

        model_spec_file = os.path.join(data_dir, "车型分类规范.xlsx")
        country_list_file = os.path.join(data_dir, "国家列表.xlsx")

        assert os.path.exists(model_spec_file)
        assert os.path.exists(country_list_file)

        # 1. 初始化引擎
        cfg_mgr = ConfigManager(model_spec_file, country_list_file)
        tagger = ModelTagger(cfg_mgr)
        consolidator = DataConsolidator(tagger)

        # 2. 批量处理单基地原始月计划文件（多Sheet且含合计行）
        raw_files = sorted(glob.glob(os.path.join(raw_dir, "*.xlsx")))
        assert len(raw_files) >= 3

        processed_results = consolidator.batch_process_files(raw_files, output_dir=output_dir)
        assert len(processed_results) == len(raw_files)

        processed_files = []
        for orig, proc_path, row_count in processed_results:
            assert os.path.exists(proc_path)
            assert "_processed.xlsx" in proc_path
            assert row_count > 0
            processed_files.append(proc_path)

        # 3. 核心校验：现场照片 1:1 长沙基地月计划处理结果
        cs_proc = [f for f in processed_files if "长沙" in f][0]
        df_cs = pd.read_excel(cs_proc)

        # 验证各类汇总/合计行已被精准剔除，24 行有效车型全部保留
        assert len(df_cs) == 24
        assert "合计" not in df_cs["车型"].values
        assert "常规" not in df_cs["生产车系"].values
        assert "长沙基地合计" not in df_cs["生产车系"].values

        # 验证大车系合并单元格前向填充完全准确，无错位
        series_a_list = df_cs["大车系"].tolist()
        assert series_a_list.count("STE(海鸥)") == 2
        assert series_a_list.count("STH(海豚)") == 1
        assert series_a_list.count("UNE") == 13
        assert series_a_list.count("UNH") == 8

        # 验证车型列保存完整信息（包括选装激光雷达、普通、试验、尾随字符等完整信息）
        models = df_cs["车型"].tolist()
        assert "STEAY尊贵型Y" in models           # 保留完整信息
        assert "UNED-30型(普通)" in models       # 保留完整信息
        assert "UNEH-30型(选装激光雷达)" in models # 保留完整信息
        assert "UNHD-10型试验" in models         # 保留完整信息
        assert "UNHG-30型(选装激光雷达)试验" in models # 保留完整信息

        # 验证配置列打标准确
        configs_cs = df_cs["配置"].tolist()
        assert "直接式" in configs_cs
        assert "间接式" in configs_cs
        assert "独立控制器" in configs_cs
        assert "爆胎" in configs_cs

        # 4. 检查抚州处理结果各行配置列及海外出口识别
        fz_proc = [f for f in processed_files if "抚州" in f][0]
        df_fz = pd.read_excel(fz_proc)
        assert "合计" not in df_fz["车型"].values
        assert df_fz.loc[df_fz["车型"] == "汉EV沙特尊贵版", "配置"].values[0] == "出口"
        assert df_fz.loc[df_fz["车型"] == "海豹印尼右舵版", "配置"].values[0] == "出口"

        # 5. 全基地合并汇总
        summary_path, df_summary = consolidator.consolidate_bases(
            file_paths=processed_files,
            output_dir=output_dir,
            summary_filename="★秘密★全基地车型数据汇总.xlsx"
        )

        assert os.path.exists(summary_path)
        assert "_20" in os.path.basename(summary_path)  # 验证文件名标注了时间戳格式 _YYYYMMDD_HHMM

        # 验证汇总表中不含任何‘合计’、‘总计’或‘小计’
        assert "合计" not in df_summary["车型"].values
        assert "总计" not in df_summary["车型"].values

        # 检查表头列规范
        expected_prefix = ["基地", "大车系", "生产车系", "车型"]
        for idx, col_name in enumerate(expected_prefix):
            assert df_summary.columns[idx] == col_name
        assert df_summary.columns[-1] == "配置"

        # 检查各基地记录已成功汇聚
        bases = df_summary["基地"].tolist()
        assert "长沙" in bases
        assert "常州" in bases
        assert "抚州" in bases
        assert bases.count("长沙") == 24

        # 检查汇总 Excel 尾部时间戳备注
        wb = load_workbook(summary_path)
        ws = wb["车型汇总表"]
        last_cell_val = ws.cell(row=ws.max_row, column=1).value
        assert "备注：数据汇总生成时间" in str(last_cell_val)
        assert "年" in str(last_cell_val) and "月" in str(last_cell_val) and "日" in str(last_cell_val)
        assert "时" in str(last_cell_val) and "分" in str(last_cell_val)
