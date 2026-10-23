"""
ResultConsolidator 与 DataMerger 单元测试用例集
对应 TC-POLAR-001, TC-MERG-001, TC-CLOSE-001, TC-LIST-001
"""

import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data_processor")))

from processor.result_consolidator import ResultConsolidator, DataMerger
from processor.calibration_processor import CalibrationProcessor


class TestResultConsolidatorAndMerger:
    """测试结果分流、A/B 极性对齐、数据缝合与良率闭环流转"""

    def test_fixture_ab_polarity_alignment(self):
        """TC-POLAR-001: 校验 P/N 夹具在 Axis1 与 Axis2 时的物理受力极性 (需求 8)"""
        merger = DataMerger()

        # Axis1: P 正 N 负
        assert merger.resolve_physical_polarity("P", "Axis1", 850.0) == 850.0
        assert merger.resolve_physical_polarity("N", "Axis1", 850.0) == -850.0

        # Axis2: P 负 N 正 (翻转工装后受力方向互换)
        assert merger.resolve_physical_polarity("P", "Axis2", 850.0) == -850.0
        assert merger.resolve_physical_polarity("N", "Axis2", 850.0) == 850.0

    def test_data_merger_stitch_logic(self):
        """TC-MERG-001: 原 LOT1 缺失 Axis2 的条目与 Rework_Lot 补测条目缝合"""
        merger = DataMerger()

        # 原主数据表 (芯片 1 缺 Axis2，芯片 2 双轴正常)
        lot_df = pd.DataFrame([
            {
                "device_code_11": "00030020001",
                "fixture_type": "P",
                "Axis1_Mean": 850.0,
                "Axis2_Mean": None,
                "rework_status": "Pending",
            },
            {
                "device_code_11": "00030020002",
                "fixture_type": "N",
                "Axis1_Mean": -840.0,
                "Axis2_Mean": 845.0,
                "rework_status": "Passed",
            }
        ])

        # 补测数据表 (仅重测 Axis2)
        rework_df = pd.DataFrame([
            {
                "device_code_11": "00030020001",
                "rework_reading": 855.0,  # 原始读数
            }
        ])

        merged = merger.merge_lot_with_rework(lot_df, rework_df, rework_axis="Axis2")

        # 校验芯片 1 的 Axis2 是否被成功缝合并完成极性对齐 (工装 P 在 Axis2 为负)
        row1 = merged[merged["device_code_11"] == "00030020001"].iloc[0]
        assert row1["Axis2_Mean"] == -855.0
        assert row1["rework_status"] == "Resolved"

        # 校验未参与补测的芯片 2 保持原样
        row2 = merged[merged["device_code_11"] == "00030020002"].iloc[0]
        assert row2["Axis2_Mean"] == 845.0

    def test_tri_lists_classification_and_export(self, tmp_path):
        """TC-LIST-001: 校验三清单分类分流与导出"""
        cal_proc = CalibrationProcessor(span_min=600.0, span_max=3600.0)
        consolidator = ResultConsolidator(base_output_dir=str(tmp_path))

        devices = [
            # 1. 正常合格件 (双轴齐全且过门禁，板3为 25C 正向区 P: Axis1>0, Axis2<0)
            {
                "device_code_11": "00030020001",
                "uid_32": "UID001",
                "board_id": 3,
                "sensor_id": 1,
                "fixture_type": "P",
                "is_valid": True,
                "Axis1_Mean": 850.0,
                "Axis2_Mean": -850.0,
            },
            # 2. 缺轴件 (缺 Axis2，进入 Rework)
            {
                "device_code_11": "00030020002",
                "uid_32": "UID002",
                "board_id": 3,
                "sensor_id": 2,
                "fixture_type": "P",
                "is_valid": True,
                "Axis1_Mean": 850.0,
                "Axis2_Mean": None,
            },
            # 3. 硬件断路通信故障件 (进入 Abnormal)
            {
                "device_code_11": "00000000000",
                "can_id": "0x133",
                "board_id": 3,
                "sensor_id": 3,
                "fixture_type": "P",
                "is_valid": False,
                "status_msg": "第 2 组数据状态异常 (Status: 0x01)",
            },
        ]

        normal, rework, abnormal = consolidator.classify_devices(devices, calibration_processor=cal_proc)

        assert len(normal) == 1
        assert normal[0]["芯片编号_HEX"] == "00030020001"
        assert normal[0]["ADJ_HEX"] != "-"

        assert len(rework) == 1
        assert rework[0]["芯片编号_HEX"] == "00030020002"
        assert rework[0]["缺失轴向"] == "Axis2"

        assert len(abnormal) == 1
        assert abnormal[0]["供电板编号"] == 3
        assert abnormal[0]["通道编号"] == 3

        # 导出测试
        out_paths = consolidator.export_tri_lists(str(tmp_path), "20260818", normal, rework, abnormal)
        assert os.path.exists(out_paths["normal"])
        assert os.path.exists(out_paths["rework"])
        assert os.path.exists(out_paths["abnormal"])

    def test_rework_to_normal_yield_closure(self, tmp_path):
        """TC-CLOSE-001: 校验补测成功后 Rework 更新为 Resolved 并追加 Normal 清单"""
        consolidator = ResultConsolidator(base_output_dir=str(tmp_path))

        rework_file = tmp_path / "Rework_List_test.csv"
        normal_file = tmp_path / "Normal_List_test.csv"

        df_init_rework = pd.DataFrame([
            {"芯片编号_HEX": "00030020002", "复测状态": "Pending", "缺失轴向": "Axis2"}
        ])
        df_init_rework.to_csv(rework_file, index=False, encoding="utf-8-sig")

        df_init_normal = pd.DataFrame([
            {"芯片编号_HEX": "00030020001", "状态": "Passed"}
        ])
        df_init_normal.to_csv(normal_file, index=False, encoding="utf-8-sig")

        # 触发良率闭环更新
        resolved_details = [
            {"芯片编号_HEX": "00030020002", "状态": "Passed"}
        ]
        consolidator.update_rework_to_normal_closure(
            str(rework_file),
            str(normal_file),
            resolved_device_codes=["00030020002"],
            resolved_details=resolved_details
        )

        # 检验 Rework 状态变为 Resolved
        df_rw_after = pd.read_csv(rework_file, dtype=str)
        matched = df_rw_after.loc[df_rw_after["芯片编号_HEX"] == "00030020002", "复测状态"]
        assert len(matched) > 0
        assert matched.iloc[0] == "Resolved"

        # 检验 Normal 文件追加了 00030020002，总数变成 2
        df_nm_after = pd.read_csv(normal_file, dtype=str)
        assert len(df_nm_after) == 2
        assert "00030020002" in df_nm_after["芯片编号_HEX"].values

    def test_fixture_polarity_inversion_gate(self):
        """测试工装极性门禁：防止首测时因工装接反导致两个轴向均为负或均为正，误用 max/min 掩盖错误"""
        consolidator = ResultConsolidator()

        inverted_devices = [
            # 异常案例 1: 正向工装 P (25C) 接反，导致 Axis1 读数为负 (-850)，Axis2 读数为负 (-840) (P要求 Axis1>0)
            {
                "device_code_11": "00030020001",
                "uid_32": "UID001",
                "board_id": 3,
                "sensor_id": 1,
                "fixture_type": "P",
                "is_valid": True,
                "Axis1_Mean": -850.0,
                "Axis2_Mean": -840.0,
            },
            # 异常案例 2: 负向工装 N (25A) 接反，导致 Axis1 为正 (+850)，Axis2 为负 (-850) (N要求 Axis1<0, Axis2>0)
            {
                "device_code_11": "00030020002",
                "uid_32": "UID002",
                "board_id": 1,
                "sensor_id": 1,
                "fixture_type": "N",
                "is_valid": True,
                "Axis1_Mean": 850.0,
                "Axis2_Mean": -850.0,
            }
        ]

        normal, rework, abnormal = consolidator.classify_devices(inverted_devices)

        # 两个异常件必须全部被门禁拦截，严禁进入 Normal 列表
        assert len(normal) == 0
        assert len(abnormal) == 2
        assert abnormal[0]["异常类型"] == "物理极性反转/工装异常"
        assert "正向区(P)极性不符" in abnormal[0]["原始错误信息"]
        assert abnormal[1]["异常类型"] == "物理极性反转/工装异常"
        assert "负向区(N)极性不符" in abnormal[1]["原始错误信息"]

    def test_organize_directories_daily_layout(self, tmp_path):
        """需求 13 验证：Normal_Lot 与 Rework_Lot 文件夹统一放置在同日文件夹 daily_dir 下，而非与日目录并列"""
        consolidator = ResultConsolidator(base_output_dir=str(tmp_path))
        dirs = consolidator.organize_directories(date_str="2026-09-11", lot_id="LOT1", centrifuge_id="Centrifuge1")

        daily_dir = dirs["daily_dir"]
        assert daily_dir.endswith(os.path.join("2026", "09", "11"))
        # 验证 normal_lot_root 和 rework_lot_root 是 daily_dir 的子目录
        assert dirs["normal_lot_root"] == os.path.join(daily_dir, "Normal_Lot")
        assert dirs["rework_lot_root"] == os.path.join(daily_dir, "Rework_Lot")
        assert dirs["normal_lot_dir"] == os.path.join(daily_dir, "Normal_Lot", "LOT1")
        assert dirs["rework_lot_dir"] == os.path.join(daily_dir, "Rework_Lot", "LOT1")

    def test_export_axis_processed_data1_and_idcheck(self, tmp_path):
        """需求 11 验证：首测处理后输出 ProcessedData1 与 IdCheck 两份 CSV 文件，格式严格对齐规范"""
        consolidator = ResultConsolidator(base_output_dir=str(tmp_path))
        lot_dir = os.path.join(str(tmp_path), "test_lot")

        # 模拟 slot 0 和 slot 1
        parsed_slots = {
            0: {
                "is_valid": True,
                "device_code_11": "00030020001",
                "uid_32": "UID_HEX_001",
                "cfg29_val": 0xCF62,
                "cfg28_val": 0x9028,
                "cfg27_val": 0x3027,
                "芯片器件码": "CF6290283027",
                "生产日期_真实日期": "2026-09-11",
            },
            1: {
                "is_valid": True,
                "device_code_11": "00030020002",
                "uid_32": "UID_HEX_002",
                "cfg29_val": 0x1111,
                "cfg28_val": 0x2222,
                "cfg27_val": 0x3333,
                "芯片器件码": "111122223333",
                "生产日期_真实日期": "2026-09-11",
            }
        }
        series_map = {
            0: [320.0, 321.0, 322.0],
            1: [315.0, 316.0],
        }
        paired_neg_series = {
            0: [-320.0, -321.0, -322.0],
            1: [-315.0, -316.0],
        }

        # 1. 完整双向数据 (+160g 与 -160g)
        files = consolidator.export_axis_processed_data1_and_idcheck(
            lot_dir=lot_dir,
            timestamp="20260911_120000",
            axis="Axis1",
            parsed_slots=parsed_slots,
            series_map=series_map,
            paired_neg_series_map=paired_neg_series,
            centrifuge_id="Centrifuge1"
        )

        assert os.path.exists(files["id_check"])
        assert os.path.exists(files["proc1"])

        # 检查 IdCheck 格式
        df_id = pd.read_csv(files["id_check"], dtype=str)
        assert "芯片器件码" in df_id.columns
        assert "CF6290283027" in df_id["芯片器件码"].values
        assert "111122223333" in df_id["芯片器件码"].values

        # 检查 ProcessedData1 表头与数据 (10进制加速度)
        df_proc = pd.read_csv(files["proc1"])
        expected_cols = [
            "CF6290283027_+160g", "CF6290283027_-160g",
            "111122223333_+160g", "111122223333_-160g"
        ]
        assert list(df_proc.columns) == expected_cols
        assert int(df_proc["CF6290283027_+160g"].iloc[0]) == 320

        # 2. 负向数据缺失兼容性测试 (只保留 +160g)
        files_pos_only = consolidator.export_axis_processed_data1_and_idcheck(
            lot_dir=lot_dir,
            timestamp="20260911_120001",
            axis="Axis1",
            parsed_slots=parsed_slots,
            series_map=series_map,
            paired_neg_series_map=None,
            centrifuge_id="Centrifuge1"
        )
        df_pos_only = pd.read_csv(files_pos_only["proc1"])
        assert list(df_pos_only.columns) == ["CF6290283027_+160g", "111122223333_+160g"]

    def test_daily_yield_breakpoint_persistence(self, tmp_path):
        """需求 11 验证：当日良率统计（只计 Pass 和 Fail，排除复测），断点保存并在多批次后正确累加"""
        consolidator = ResultConsolidator(base_output_dir=str(tmp_path))
        daily_dir = os.path.join(str(tmp_path), "2026", "09", "11")

        # 批次 1: 18 Pass, 2 Fail
        res1 = consolidator.record_batch_yield(daily_dir, lot_id="LOT1", batch_pass=18, batch_fail=2, date_str="2026-09-11")
        assert res1["total_pass"] == 18
        assert res1["total_fail"] == 2
        assert res1["yield_rate"] == 90.0
        assert os.path.exists(res1["file_path"])

        # 批次 2: 20 Pass, 0 Fail
        res2 = consolidator.record_batch_yield(daily_dir, lot_id="LOT2", batch_pass=20, batch_fail=0, date_str="2026-09-11")
        assert res2["total_pass"] == 38
        assert res2["total_fail"] == 2
        assert res2["yield_rate"] == 95.0

        # 从断点文件重新加载验证
        loaded = consolidator.load_daily_yield(daily_dir, date_str="2026-09-11")
        assert loaded["total_pass"] == 38
        assert loaded["total_fail"] == 2
        assert loaded["yield_rate"] == 95.0
        assert loaded["batches"] == 2

    def test_keep_only_latest_file_per_lot(self, tmp_path):
        """需求 13 验证：Normal_List 与标定等文件每次生成只保留最新一个文件，自动清理同批次历史旧文件"""
        consolidator = ResultConsolidator(base_output_dir=str(tmp_path))
        dirs = consolidator.organize_directories(date_str="2026-09-11", lot_id="LOT1", centrifuge_id="Centrifuge1")

        sample_normal = [{
            "工位": 0, "LOT编号": "LOT1", "供电板编号": 1, "通道编号": 1, "芯片器件码": "CODE1",
            "Axis1_Mean": 850.0, "Axis2_Mean": 850.0, "检验结论": "Normal", "工装类别": "P"
        }]

        # 第一次导出 (时间戳 1)
        consolidator.export_tri_lists(
            export_dir=dirs["normal_lot_dir"],
            timestamp="20260911_100000",
            normal_list=sample_normal,
            rework_list=[],
            abnormal_list=[],
            lot_id="LOT1"
        )
        files1 = [f for f in os.listdir(dirs["normal_lot_dir"]) if f.endswith(".csv")]
        assert len(files1) == 3
        assert any("20260911_100000" in f for f in files1)

        # 第二次导出同一批次 (时间戳 2)
        consolidator.export_tri_lists(
            export_dir=dirs["normal_lot_dir"],
            timestamp="20260911_110000",
            normal_list=sample_normal,
            rework_list=[],
            abnormal_list=[],
            lot_id="LOT1"
        )
        files2 = [f for f in os.listdir(dirs["normal_lot_dir"]) if f.endswith(".csv")]
        # 必须只保留最新版本 (3份清单每份各1个)，旧时间戳全部被清除
        assert len(files2) == 3
        assert all("20260911_110000" in f for f in files2)
        assert not any("20260911_100000" in f for f in files2)

