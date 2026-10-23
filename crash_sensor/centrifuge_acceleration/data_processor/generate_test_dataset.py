"""
CrashSensor 离心机测试全套测试数据生成器
严格遵循原厂需求文档 (图 1/8 至图 8/8，特别是图 4/8 与图 5/8 目录结构规范)
生成高仿真生产测试数据集，存放在 data_conlidation 目录下，供分步验证与全流程测试使用。
"""

import os
import sys
import csv
import shutil
import datetime
import numpy as np

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_CONLIDATION_DIR = os.path.join(BASE_DIR, "data_conlidation")

sys.path.insert(0, os.path.join(BASE_DIR, "data_processor"))
from processor.can_data_parser import CentrifugeCANParser
from processor.result_consolidator import ResultConsolidator


def build_64byte_payload(reg_map: dict, acc_signed_val: int = 0, is_empty: bool = False, is_broken: bool = False) -> str:
    """
    构造 64 字节 CG904 CAN 报文负载 (32 组 [状态, 数据])
    """
    if is_empty:
        return " ".join(["01", "f0"] * 32)
    if is_broken:
        return " ".join(["01", "00"] * 32)

    # 16 个有效 8-bit 寄存器顺序 (与 device_code_scan.py 完全一致)
    reg_seq = [
        "31", "30",  # CFG26_1
        "2E", "2D",  # CFG27_1 (芯片编号)
        "2B", "2A",  # CFG28_1 (生产日期)
        "28", "27",  # CFG29_1 (备用序号与上位机编号)
        "25", "24",  # CFG30_1
        "22", "21",  # CFG31_1
        "1F", "1E",  # CFG32_1
        "1C", "1B",  # CFG33_1
    ]

    clean_nibbles = []
    for reg_name in reg_seq:
        val = reg_map.get(reg_name, 0) & 0xFF
        clean_nibbles.append((val >> 4) & 0x0F)
        clean_nibbles.append(val & 0x0F)

    # 将 acc_signed_val (+320 或 -320) 转为 10-bit 原始码 (0 ~ 1023)
    raw_acc = int(acc_signed_val) if acc_signed_val >= 0 else int(1024 + acc_signed_val)
    raw_acc = max(0, min(1023, raw_acc))
    acc_high = (raw_acc >> 8) & 0x03
    acc_low = raw_acc & 0xFF

    tokens = []
    for i in range(32):
        tokens.append("02")  # 正常通信状态字节
        if i == 0:
            tokens.append(f"{acc_high:02X}")
        elif i == 1:
            tokens.append(f"{acc_low:02X}")
        else:
            nibble = clean_nibbles[i]
            tokens.append(f"{nibble:02X}")

    return " ".join(tokens)


def build_25x_board_payload(
    board_id: int,
    chip_info: dict,
    frame_idx: int,
    signals: dict,
    broken_slots: set,
    empty_slots: set,
    missing_slots: set
) -> str:
    """
    构造 0x25X (0x25A ~ 0x25D) 供电板的 48 字节加速度报文 (严格遵循图 6/8 与图 7/8 工业标准)
    每块板 6 路 PSI5 通道，每通道 3 个 timeslot，每 timeslot 2 字节:
    - timeslot 1: 高八位 低八位 (有效传感器加速度，10-bit 补码编码)
    - timeslot 2: 01 f0 (未使用)
    - timeslot 3: 01 f0 (未使用)
    末尾填充 12 字节保留位 (02 10 02 10 02 10 02 1E 02 10 02 10)，总计 48 字节。
    """
    tokens = []
    for s_id in range(1, 7):
        slot = (board_id - 1) * 6 + (s_id - 1)
        if slot in empty_slots:
            ts1 = "01 f0"
        elif slot in broken_slots:
            ts1 = "01 00"
        elif slot in missing_slots:
            ts1 = "01 f0"
        else:
            sig = signals[slot]
            curr_acc = int(round(sig[frame_idx]))
            raw_10bit = curr_acc if curr_acc >= 0 else 1024 + curr_acc
            raw_10bit = max(0, min(1023, raw_10bit))
            h = (raw_10bit >> 8) & 0xFF
            l = raw_10bit & 0xFF
            ts1 = f"{h:02X} {l:02X}"
        ts2 = "01 f0"
        ts3 = "01 f0"
        tokens.extend([ts1, ts2, ts3])

    # 12 字节保留位 (6 组 2-byte: 02 10 02 10 02 10 02 1e 02 10 02 10，完全对齐图 7/8 报文示例)
    tokens.extend(["02 10", "02 10", "02 10", "02 1E", "02 10", "02 10"])
    return " ".join(tokens)


