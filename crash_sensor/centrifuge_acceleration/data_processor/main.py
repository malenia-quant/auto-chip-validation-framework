"""
CrashSensor 离心机测试数据自动化处理软件主程序入口
支持 GUI 交互控制台与 CLI 批处理模式
"""

import os
import sys
import argparse
import datetime
import re

# 确保 processor 模块正确加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from processor.can_data_parser import CentrifugeCANParser
from processor.centrifuge_processor import CentrifugeProcessor
from processor.calibration_processor import CalibrationProcessor
from processor.result_consolidator import ResultConsolidator, DataMerger


def run_cli_batch(lot_id: str, axis1_file: str, axis2_file: str, output_base: str = "Data_Consolidation"):
    """CLI 批处理全自动流"""
    print(f"=== CrashSensor 离心机数据批处理 (LOT: {lot_id}) ===")
    can_parser = CentrifugeCANParser()
    cent_processor = CentrifugeProcessor()
    cal_processor = CalibrationProcessor()
    consolidator = ResultConsolidator(base_output_dir=output_base)

    print(f"[1/4] 解析 Axis1 文件: {axis1_file}...")
    ax1_parsed = can_parser.parse_can_raw_csv(axis1_file)
    series1 = can_parser.extract_dynamic_acceleration_series(axis1_file)
    print(f" -> 4-in-1 芯片命名完成 (共 {len(ax1_parsed['filenames_4in1'])} 组)")

    print(f"[2/4] 解析 Axis2 文件: {axis2_file}...")
    ax2_parsed = can_parser.parse_can_raw_csv(axis2_file)
    series2 = can_parser.extract_dynamic_acceleration_series(axis2_file)

    fixture_map = {s: ("N" if (s // 6 + 1) in (1, 2) else "P") for s in range(24)}
    real_means1 = cent_processor.compute_slot_steady_means(series1, "Axis1", fixture_map)
    real_means2 = cent_processor.compute_slot_steady_means(series2, "Axis2", fixture_map)

    print(f"[3/4] 双轴数据聚合与标定计算...")
    tested_list = []
    for s in range(24):
        item1 = ax1_parsed["slots"].get(s, {})
        item2 = ax2_parsed["slots"].get(s, {})

        b_id, s_id = CentrifugeCANParser.get_slot_from_global_index(s)
        fixture = "N" if (b_id in (1, 2)) else "P"

        # 检查空载 (两个轴均无器件或均为空载报文)
        is_empty1 = (not item1) or item1.get("status_msg") == "空载通道 (无器件)"
        is_empty2 = (not item2) or item2.get("status_msg") == "空载通道 (无器件)"
        if is_empty1 and is_empty2:
            continue

        # 检查报文通信损坏/断路
        is_broken1 = item1 and (not item1.get("is_valid", False)) and item1.get("status_msg") != "空载通道 (无器件)"
        is_broken2 = item2 and (not item2.get("is_valid", False)) and item2.get("status_msg") != "空载通道 (无器件)"

        dev_code = item1.get("device_code_11") or item2.get("device_code_11") or "00000000000"
        uid = item1.get("uid_32") or item2.get("uid_32") or "-"

        if is_broken1 or is_broken2:
            status_err = item1.get("status_msg") if is_broken1 else item2.get("status_msg")
            tested_list.append({
                "device_code_11": dev_code,
                "uid_32": uid,
                "can_id": f"0x1{b_id}{s_id}",
                "board_id": b_id,
                "sensor_id": s_id,
                "fixture_type": fixture,
                "is_valid": False,
                "status_msg": status_err or "通信故障",
                "Axis1_Mean": None,
                "Axis2_Mean": None,
            })
            continue

        # 提取实测加速度稳态均值 (若通道未测/缺轴，则保持 None 触发 Rework)
        ax1_mean = real_means1.get(s) if (item1 and item1.get("is_valid")) else None
        ax2_mean = real_means2.get(s) if (item2 and item2.get("is_valid")) else None

        tested_list.append({
            "device_code_11": dev_code,
            "uid_32": uid,
            "can_id": f"0x1{b_id}{s_id}",
            "board_id": b_id,
            "sensor_id": s_id,
            "fixture_type": fixture,
            "is_valid": True,
            "status_msg": "正常",
            "Axis1_Mean": ax1_mean,
            "Axis2_Mean": ax2_mean,
        })

    normal, rework, abnormal = consolidator.classify_devices(tested_list, calibration_processor=cal_processor)

    print(f"[4/4] 产出三清单与归档目录树...")
    # 尝试从输入文件名中提取日期与时间戳 (如 20260907_120000)
    ts_match = re.search(r"(\d{8}_\d{6})", axis1_file)
    ts = ts_match.group(1) if ts_match else datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    date_str = ts.split("_")[0] if "_" in ts else ts[:8]

    dirs = consolidator.organize_directories(date_str=date_str, lot_id=lot_id)
    out_files = consolidator.export_tri_lists(dirs["daily_dir"], ts, normal, rework, abnormal)
    cal_file = consolidator.export_calibration_file(dirs["calibration_dir"], ts, lot_id, normal)

    total = len(normal) + len(rework) + len(abnormal)
    yield_rate = (len(normal) / total * 100) if total > 0 else 0.0

    print("=" * 60)
    print(f"批次测试处理完成！")
    print(f"总工位数: {total} | 正常 (Normal): {len(normal)} | 待复测 (Rework): {len(rework)} | 异常 (Abnormal): {len(abnormal)}")
    print(f"直通良率 (Yield Rate): {yield_rate:.1f}%")
    print(f"三清单导出路径 (日目录): {dirs['daily_dir']}")
    print(f"标定汇总导出路径 (月目录): {cal_file}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="CrashSensor 离心机测试数据自动化处理软件")
    parser.add_argument("--mode", choices=["gui", "cli"], default="gui", help="运行模式: gui 或 cli")
    parser.add_argument("--lot", default="LOT1", help="LOT 批次号")
    parser.add_argument("--axis1", help="Axis1 原始 CAN CSV 路径 (CLI 模式必填)")
    parser.add_argument("--axis2", help="Axis2 原始 CAN CSV 路径 (CLI 模式必填)")
    parser.add_argument("--output", default="Data_Consolidation", help="输出根目录")

    args = parser.parse_args()

    if args.mode == "gui":
        from gui import CentrifugeGUI
        import tkinter as tk
        root = tk.Tk()
        app = CentrifugeGUI(root)
        root.mainloop()
    elif args.mode == "cli":
        if not args.axis1 or not args.axis2:
            print("错误: CLI 模式下必须提供 --axis1 与 --axis2 参数！")
            sys.exit(1)
        run_cli_batch(args.lot, args.axis1, args.axis2, args.output)


if __name__ == "__main__":
    main()
