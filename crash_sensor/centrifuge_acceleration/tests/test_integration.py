"""
端到端集成测试: 模拟量产批次在 Mode A (首测) 与 Mode B (定向复测) 下的完整数据流转
对应 TC-INT-001, TC-INT-002, TC-INT-003
"""

import os
import sys
import csv
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data_processor")))

from processor.can_data_parser import CentrifugeCANParser
from processor.centrifuge_processor import CentrifugeProcessor
from processor.calibration_processor import CalibrationProcessor
from processor.result_consolidator import ResultConsolidator, DataMerger


def _generate_mock_can_csv(file_path: str, valid_channels: list, broken_channels: list, empty_channels: list):
    """辅助生成仿真 24 通道 CAN 测试 CSV 文件"""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    rows = []

    for b in range(1, 5):
        for s in range(1, 7):
            can_id = f"0x1{b}{s}"
            token_pair = (b, s)

            if token_pair in empty_channels:
                # 01 f0 空载
                data_hex = "01 f0 " * 32
            elif token_pair in broken_channels:
                # 状态异常
                tokens = ["01", "00"] * 32
                data_hex = " ".join(tokens)
            else:
                # 正常 64 字节报文 (32 组 [02, val])
                tokens = []
                for i in range(32):
                    tokens.append("02")
                    tokens.append(f"{(i + s) % 16:02X}")
                data_hex = " ".join(tokens)

            rows.append({
                "MAKE_CAN_ID(HEX)": can_id,
                "DATA(HEX)": data_hex
            })

    with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["MAKE_CAN_ID(HEX)", "DATA(HEX)"])
        writer.writeheader()
        writer.writerows(rows)