def build_register_map_for_chip(chip_sn: int, mfg_date_code: int = 0x0020, host_id: int = 0x0003) -> dict:
    """构建单颗芯片的 16 个底层寄存器映射表"""
    reg_map = {
        "31": 0x00, "30": 0x01,                             # CFG26
        "2E": (chip_sn >> 8) & 0xFF, "2D": chip_sn & 0xFF,  # CFG27 (芯片编号)
        "2B": (mfg_date_code >> 8) & 0xFF, "2A": mfg_date_code & 0xFF,  # CFG28 (日期)
        "28": (host_id >> 8) & 0xFF, "27": host_id & 0xFF,  # CFG29 (上位机)
        "25": 0x10, "24": 0x2A,                             # CFG30 (版本v1.0)
        "22": 0x00, "21": 0x00,                             # CFG31
        "1F": 0x00, "1E": 0x00,                             # CFG32
        "1C": 0x00, "1B": 0x00,                             # CFG33
    }
    return reg_map


def generate_time_series_data(num_points: int = 120, steady_val: float = 320.0, ramp_points: int = 25) -> np.ndarray:
    """生成带加减速过渡态与稳态的高仿真加速度波形 (包含启动静止、升速沿、稳态平台、降速沿、停止静止)"""
    signal = np.zeros(num_points)
    p1 = 10
    p2 = p1 + ramp_points
    p4 = num_points - 10
    p3 = p4 - ramp_points

    if p3 > p2:
        signal[p1:p2] = np.linspace(0, steady_val, p2 - p1)
        noise = np.random.normal(0, 0.8, p3 - p2)
        signal[p2:p3] = steady_val + noise
        signal[p3:p4] = np.linspace(steady_val, 0, p4 - p3)
    else:
        signal[:ramp_points] = np.linspace(0, steady_val, ramp_points)
        signal[ramp_points:] = steady_val + np.random.normal(0, 0.8, num_points - ramp_points)
    return signal


