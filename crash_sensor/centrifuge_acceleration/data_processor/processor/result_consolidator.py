"""
CrashSensor 结果整合引擎、数据缝合器 (Data Merger) 与三清单良率闭环管理器
1. 以芯片编号_HEX / UID 为主键进行跨批次 Join 缝合
2. A/B 夹具物理受力极性对齐 (Axis1 A正B负, Axis2 A负B正)
3. 规范 Data_Consolidation 目录组织 (LOTn / Rework_Lot)
4. 三清单 (Normal_List, Rework_List, AbnormalFunction_List) 去重与生命周期流转
"""

import os
import csv
import datetime
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd


class DataMerger:
    """
    数据缝合引擎:
    负责将 LOTn 原始批次中缺轴的数据与 Rework_Lot 补测数据进行主键 Join 缝合，
    并在物理层校准 A/B 工装翻转后的受力符号。
    """

    @staticmethod
    def resolve_physical_polarity(fixture_type: str, test_axis: str, raw_reading: float) -> float:
        """
        根据工装类型与轴向对齐真实物理受力符号 (需求 8):
        - 25C / 25D 为正向区域 (P): Axis1 为正向 (+), Axis2 翻转为负向 (-)
        - 25A / 25B 为负向区域 (N): Axis1 为负向 (-), Axis2 翻转为正向 (+)
        """
        f_type = fixture_type.strip().upper()
        is_pos_fixture = f_type in ("P", "POSITIVE", "B")  # 兼容旧代码 B 对应正向区
        axis = test_axis.strip()
        val = abs(raw_reading)

        if axis == "Axis1":
            return val if is_pos_fixture else -val
        elif axis == "Axis2":
            return -val if is_pos_fixture else val
        return raw_reading

    def merge_lot_with_rework(
        self,
        lot_df: pd.DataFrame,
        rework_df: pd.DataFrame,
        rework_axis: str,
        join_key: str = "device_code_11"
    ) -> pd.DataFrame:
        """
        将补测数据依据 join_key 缝合进主数据表中
        """
        merged = lot_df.copy()
        if rework_df.empty:
            return merged

        rework_map = {}
        for _, r_row in rework_df.iterrows():
            key = r_row.get(join_key)
            if key and str(key) != "00000000000":
                rework_map[str(key)] = r_row

        for idx, row in merged.iterrows():
            key = str(row.get(join_key, ""))
            if key in rework_map:
                r_item = rework_map[key]
                fixture = row.get("fixture_type", "A")
                raw_val = r_item.get("rework_reading", None)

                if raw_val is not None and not pd.isna(raw_val):
                    corrected_val = self.resolve_physical_polarity(fixture, rework_axis, float(raw_val))
                    if rework_axis == "Axis1":
                        merged.at[idx, "Axis1_Mean"] = corrected_val
                    elif rework_axis == "Axis2":
                        merged.at[idx, "Axis2_Mean"] = corrected_val
                    merged.at[idx, "rework_status"] = "Resolved"

        return merged