class TestEndToEndPipeline:
    """端到端全流程验证"""

    def test_full_pipeline_flow(self, tmp_path):
        """TC-INT-001 & TC-INT-002: Mode A 首测 -> 换装 -> 标定 -> Mode B 补测良率闭环"""
        output_dir = tmp_path / "Data_Consolidation"
        parser = CentrifugeCANParser()
        cal_proc = CalibrationProcessor(span_min=600.0, span_max=3600.0)
        consolidator = ResultConsolidator(base_output_dir=str(output_dir))
        merger = DataMerger()

        # 构造仿真数据:
        # 工位 (1, 1) ~ (1, 4): 正常件
        # 工位 (1, 5): 仅 Axis1 正常, Axis2 缺测 (将进入 Rework)
        # 工位 (1, 6): 通信损坏 (进入 Abnormal)
        # 其余通道设为空载
        valid_a1 = [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5)]
        broken_a1 = [(1, 6)]
        empty_a1 = [(b, s) for b in range(1, 5) for s in range(1, 7) if (b, s) not in valid_a1 and (b, s) not in broken_a1]

        axis1_file = str(tmp_path / "raw_axis1.csv")
        _generate_mock_can_csv(axis1_file, valid_a1, broken_a1, empty_a1)

        # Axis2 数据: (1, 5) 缺失
        valid_a2 = [(1, 1), (1, 2), (1, 3), (1, 4)]
        broken_a2 = [(1, 6)]
        empty_a2 = [(b, s) for b in range(1, 5) for s in range(1, 7) if (b, s) not in valid_a2 and (b, s) not in broken_a2]

        axis2_file = str(tmp_path / "raw_axis2.csv")
        _generate_mock_can_csv(axis2_file, valid_a2, broken_a2, empty_a2)

        # 1. 运行 Mode A 首测解析
        res_a1 = parser.parse_can_raw_csv(axis1_file)
        res_a2 = parser.parse_can_raw_csv(axis2_file)

        assert len(res_a1["filenames_4in1"]) == 6
        assert len(res_a2["filenames_4in1"]) == 6

        # 2. 组装测试集
        tested_list = []
        for s_idx in range(24):
            item1 = res_a1["slots"].get(s_idx, {})
            item2 = res_a2["slots"].get(s_idx, {})
            b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s_idx)
            fixture = "N" if b_id in (1, 2) else "P"

            # 过滤全空通道
            if not item1.get("is_valid") and not item2.get("is_valid") and (b_id, s_id) in empty_a1:
                continue

            is_valid = item1.get("is_valid", False) or item2.get("is_valid", False)
            if (b_id, s_id) in broken_a1:
                is_valid = False

            dev_code = item1.get("device_code_11") or item2.get("device_code_11") or "00000000000"
            uid = item1.get("uid_32") or item2.get("uid_32") or "-"

            # 需求 8: N (25A/25B) 内圈 Axis1 为负，Axis2 为正
            ax1_mean = -850.0 if item1.get("is_valid") else None
            ax2_mean = 850.0 if item2.get("is_valid") else None

            tested_list.append({
                "device_code_11": dev_code,
                "uid_32": uid,
                "can_id": f"0x1{b_id}{s_id}",
                "board_id": b_id,
                "sensor_id": s_id,
                "fixture_type": fixture,
                "is_valid": is_valid,
                "status_msg": "正常" if is_valid else "通信故障",
                "Axis1_Mean": ax1_mean,
                "Axis2_Mean": ax2_mean,
            })

        normal, rework, abnormal = consolidator.classify_devices(tested_list, calibration_processor=cal_proc)

        # 校验首测分类分流
        assert len(normal) == 4    # (1,1) ~ (1,4) 合格
        assert len(rework) == 1    # (1,5) 缺失 Axis2
        assert len(abnormal) == 1  # (1,6) 硬件故障

        rework_chip = rework[0]["芯片编号_HEX"]
        assert rework[0]["缺失轴向"] == "Axis2"

        dirs = consolidator.organize_directories(lot_id="LOT1")
        tri_files = consolidator.export_tri_lists(dirs["month_root"], "20260818_120000", normal, rework, abnormal)

        # 3. 运行 Mode B 定向复测 (对 (1, 5) 补测 Axis2)
        rework_can_file = str(tmp_path / "rework_axis2.csv")
        # 仅补测 (1, 5)
        _generate_mock_can_csv(rework_can_file, valid_channels=[(1, 5)], broken_channels=[], empty_channels=[])

        parsed_rw = parser.parse_can_raw_csv(rework_can_file)
        slot_1_5 = parser.get_global_slot_index(1, 5)
        rw_item = parsed_rw["slots"][slot_1_5]

        # 物理受力对齐 (工装 N, Axis2 对应正向)
        corr_val = merger.resolve_physical_polarity("N", "Axis2", 850.0)
        assert corr_val == 850.0

        # 执行良率闭环状态流转
        resolved_details = [{
            "芯片编号_HEX": rework_chip,
            "完整32位Hex_UID": rw_item.get("uid_32", "-"),
            "供电板编号": 1,
            "通道编号": 5,
            "工装类别": "N",
            "Axis1_均值": "-850.00",
            "Axis2_均值": f"{corr_val:.2f}",
            "Span": "2550.00",
            "ADJ_HEX": "3C2A",
            "状态": "Passed",
            "完成时间": "2026-08-18 12:30:00",
        }]

        consolidator.update_rework_to_normal_closure(
            rework_csv_path=tri_files["rework"],
            normal_csv_path=tri_files["normal"],
            resolved_device_codes=[rework_chip],
            resolved_details=resolved_details
        )

        # 验证最终闭环结果
        df_rw_final = pd.read_csv(tri_files["rework"], dtype=str)
        assert df_rw_final.loc[df_rw_final["芯片编号_HEX"] == rework_chip, "复测状态"].iloc[0] == "Resolved"

        df_nm_final = pd.read_csv(tri_files["normal"], dtype=str)
        assert len(df_nm_final) == 5  # 原 4 颗 + 补测合格 1 颗 = 5 颗
        assert rework_chip in df_nm_final["芯片编号_HEX"].values