def create_all_test_datasets():
    print(f"[1/6] 清理旧目录并初始化标准工业目录架构: {DATA_CONLIDATION_DIR}...")
    # 彻底清理非标旧目录 (如 202609开头的非标文件夹)
    if os.path.exists(DATA_CONLIDATION_DIR):
        for entry in os.listdir(DATA_CONLIDATION_DIR):
            entry_path = os.path.join(DATA_CONLIDATION_DIR, entry)
            if os.path.isdir(entry_path) and entry not in ("Centrifuge1", "Centrifuge2", "MTP_DATA"):
                shutil.rmtree(entry_path, ignore_errors=True)
                print(f" -> 已清理非标旧目录: {entry}")

    consolidator = ResultConsolidator(base_output_dir=DATA_CONLIDATION_DIR)
    ts_str = "20260907_120000"
    date_str = "20260907"
    lot_id = "LOT1"

    # 初始化 Centrifuge1 与 Centrifuge2 标准目录
    dirs_c1 = consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge1")
    dirs_c2 = consolidator.organize_directories(date_str=date_str, lot_id=lot_id, centrifuge_id="Centrifuge2")

    mtp_before_dir = os.path.join(DATA_CONLIDATION_DIR, "MTP_DATA", "before-calibration")
    mtp_after_dir = os.path.join(DATA_CONLIDATION_DIR, "MTP_DATA", "after-calibration")
    os.makedirs(mtp_before_dir, exist_ok=True)
    os.makedirs(mtp_after_dir, exist_ok=True)

    can_parser = CentrifugeCANParser()

    # 预计算 24 个工位的器件信息
    board_channel_map = {1: "0x25A", 2: "0x25B", 3: "0x25C", 4: "0x25D"}
    board_fixture_desc = {1: "Negative", 2: "Negative", 3: "Positive", 4: "Positive"}

    chip_info = {}
    for s in range(24):
        b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
        fixture = "A" if b_id in (1, 2) else "B"
        sn = s + 1
        reg_map = build_register_map_for_chip(sn)
        dev_code = can_parser.extract_device_code_from_registers(reg_map)
        chip_info[s] = {
            "slot": s,
            "board_id": b_id,
            "sensor_id": s_id,
            "can_id": f"0x1{b_id}{s_id}",
            "channel_code": board_channel_map.get(b_id, "0x25A"),
            "fixture_desc": board_fixture_desc.get(b_id, "Negative"),
            "fixture": fixture,
            "sn": sn,
            "reg_map": reg_map,
            "dev_code": dev_code,
            "uid": f"0001{sn:04X}00200003102A000000000000",
        }

    print("[2/6] 生成 24 颗芯片的 MTP before-calibration 模板与 after-calibration 示例...")
    for s in range(24):
        code = chip_info[s]["dev_code"]
        mtp_file = os.path.join(mtp_before_dir, f"{code}.txt")
        content = f"""// MTP Configuration Template Before Calibration
// Device Code: {code}, Slot: {s}
REG_ADJ_MIN  5b 5a  DATA: 16h0
REG_ADJ_MAX  58 57  DATA: 16h0
REG_ADJ_MAXH 55 54  DATA: 16h3c10
CTRL_REG     CFG22  VAL: 16h0010
CFG26_VAL    31 30  DATA: 16h0001
CFG27_VAL    2e 2d  DATA: 16h{chip_info[s]['sn']:04X}
CFG28_VAL    2b 2a  DATA: 16h0020
CFG29_VAL    28 27  DATA: 16h0003
"""
        with open(mtp_file, "w", encoding="utf-8") as f:
            f.write(content)

        # 按照图 1/8 规范命名: {code}-after-calibration.txt
        after_file = os.path.join(mtp_after_dir, f"{code}-after-calibration.txt")
        content_after = content.replace("DATA: 16h0", "DATA: 16hFFFF").replace("16h0010", "16h2010")
        with open(after_file, "w", encoding="utf-8") as f:
            f.write(content_after)

    print("[3/6] 生成 Centrifuge1 Normal_Lot (LOT1) 原始数据与各中间文件...")
    num_frames = 120
    axis1_file = os.path.join(dirs_c1["normal_lot_dir"], f"CrashSensor_Centrifuge1_OriginalData_Axis1_{ts_str}.csv")
    axis2_file = os.path.join(dirs_c1["normal_lot_dir"], f"CrashSensor_Centrifuge1_OriginalData_Axis2_{ts_str}.csv")

    # 1. 预先计算 24 槽位在 Axis1 / Axis2 下的动态波形
    signals_a1 = {
        s: generate_time_series_data(num_frames, 320.0 if chip_info[s]["fixture"] == "A" else -320.0)
        for s in range(24)
    }
    signals_a2 = {
        s: generate_time_series_data(num_frames, -320.0 if chip_info[s]["fixture"] == "A" else 320.0)
        for s in range(24)
    }

    # 2. 生成 Axis1 原始 CSV (前 24 条为 0x1XX ID 扫描/寄存器读取，后续为 0x25A~0x25D 动态加速度)
    rows_axis1 = []
    # (a) 前 24 条 0x1XX 芯片写数据/读 UID 报文
    for s in range(24):
        info = chip_info[s]
        if s == 23:
            payload = build_64byte_payload({}, is_empty=True)
        elif s == 5:
            payload = build_64byte_payload({}, is_broken=True)
        else:
            payload = build_64byte_payload(info["reg_map"])
        rows_axis1.append({"MAKE_CAN_ID(HEX)": info["can_id"], "DATA(HEX)": payload})

    # (b) 后续离心机运转期间的 0x25X 动态加速度报文 (Slot 10 缺测 Axis1)
    for frame_idx in range(num_frames):
        for b_id in range(1, 5):
            can_id = board_channel_map[b_id]
            payload = build_25x_board_payload(
                board_id=b_id,
                chip_info=chip_info,
                frame_idx=frame_idx,
                signals=signals_a1,
                broken_slots={5},
                empty_slots={23},
                missing_slots={10}
            )
            rows_axis1.append({"MAKE_CAN_ID(HEX)": can_id, "DATA(HEX)": payload})

    with open(axis1_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["MAKE_CAN_ID(HEX)", "DATA(HEX)"])
        writer.writeheader()
        writer.writerows(rows_axis1)

    # 3. 生成 Axis2 原始 CSV (前 24 条为 0x1XX，后续为 0x25X，Slot 4 缺测 Axis2)
    rows_axis2 = []
    # (a) 前 24 条 0x1XX 报文
    for s in range(24):
        info = chip_info[s]
        if s == 23:
            payload = build_64byte_payload({}, is_empty=True)
        elif s == 5:
            payload = build_64byte_payload({}, is_broken=True)
        else:
            payload = build_64byte_payload(info["reg_map"])
        rows_axis2.append({"MAKE_CAN_ID(HEX)": info["can_id"], "DATA(HEX)": payload})

    # (b) 后续 0x25X 动态加速度报文
    for frame_idx in range(num_frames):
        for b_id in range(1, 5):
            can_id = board_channel_map[b_id]
            payload = build_25x_board_payload(
                board_id=b_id,
                chip_info=chip_info,
                frame_idx=frame_idx,
                signals=signals_a2,
                broken_slots={5},
                empty_slots={23},
                missing_slots={4}
            )
            rows_axis2.append({"MAKE_CAN_ID(HEX)": can_id, "DATA(HEX)": payload})

    with open(axis2_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["MAKE_CAN_ID(HEX)", "DATA(HEX)"])
        writer.writeheader()
        writer.writerows(rows_axis2)

    # 生成规范中的中间文件: IdCheck, ProcessedData1, ProcessedData2, Lot_Summary (图 1/8 脚本 2、图 5/8)
    for axis, a_rows in [("Axis1", rows_axis1), ("Axis2", rows_axis2)]:
        id_check_rows = []
        proc1_rows = []
        proc2_rows = []
        summary_rows = []
        for s in range(24):
            info = chip_info[s]
            if s == 23:
                continue
            is_valid = (s != 5) and (s != 10 if axis == "Axis1" else s != 4)
            val = (312.5 if info["fixture"] == "A" else -312.5) if axis == "Axis1" else (-312.5 if info["fixture"] == "A" else 312.5)
            val_str = f"{val:.2f}" if is_valid else "-"

            id_check_rows.append({
                "工位": s,
                "供电板编号": info["board_id"],
                "通道编号": info["sensor_id"],
                "CAN_ID": info["can_id"],
                "通道号_0x25X": info["channel_code"],
                "芯片编号_HEX": info["dev_code"] if is_valid else "00000000000",
                "完整32位Hex_UID": info["uid"] if is_valid else "-",
                "状态": "Valid" if is_valid else "Abnormal",
            })
            proc1_rows.append({
                "工位": s,
                "芯片编号_HEX": info["dev_code"] if is_valid else "00000000000",
                "稳态读数_LSB": val_str,
                "稳态均值_LSB": val_str,
                "稳态标准差_LSB": "0.82" if is_valid else "-",
                "状态": "Passed" if is_valid else "Fail",
            })
            proc2_rows.append({
                "工位": s,
                "芯片编号_HEX": info["dev_code"] if is_valid else "00000000000",
                "Axis_均值": val_str,
                "状态": "Passed" if is_valid else "Fail",
            })
            summary_rows.append({
                "工位": s,
                "CAN_ID": info["can_id"],
                "芯片编号_HEX": info["dev_code"] if is_valid else "00000000000",
                "状态": "Passed" if is_valid else "Fail",
                "均值": val_str,
            })

        consolidator.export_intermediate_lot_files(
            dirs_c1["normal_lot_dir"], ts_str, axis, id_check_rows, proc1_rows, proc2_rows, centrifuge_id="Centrifuge1"
        )

    print("[4/6] 生成 Centrifuge1 Rework_Lot (LOT1) 补测原始数据与各中间文件...")
    rework_axis1_file = os.path.join(dirs_c1["rework_lot_dir"], f"CrashSensor_Centrifuge1_OriginalData_Axis1_{ts_str}.csv")
    rework_axis2_file = os.path.join(dirs_c1["rework_lot_dir"], f"CrashSensor_Centrifuge1_OriginalData_Axis2_{ts_str}.csv")

    # 补测 Axis1 (针对 Slot 10, 板 2 工装 A, 正向 +320)
    rows_rw_a1 = []
    # (a) 前 24 条 0x1XX
    for s in range(24):
        info = chip_info[s]
        payload = build_64byte_payload(info["reg_map"]) if s == 10 else build_64byte_payload({}, is_empty=True)
        rows_rw_a1.append({"MAKE_CAN_ID(HEX)": info["can_id"], "DATA(HEX)": payload})
    # (b) 0x25X 动态波形
    signals_rw_a1 = {s: generate_time_series_data(num_frames, 320.0) for s in range(24)}
    for frame_idx in range(num_frames):
        for b_id in range(1, 5):
            can_id = board_channel_map[b_id]
            # 仅 slot 10 有效，其余为空载
            empty_s = set(range(24)) - {10}
            payload = build_25x_board_payload(b_id, chip_info, frame_idx, signals_rw_a1, set(), empty_s, set())
            rows_rw_a1.append({"MAKE_CAN_ID(HEX)": can_id, "DATA(HEX)": payload})

    with open(rework_axis1_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["MAKE_CAN_ID(HEX)", "DATA(HEX)"])
        writer.writeheader()
        writer.writerows(rows_rw_a1)

    # 补测 Axis2 (针对 Slot 4, 板 1 工装 A, 负向 -320)
    rows_rw_a2 = []
    # (a) 前 24 条 0x1XX
    for s in range(24):
        info = chip_info[s]
        payload = build_64byte_payload(info["reg_map"]) if s == 4 else build_64byte_payload({}, is_empty=True)
        rows_rw_a2.append({"MAKE_CAN_ID(HEX)": info["can_id"], "DATA(HEX)": payload})
    # (b) 0x25X 动态波形
    signals_rw_a2 = {s: generate_time_series_data(num_frames, -320.0) for s in range(24)}
    for frame_idx in range(num_frames):
        for b_id in range(1, 5):
            can_id = board_channel_map[b_id]
            # 仅 slot 4 有效，其余为空载
            empty_s = set(range(24)) - {4}
            payload = build_25x_board_payload(b_id, chip_info, frame_idx, signals_rw_a2, set(), empty_s, set())
            rows_rw_a2.append({"MAKE_CAN_ID(HEX)": can_id, "DATA(HEX)": payload})

    with open(rework_axis2_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["MAKE_CAN_ID(HEX)", "DATA(HEX)"])
        writer.writeheader()
        writer.writerows(rows_rw_a2)

    # 导出 Rework 批次中间文件
    for axis, rows_rw in [("Axis1", rows_rw_a1), ("Axis2", rows_rw_a2)]:
        rw_target_slot = 10 if axis == "Axis1" else 4
        info_rw = chip_info[rw_target_slot]
        val_rw = "312.50" if axis == "Axis1" else "-312.50"

        id_rw = [{
            "工位": rw_target_slot,
            "供电板编号": info_rw["board_id"],
            "通道编号": info_rw["sensor_id"],
            "CAN_ID": info_rw["can_id"],
            "通道号_0x25X": info_rw["channel_code"],
            "芯片编号_HEX": info_rw["dev_code"],
            "完整32位Hex_UID": info_rw["uid"],
            "状态": "Valid",
        }]
        p1_rw = [{
            "工位": rw_target_slot,
            "芯片编号_HEX": info_rw["dev_code"],
            "稳态读数_LSB": val_rw,
            "稳态均值_LSB": val_rw,
            "稳态标准差_LSB": "0.80",
            "状态": "Passed",
        }]
        p2_rw = [{
            "工位": rw_target_slot,
            "芯片编号_HEX": info_rw["dev_code"],
            "Axis_均值": val_rw,
            "状态": "Passed",
        }]
        consolidator.export_intermediate_lot_files(
            dirs_c1["rework_lot_dir"], ts_str, axis, id_rw, p1_rw, p2_rw, centrifuge_id="Centrifuge1"
        )

    print("[5/6] 生成当日日目录三清单 (Normal/Rework/Abnormal) 与月度标定汇总文件...")
    # 构造当日测试结果
    normal_rows = []
    for s in range(24):
        if s in (4, 5, 10, 23):
            continue
        info = chip_info[s]
        normal_rows.append({
            "工位": s,
            "LOT编号": lot_id,
            "CAN_ID": info["can_id"],
            "通道号": info["channel_code"],
            "16位芯片器件码": info["uid"],
            "芯片编号_HEX": info["dev_code"],
            "器具类型区分": info["fixture_desc"],
            "工装类别": info["fixture"],
            "供电板编号": info["board_id"],
            "通道编号": info["sensor_id"],
            "Axis1_均值": "312.37" if info["fixture"] == "A" else "-312.11",
            "Axis2_均值": "-312.34" if info["fixture"] == "A" else "312.29",
            "Span": "937.07",
            "ADJ_HEX": "FFFF",
            "状态": "Passed",
            "完成时间": "2026-09-07 12:05:00",
        })

    rework_rows = [
        {
            "工位": 4,
            "LOT编号": lot_id,
            "CAN_ID": chip_info[4]["can_id"],
            "通道号": chip_info[4]["channel_code"],
            "16位芯片器件码": chip_info[4]["uid"],
            "芯片编号_HEX": chip_info[4]["dev_code"],
            "器具类型区分": chip_info[4]["fixture_desc"],
            "工装类别": chip_info[4]["fixture"],
            "供电板编号": chip_info[4]["board_id"],
            "通道编号": chip_info[4]["sensor_id"],
            "缺失轴向": "Axis2",
            "采集状态": "Fail",
            "失败原因": "缺失 Axis2 数据",
            "复测状态": "Pending",
            "记录时间": "2026-09-07 12:05:00",
        },
        {
            "工位": 10,
            "LOT编号": lot_id,
            "CAN_ID": chip_info[10]["can_id"],
            "通道号": chip_info[10]["channel_code"],
            "16位芯片器件码": chip_info[10]["uid"],
            "芯片编号_HEX": chip_info[10]["dev_code"],
            "器具类型区分": chip_info[10]["fixture_desc"],
            "工装类别": chip_info[10]["fixture"],
            "供电板编号": chip_info[10]["board_id"],
            "通道编号": chip_info[10]["sensor_id"],
            "缺失轴向": "Axis1",
            "采集状态": "Fail",
            "失败原因": "缺失 Axis1 数据",
            "复测状态": "Pending",
            "记录时间": "2026-09-07 12:05:00",
        },
    ]

    abnormal_rows = [
        {
            "工位": 5,
            "LOT编号": lot_id,
            "CAN_ID": chip_info[5]["can_id"],
            "通道号": chip_info[5]["channel_code"],
            "16位芯片器件码": chip_info[5]["uid"],
            "芯片编号_HEX": "00000000000",
            "器具类型区分": chip_info[5]["fixture_desc"],
            "工装类别": chip_info[5]["fixture"],
            "供电板编号": chip_info[5]["board_id"],
            "通道编号": chip_info[5]["sensor_id"],
            "异常类型": "通信或链路异常",
            "原始错误信息": "第 1 组状态异常 (Status: 0x01)",
            "采集状态": "Fail",
            "记录时间": "2026-09-07 12:05:00",
        }
    ]

    # 导出三清单到日目录 {YYYY}/{MM}/{DD}/
    tri_paths = consolidator.export_tri_lists(dirs_c1["daily_dir"], ts_str, normal_rows, rework_rows, abnormal_rows)
    print(f" -> 已生成日目录三清单文件: {dirs_c1['daily_dir']}")

    # 导出月度标定汇总文件
    cal_file = consolidator.export_calibration_file(dirs_c1["calibration_dir"], ts_str, lot_id, normal_rows, centrifuge_id="Centrifuge1")
    print(f" -> 已生成标定汇总文件: {cal_file}")

    print("[6/6] 生成 Centrifuge2 (80g/160g 校验) 完整目录树与 ProcessedData1~3 数据...")
    c2_axis1_file = os.path.join(dirs_c2["normal_lot_dir"], f"CrashSensor_Centrifuge2_OriginalData_Axis1_{ts_str}.csv")
    c2_axis2_file = os.path.join(dirs_c2["normal_lot_dir"], f"CrashSensor_Centrifuge2_OriginalData_Axis2_{ts_str}.csv")

    rows_c2_a1 = []
    # (a) 前 24 条 0x1XX 芯片写数据/读 UID 报文
    for s in range(24):
        info = chip_info[s]
        rows_c2_a1.append({"MAKE_CAN_ID(HEX)": info["can_id"], "DATA(HEX)": build_64byte_payload(info["reg_map"])})
    # (b) 后续 0x25X 动态加速度报文
    for frame_idx in range(num_frames):
        for b_id in range(1, 5):
            can_id = board_channel_map[b_id]
            payload = build_25x_board_payload(b_id, chip_info, frame_idx, signals_a1, set(), set(), set())
            rows_c2_a1.append({"MAKE_CAN_ID(HEX)": can_id, "DATA(HEX)": payload})

    with open(c2_axis1_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["MAKE_CAN_ID(HEX)", "DATA(HEX)"])
        writer.writeheader()
        writer.writerows(rows_c2_a1)

    rows_c2_a2 = []
    # (a) 前 24 条 0x1XX 报文
    for s in range(24):
        info = chip_info[s]
        rows_c2_a2.append({"MAKE_CAN_ID(HEX)": info["can_id"], "DATA(HEX)": build_64byte_payload(info["reg_map"])})
    # (b) 后续 0x25X 动态加速度报文
    for frame_idx in range(num_frames):
        for b_id in range(1, 5):
            can_id = board_channel_map[b_id]
            payload = build_25x_board_payload(b_id, chip_info, frame_idx, signals_a2, set(), set(), set())
            rows_c2_a2.append({"MAKE_CAN_ID(HEX)": can_id, "DATA(HEX)": payload})

    with open(c2_axis2_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["MAKE_CAN_ID(HEX)", "DATA(HEX)"])
        writer.writeheader()
        writer.writerows(rows_c2_a2)

    # 导出 Centrifuge2 中间文件与 ProcessedData3 (图 5/8)
    for axis, c2_rows in [("Axis1", rows_c2_a1), ("Axis2", rows_c2_a2)]:
        id_c2 = []
        p1_c2 = []
        p2_c2 = []
        p3_c2 = []
        for s in range(24):
            info = chip_info[s]
            id_c2.append({
                "工位": s,
                "供电板编号": info["board_id"],
                "通道编号": info["sensor_id"],
                "CAN_ID": info["can_id"],
                "通道号_0x25X": info["channel_code"],
                "芯片编号_HEX": info["dev_code"],
                "完整32位Hex_UID": info["uid"],
                "状态": "Valid",
            })
            p1_c2.append({
                "工位": s,
                "芯片编号_HEX": info["dev_code"],
                "稳态读数_LSB": "312.50",
                "稳态均值_LSB": "312.50",
                "状态": "Passed",
            })
            p2_c2.append({
                "工位": s,
                "芯片编号_HEX": info["dev_code"],
                "Axis_均值": "312.50",
                "状态": "Passed",
            })
            p3_c2.append({
                "工位": s,
                "芯片编号_HEX": info["dev_code"],
                "零偏_前1w点": "0.12",
                "灵敏度_160g": "1.953",
                "灵敏度_80g": "1.951",
                "非线性度_pct": "0.08%",
                "标定因数": "1.000",
                "状态": "Passed",
            })

        consolidator.export_intermediate_lot_files(
            dirs_c2["normal_lot_dir"], ts_str, axis, id_c2, p1_c2, p2_c2, centrifuge_id="Centrifuge2"
        )
        p3_file = os.path.join(dirs_c2["normal_lot_dir"], f"CrashSensor_Centrifuge2_ProcessedData3_{axis}_{ts_str}.csv")
        consolidator._write_csv(p3_file, p3_c2)

    # 导出 Centrifuge2 标定/整合文件 (图 1/8 脚本 8、图 5/8)
    c2_cal_file = os.path.join(dirs_c2["calibration_dir"], f"CrashSensor_Centrifuge2_Integration_{ts_str}_{lot_id}.csv")
    consolidator._write_csv(c2_cal_file, normal_rows)
    print(f" -> 已生成 Centrifuge2 整合测试文件: {c2_cal_file}")

    print("\n[完成] 全部测试数据集已严格遵循原厂规范 (图 1/8 至图 8/8) 生成至 data_conlidation 目录！")


if __name__ == "__main__":
    create_all_test_datasets()