class ResultConsolidator:
    """
    测试结果分类汇总与三清单良率闭环管理器
    """

    def __init__(self, base_output_dir: str = "Data_Consolidation"):
        self.base_output_dir = base_output_dir
        self.merger = DataMerger()

    def organize_directories(
        self,
        date_str: Optional[str] = None,
        lot_id: str = "LOT1",
        centrifuge_id: str = "Centrifuge1"
    ) -> Dict[str, str]:
        """
        初始化符合原厂规范的标准目录树 (图 5/8、图 4/8):
        {base_output_dir}/
          |--Centrifuge1/
          |   |--Data_Consolidation/
          |   |   |--{YYYY}/                # 按照年建立文件夹 (如 2026)
          |   |   |   |--{MM}/              # 按照月份建立文件夹 (如 09)
          |   |   |   |   |--{DD}/          # 按照日建立文件夹 (如 07)，存放当日三清单
          |   |   |   |   |--Normal_Lot/    # 流水线正常批次数据文件夹
          |   |   |   |   |   |--{lot_id}/  # 按照 LOT 批次建立文件夹
          |   |   |   |   |--Rework_Lot/    # 补测数据文件夹
          |   |   |   |   |   |--{lot_id}/
          |   |--Data_Calibration/
          |   |   |--{YYYY}/
          |   |   |   |--{MM}/              # 存放标定测试汇总数据
        """
        if not date_str:
            now = datetime.datetime.now()
            year = now.strftime("%Y")
            month = now.strftime("%m")
            day = now.strftime("%d")
        else:
            clean = date_str.replace("-", "").replace("_", "")
            year = clean[:4] if len(clean) >= 4 else "2026"
            month = clean[4:6] if len(clean) >= 6 else "09"
            day = clean[6:8] if len(clean) >= 8 else "07"

        cent_root = os.path.join(self.base_output_dir, centrifuge_id)
        consolidation_root = os.path.join(cent_root, "Data_Consolidation")
        month_root = os.path.join(consolidation_root, year, month)
        daily_dir = os.path.join(month_root, day)

        # 核心架构调整：Normal_Lot 与 Rework_Lot 全部归档在同日的 daily_dir 下
        normal_lot_root = os.path.join(daily_dir, "Normal_Lot")
        normal_lot_dir = os.path.join(normal_lot_root, lot_id)

        rework_lot_root = os.path.join(daily_dir, "Rework_Lot")
        rework_lot_dir = os.path.join(rework_lot_root, lot_id)

        calibration_dir = os.path.join(cent_root, "Data_Calibration", year, month)

        paths = {
            "cent_root": cent_root,
            "consolidation_root": consolidation_root,
            "month_root": month_root,
            "daily_dir": daily_dir,
            "normal_lot_root": normal_lot_root,
            "normal_lot_dir": normal_lot_dir,
            "lot_root": normal_lot_dir,         # 兼容别名
            "rework_lot_root": rework_lot_root,
            "rework_lot_dir": rework_lot_dir,
            "rework_root": rework_lot_dir,      # 兼容别名
            "calibration_dir": calibration_dir,
            "year": year,
            "month": month,
            "day": day,
        }

        for k, p in paths.items():
            if k not in ("year", "month", "day"):
                os.makedirs(p, exist_ok=True)

        return paths

    def classify_devices(
        self,
        tested_devices: List[Dict],
        calibration_processor=None
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        对器件进行初始分流 (严格遵循图 4/8 Pass/Fail 分类与字段规范):
        - normal_list: 双轴数据齐全且标定通过
        - rework_list: 单轴缺失或接触不良，等待复测 (记录工位, LOT, CAN_ID, 通道号0x25X, UID, 器件编号, 区分Positive/Negative, 状态:Fail)
        - abnormal_list: 报文错误、通信故障、硬件损坏或 Span 门禁拦截
        """
        normal_list = []
        rework_list = []
        abnormal_list = []

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        board_channel_map = {1: "0x25A", 2: "0x25B", 3: "0x25C", 4: "0x25D"}
        board_fixture_type = {1: "N", 2: "N", 3: "P", 4: "P"}

        for dev in tested_devices:
            dev_code = dev.get("device_code_11", "00000000000")
            uid = dev.get("uid_32", "-")
            board_id = dev.get("board_id", 0)
            sensor_id = dev.get("sensor_id", 0)
            raw_fix = str(dev.get("fixture_type", board_fixture_type.get(board_id, "N"))).strip().upper()
            # 需求 8: 25C/25D 为正向区域(P)，25A/25B 为负向区域(N)；工装类型改为 P/N
            fixture = "P" if raw_fix in ("P", "POSITIVE", "B") else "N"
            slot_idx = dev.get("slot_index", (board_id - 1) * 6 + sensor_id - 1 if board_id else 0)
            lot_id = dev.get("lot_id", "LOT1")
            can_id = dev.get("can_id", f"0x1{board_id}{sensor_id}")
            channel_code = board_channel_map.get(board_id, f"0x25{chr(64+board_id) if 1<=board_id<=4 else 'A'}")
            fixture_desc = "Positive" if fixture == "P" else "Negative"

            # 1. 致命硬件或通信异常检查
            if not dev.get("is_valid", False):
                abnormal_list.append({
                    "工位": slot_idx,
                    "LOT编号": lot_id,
                    "CAN_ID": can_id,
                    "通道号": channel_code,
                    "16位芯片器件码": uid,
                    "芯片编号_HEX": dev_code,
                    "器具类型区分": fixture_desc,
                    "工装类别": fixture,
                    "供电板编号": board_id,
                    "通道编号": sensor_id,
                    "异常类型": "通信或链路异常",
                    "原始错误信息": dev.get("status_msg", "通信异常"),
                    "采集状态": "Fail",
                    "记录时间": now_str,
                })
                continue

            ax1 = dev.get("Axis1_Mean")
            ax2 = dev.get("Axis2_Mean")

            # 2. 单轴缺失检查 -> 汇入 Rework (记录图 4/8 要求的规范字段)
            if ax1 is None and ax2 is not None:
                rework_list.append({
                    "工位": slot_idx,
                    "LOT编号": lot_id,
                    "CAN_ID": can_id,
                    "通道号": channel_code,
                    "16位芯片器件码": uid,
                    "芯片编号_HEX": dev_code,
                    "器具类型区分": fixture_desc,
                    "工装类别": fixture,
                    "供电板编号": board_id,
                    "通道编号": sensor_id,
                    "缺失轴向": "Axis1",
                    "采集状态": "Fail",
                    "失败原因": "缺失 Axis1 数据",
                    "复测状态": "Pending",
                    "记录时间": now_str,
                })
                continue
            elif ax2 is None and ax1 is not None:
                rework_list.append({
                    "工位": slot_idx,
                    "LOT编号": lot_id,
                    "CAN_ID": can_id,
                    "通道号": channel_code,
                    "16位芯片器件码": uid,
                    "芯片编号_HEX": dev_code,
                    "器具类型区分": fixture_desc,
                    "工装类别": fixture,
                    "供电板编号": board_id,
                    "通道编号": sensor_id,
                    "缺失轴向": "Axis2",
                    "采集状态": "Fail",
                    "失败原因": "缺失 Axis2 数据",
                    "复测状态": "Pending",
                    "记录时间": now_str,
                })
                continue
            elif ax1 is None and ax2 is None:
                rework_list.append({
                    "工位": slot_idx,
                    "LOT编号": lot_id,
                    "CAN_ID": can_id,
                    "通道号": channel_code,
                    "16位芯片器件码": uid,
                    "芯片编号_HEX": dev_code,
                    "器具类型区分": fixture_desc,
                    "工装类别": fixture,
                    "供电板编号": board_id,
                    "通道编号": sensor_id,
                    "缺失轴向": "Axis1+Axis2",
                    "采集状态": "Fail",
                    "失败原因": "双轴数据均缺失",
                    "复测状态": "Pending",
                    "记录时间": now_str,
                })
                continue

            # 3. 双轴均有数据 -> 依据工装 (P / N) 进行物理受力极性校验门禁
            # 正向工装 P (25C, 25D): Axis1 正向 (>0), Axis2 负向 (<0)
            # 负向工装 N (25A, 25B): Axis1 负向 (<0), Axis2 正向 (>0)
            if fixture == "P":
                if ax1 <= 0 or ax2 >= 0:
                    abnormal_list.append({
                        "工位": slot_idx,
                        "LOT编号": lot_id,
                        "CAN_ID": can_id,
                        "通道号": channel_code,
                        "16位芯片器件码": uid,
                        "芯片编号_HEX": dev_code,
                        "器具类型区分": fixture_desc,
                        "工装类别": fixture,
                        "供电板编号": board_id,
                        "通道编号": sensor_id,
                        "异常类型": "物理极性反转/工装异常",
                        "原始错误信息": f"正向区(P)极性不符: Axis1={ax1:.1f}(需>0), Axis2={ax2:.1f}(需<0)",
                        "采集状态": "Fail",
                        "记录时间": now_str,
                    })
                    continue
                pos_val = ax1
                neg_val = ax2
            else:
                if ax2 <= 0 or ax1 >= 0:
                    abnormal_list.append({
                        "工位": slot_idx,
                        "LOT编号": lot_id,
                        "CAN_ID": can_id,
                        "通道号": channel_code,
                        "16位芯片器件码": uid,
                        "芯片编号_HEX": dev_code,
                        "器具类型区分": fixture_desc,
                        "工装类别": fixture,
                        "供电板编号": board_id,
                        "通道编号": sensor_id,
                        "异常类型": "物理极性反转/工装异常",
                        "原始错误信息": f"负向区(N)极性不符: Axis2={ax2:.1f}(需>0), Axis1={ax1:.1f}(需<0)",
                        "采集状态": "Fail",
                        "记录时间": now_str,
                    })
                    continue
                pos_val = ax2
                neg_val = ax1

            if calibration_processor:
                try:
                    adj_dec, adj_hex, span = calibration_processor.calculate_adj(pos_val, neg_val)
                    normal_list.append({
                        "工位": slot_idx,
                        "LOT编号": lot_id,
                        "CAN_ID": can_id,
                        "通道号": channel_code,
                        "16位芯片器件码": uid,
                        "芯片编号_HEX": dev_code,
                        "器具类型区分": fixture_desc,
                        "工装类别": fixture,
                        "供电板编号": board_id,
                        "通道编号": sensor_id,
                        "Axis1_均值": f"{ax1:.2f}",
                        "Axis2_均值": f"{ax2:.2f}",
                        "Span": f"{span:.2f}",
                        "ADJ_HEX": adj_hex,
                        "状态": "Passed",
                        "完成时间": now_str,
                    })
                except Exception as e:
                    abnormal_list.append({
                        "工位": slot_idx,
                        "LOT编号": lot_id,
                        "CAN_ID": can_id,
                        "通道号": channel_code,
                        "16位芯片器件码": uid,
                        "芯片编号_HEX": dev_code,
                        "器具类型区分": fixture_desc,
                        "工装类别": fixture,
                        "供电板编号": board_id,
                        "通道编号": sensor_id,
                        "异常类型": "Span门禁或标定异常",
                        "原始错误信息": str(e),
                        "采集状态": "Fail",
                        "记录时间": now_str,
                    })
            else:
                normal_list.append({
                    "工位": slot_idx,
                    "LOT编号": lot_id,
                    "CAN_ID": can_id,
                    "通道号": channel_code,
                    "16位芯片器件码": uid,
                    "芯片编号_HEX": dev_code,
                    "器具类型区分": fixture_desc,
                    "工装类别": fixture,
                    "供电板编号": board_id,
                    "通道编号": sensor_id,
                    "Axis1_均值": f"{ax1:.2f}",
                    "Axis2_均值": f"{ax2:.2f}",
                    "Span": "-",
                    "ADJ_HEX": "-",
                    "状态": "Passed",
                    "完成时间": now_str,
                })

        return normal_list, rework_list, abnormal_list

    def export_tri_lists(
        self,
        export_dir: str,
        timestamp: str,
        normal_list: List[Dict],
        rework_list: List[Dict],
        abnormal_list: List[Dict],
        lot_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        导出当日三份清单 CSV 文件到日目录 (图 4/8、图 5/8 规范):
        - Normal_List_{timestamp}.csv # 当日正常测试完成后的器件
        - Rework_List_{timestamp}.csv # 当日待复测器件
        - AbnormalFunction_List_{timestamp}.csv # 当日数据异常器件
        需求 13: 同一个 lot 重复点击只保留最新日期的，清理历史旧文件
        """
        os.makedirs(export_dir, exist_ok=True)

        # 清理该目录中旧时间戳的三清单文件，确保只保留最新
        try:
            for f in os.listdir(export_dir):
                if f.endswith(".csv") and (
                    f.startswith("Normal_List_") or
                    f.startswith("Rework_List_") or
                    f.startswith("AbnormalFunction_List_")
                ):
                    old_path = os.path.join(export_dir, f)
                    os.remove(old_path)
        except Exception:
            pass

        paths = {
            "normal": os.path.join(export_dir, f"Normal_List_{timestamp}.csv"),
            "rework": os.path.join(export_dir, f"Rework_List_{timestamp}.csv"),
            "abnormal": os.path.join(export_dir, f"AbnormalFunction_List_{timestamp}.csv"),
        }

        self._write_csv(paths["normal"], normal_list)
        self._write_csv(paths["rework"], rework_list)
        self._write_csv(paths["abnormal"], abnormal_list)

        return paths

    def export_calibration_file(
        self,
        calibration_dir: str,
        timestamp: str,
        lot_id: str,
        normal_list: List[Dict],
        centrifuge_id: str = "Centrifuge1"
    ) -> str:
        """
        导出当日/当批次标定测试汇总数据 (图 1/8 脚本 3、图 5/8):
        CrashSensor_Centrifuge1_Calibration_{年月日时分秒}_{LOT{n}}.csv
        需求 13: 同一个 LOT 内只保留最新的标定汇总文件
        """
        os.makedirs(calibration_dir, exist_ok=True)

        # 清理同一 lot_id 历史版本
        try:
            prefix = f"CrashSensor_{centrifuge_id}_Calibration_"
            suffix = f"_{lot_id}.csv"
            for f in os.listdir(calibration_dir):
                if f.startswith(prefix) and f.endswith(suffix):
                    os.remove(os.path.join(calibration_dir, f))
        except Exception:
            pass

        filename = f"CrashSensor_{centrifuge_id}_Calibration_{timestamp}_{lot_id}.csv"
        out_path = os.path.join(calibration_dir, filename)
        self._write_csv(out_path, normal_list)
        return out_path

    def export_intermediate_lot_files(
        self,
        lot_dir: str,
        timestamp: str,
        axis: str,
        id_check_rows: List[Dict],
        processed_data1_rows: List[Dict],
        processed_data2_rows: List[Dict],
        centrifuge_id: str = "Centrifuge1"
    ) -> Dict[str, str]:
        """
        导出 LOT 批次内的中间处理结果文件 (图 1/8 脚本 2、图 5/8):
        - CrashSensor_Centrifuge1_IdCheck_Axis{1/2}_{年月日时分秒}.csv
        - CrashSensor_Centrifuge1_ProcessedData1_Axis{1/2}_{年月日时分秒}.csv
        - CrashSensor_Centrifuge1_ProcessedData2_Axis{1/2}_{年月日时分秒}.csv
        - Lot_Summary_Axis{1/2}.csv
        """
        os.makedirs(lot_dir, exist_ok=True)
        # 清理同一轴向的旧中间文件
        try:
            for f in os.listdir(lot_dir):
                if f.startswith(f"CrashSensor_{centrifuge_id}_IdCheck_{axis}_") or \
                   f.startswith(f"CrashSensor_{centrifuge_id}_ProcessedData1_{axis}_") or \
                   f.startswith(f"CrashSensor_{centrifuge_id}_ProcessedData2_{axis}_"):
                    os.remove(os.path.join(lot_dir, f))
        except Exception:
            pass

        paths = {
            "id_check": os.path.join(lot_dir, f"CrashSensor_{centrifuge_id}_IdCheck_{axis}_{timestamp}.csv"),
            "proc1": os.path.join(lot_dir, f"CrashSensor_{centrifuge_id}_ProcessedData1_{axis}_{timestamp}.csv"),
            "proc2": os.path.join(lot_dir, f"CrashSensor_{centrifuge_id}_ProcessedData2_{axis}_{timestamp}.csv"),
            "summary": os.path.join(lot_dir, f"Lot_Summary_{axis}.csv"),
        }
        self._write_csv(paths["id_check"], id_check_rows)
        self._write_csv(paths["proc1"], processed_data1_rows)
        self._write_csv(paths["proc2"], processed_data2_rows)
        self._write_csv(paths["summary"], processed_data2_rows)
        return paths

    def export_axis_processed_data1_and_idcheck(
        self,
        lot_dir: str,
        timestamp: str,
        axis: str,
        parsed_slots: Dict[int, Any],
        series_map: Dict[int, List[float]],
        paired_neg_series_map: Optional[Dict[int, List[float]]] = None,
        centrifuge_id: str = "Centrifuge1"
    ) -> Dict[str, str]:
        """
        按照需求 11 规范导出第一次处理后生成的两份关键 CSV 文件:
        (1) 测试数据：CrashSensor_Centrifuge1_ProcessedData1_Axis{1/2}_{年月日时分秒}.csv
        (2) ID检测数据：CrashSensor_Centrifuge1_IdCheck_Axis{1/2}_{年月日时分秒}.csv
        需求 8: 工装类型改用 P/N
        需求 13: 同一 lot 内只保留最新生成的文件
        """
        os.makedirs(lot_dir, exist_ok=True)
        try:
            for f in os.listdir(lot_dir):
                if f.startswith(f"CrashSensor_{centrifuge_id}_IdCheck_{axis}_") or \
                   f.startswith(f"CrashSensor_{centrifuge_id}_ProcessedData1_{axis}_"):
                    os.remove(os.path.join(lot_dir, f))
        except Exception:
            pass

        id_check_path = os.path.join(lot_dir, f"CrashSensor_{centrifuge_id}_IdCheck_{axis}_{timestamp}.csv")
        proc1_path = os.path.join(lot_dir, f"CrashSensor_{centrifuge_id}_ProcessedData1_{axis}_{timestamp}.csv")

        # 1. 组装并写入 IdCheck CSV
        id_check_rows = []
        for s in range(24):
            b_id = (s // 6) + 1
            s_id = (s % 6) + 1
            # 需求 8: 25C/25D (板3/4) 为正向 P，25A/25B (板1/2) 为负向 N
            fixture = "N" if b_id in (1, 2) else "P"
            item = parsed_slots.get(s, {})
            is_valid = item.get("is_valid", False)
            dev_code = item.get("device_code_11") or "00000000000"
            cfg29_val = item.get("cfg29_val") or 0
            cfg28_val = item.get("cfg28_val") or 0
            cfg27_val = item.get("cfg27_val") or 0

            dev_code_16 = item.get("芯片器件码")
            if not dev_code_16:
                if cfg29_val or cfg28_val or cfg27_val:
                    dev_code_16 = f"{cfg29_val:04X}{cfg28_val:04X}{cfg27_val:04X}"
                else:
                    dev_code_16 = dev_code

            id_check_rows.append({
                "工位": s,
                "供电板编号": b_id,
                "通道编号": s_id,
                "CAN_ID": f"0x1{b_id}{s_id}",
                "通道号_0x25X": f"0x25{chr(64+b_id)}",
                "工装类别": fixture,
                "芯片器件码": dev_code_16 if is_valid else "-",
                "芯片编号_HEX": dev_code if is_valid else "00000000000",
                "完整32位Hex_UID": item.get("uid_32", "-") if is_valid else "-",
                "生产日期_真实日期": item.get("生产日期_真实日期", "-") if is_valid else "-",
                "状态": "Valid" if is_valid else "Empty/Error",
            })
        self._write_csv(id_check_path, id_check_rows)

        # 2. 组装并写入 ProcessedData1 CSV (时序加速度矩阵)
        cols = []
        col_data = []

        for s in range(24):
            item = parsed_slots.get(s, {})
            if not item.get("is_valid"):
                continue
            dev_code = item.get("芯片器件码") or item.get("device_code_11") or f"Chip{s}"
            pos_series = series_map.get(s, [])
            neg_series = paired_neg_series_map.get(s, []) if paired_neg_series_map else []

            # 正向数据列
            if pos_series:
                cols.append(f"{dev_code}_+160g")
                col_data.append(pos_series)

            # 负向数据列 (若有则添加，若缺失则天然兼容仅保留 +160g)
            if neg_series:
                cols.append(f"{dev_code}_-160g")
                col_data.append(neg_series)

        if cols:
            max_len = max((len(c) for c in col_data), default=0)
            with open(proc1_path, mode="w", newline="", encoding="utf-8-sig") as f_out:
                writer = csv.writer(f_out)
                writer.writerow(cols)
                for r_idx in range(max_len):
                    row_vals = []
                    for c_list in col_data:
                        if r_idx < len(c_list):
                            val = c_list[r_idx]
                            row_vals.append(int(round(val)) if isinstance(val, (int, float)) else val)
                        else:
                            row_vals.append("")
                    writer.writerow(row_vals)
        else:
            with open(proc1_path, mode="w", newline="", encoding="utf-8-sig") as f_out:
                f_out.write("No_Valid_Data\n")

        return {"id_check": id_check_path, "proc1": proc1_path}

    def update_rework_to_normal_closure(
        self,
        rework_csv_path: str,
        normal_csv_path: str,
        resolved_device_codes: List[str],
        resolved_details: List[Dict]
    ):
        """
        良率闭环状态流转:
        当芯片在 Rework_Lot 中复测合格:
        1. 在 Rework_List 中将其状态更新为 Resolved
        2. 追加写入 Normal_List，确保当天结项良率统计精确闭环
        """
        if os.path.exists(rework_csv_path):
            df_rework = pd.read_csv(rework_csv_path, dtype=str)
            if "芯片编号_HEX" in df_rework.columns and "复测状态" in df_rework.columns:
                # 统一为字符串比对
                resolved_strs = [str(x).strip() for x in resolved_device_codes]
                mask = df_rework["芯片编号_HEX"].astype(str).str.strip().isin(resolved_strs)
                df_rework.loc[mask, "复测状态"] = "Resolved"
                df_rework.to_csv(rework_csv_path, index=False, encoding="utf-8-sig")

        if resolved_details:
            df_new_normal = pd.DataFrame(resolved_details)
            if os.path.exists(normal_csv_path):
                df_orig = pd.read_csv(normal_csv_path, dtype=str)
                combined = pd.concat([df_orig, df_new_normal], ignore_index=True)
                # 去重保留最新
                if "芯片编号_HEX" in combined.columns:
                    combined.drop_duplicates(subset=["芯片编号_HEX"], keep="last", inplace=True)
                combined.to_csv(normal_csv_path, index=False, encoding="utf-8-sig")
            else:
                df_new_normal.to_csv(normal_csv_path, index=False, encoding="utf-8-sig")

    @staticmethod
    def _write_csv(path: str, data: List[Dict]):
        if not data:
            # 写入空表头占位
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write("提示\n无记录\n")
            return

        keys = list(data[0].keys())
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)

    @staticmethod
    def get_daily_yield_file(daily_dir: str, date_str: Optional[str] = None) -> str:
        """获取当日良率断点记录 CSV 路径: {daily_dir}/Daily_Yield_Stats_{YYYYMMDD}.csv (需求 11(2))"""
        if not date_str:
            d_str = datetime.datetime.now().strftime("%Y%m%d")
        else:
            d_str = date_str.replace("-", "").replace("_", "")
        return os.path.join(daily_dir, f"Daily_Yield_Stats_{d_str}.csv")

    def load_daily_yield(self, daily_dir: str, date_str: Optional[str] = None) -> Dict[str, Any]:
        """从当日断点 CSV 加载历史累计 Pass/Fail 数据，实现断点记录与断点恢复"""
        csv_file = self.get_daily_yield_file(daily_dir, date_str)
        if not os.path.exists(csv_file):
            return {"total_pass": 0, "total_fail": 0, "batches": 0, "file_path": csv_file}
        try:
            df = pd.read_csv(csv_file)
            if not df.empty:
                last_row = df.iloc[-1]
                p = int(last_row.get("累计Pass", 0))
                fl = int(last_row.get("累计Fail", 0))
                tot = p + fl
                yr = (p / tot * 100.0) if tot > 0 else 0.0
                return {
                    "total_pass": p,
                    "total_fail": fl,
                    "yield_rate": yr,
                    "batches": len(df),
                    "file_path": csv_file,
                }
        except Exception:
            pass
        return {"total_pass": 0, "total_fail": 0, "yield_rate": 0.0, "batches": 0, "file_path": csv_file}

    def record_batch_yield(
        self,
        daily_dir: str,
        lot_id: str,
        batch_pass: int,
        batch_fail: int,
        date_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """记录单批次完成后的良率并追加更新当日断点 CSV (无需统计待复测数量)"""
        current = self.load_daily_yield(daily_dir, date_str)
        new_pass = current["total_pass"] + batch_pass
        new_fail = current["total_fail"] + batch_fail
        total = new_pass + new_fail
        yield_rate = (new_pass / total * 100.0) if total > 0 else 0.0

        csv_file = self.get_daily_yield_file(daily_dir, date_str)
        now_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row = {
            "记录时间": now_time,
            "批次LOT": lot_id,
            "本批Pass": batch_pass,
            "本批Fail": batch_fail,
            "累计Pass": new_pass,
            "累计Fail": new_fail,
            "当日综合良率": f"{yield_rate:.1f}%",
        }

        os.makedirs(daily_dir, exist_ok=True)
        file_exists = os.path.exists(csv_file)
        df_new = pd.DataFrame([row])
        if file_exists:
            df_new.to_csv(csv_file, mode="a", header=False, index=False, encoding="utf-8-sig")
        else:
            df_new.to_csv(csv_file, mode="w", header=True, index=False, encoding="utf-8-sig")

        return {
            "total_pass": new_pass,
            "total_fail": new_fail,
            "yield_rate": yield_rate,
            "batches": current["batches"] + 1,
            "file_path": csv_file,
        }
