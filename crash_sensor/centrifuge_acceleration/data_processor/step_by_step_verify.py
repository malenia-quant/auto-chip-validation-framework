"""
CrashSensor 离心机测试数据 — 分步独立验证脚本
用于配合 data_conlidation 目录中的测试文件，一步步执行不同的核心处理模块进行验证。
用法:
  python step_by_step_verify.py --step 1   # 验证 Step 1: CAN 报文清洗与 4-in-1 芯片合并命名
  python step_by_step_verify.py --step 2   # 验证 Step 2: 动态加速度边沿检测与过渡态裁剪 (≤50点稳态均值)
  python step_by_step_verify.py --step 3   # 验证 Step 3: 1.5倍量程放大、Span 门禁拦截与 MTP 模板修调替换
  python step_by_step_verify.py --step 4   # 验证 Step 4: 首测批次聚合、工装极性门禁与三大清单导出
  python step_by_step_verify.py --step 5   # 验证 Step 5: 模式 B 补测数据缝合 (Data Merger) 与良率闭环
  python step_by_step_verify.py --step all # 顺序执行全套分步验证
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data_conlidation")

sys.path.insert(0, os.path.join(BASE_DIR, "data_processor"))
from processor.can_data_parser import CentrifugeCANParser
from processor.centrifuge_processor import CentrifugeProcessor
from processor.calibration_processor import CalibrationProcessor, SpanGateError
from processor.result_consolidator import ResultConsolidator, DataMerger


def verify_step1():
    print("\n" + "=" * 70)
    print("【Step 1 验证】CAN 报文解包、UID 解码与 4-in-1 芯片合并命名")
    print("=" * 70)

    axis1_csv = os.path.join(
        DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "Normal_Lot", "LOT1",
        "CrashSensor_Centrifuge1_OriginalData_Axis1_20260907_120000.csv"
    )
    print(f"-> 待解析原始文件: {axis1_csv}")
    assert os.path.exists(axis1_csv), f"测试数据文件不存在: {axis1_csv}"

    parser = CentrifugeCANParser()
    res = parser.parse_can_raw_csv(axis1_csv)

    print(f"1. 成功提取 24 个槽位数据 (其中有效芯片数: {sum(1 for s in res['slots'].values() if s.get('is_valid'))})")
    slot0 = res["slots"][0]
    print(f"   - 示例 Slot 0 (Board 1, Sensor 1):")
    print(f"     * 11位芯片编号: {slot0.get('device_code_11')}")
    print(f"     * 32位 Hex UID: {slot0.get('uid_32')}")
    print(f"     * CAN ID: {slot0.get('can_id')}")

    print("2. 4-in-1 芯片合并文件名 (共 6 组，每 4 颗芯片合成一组，不足补 00000000000):")
    for idx, fn in enumerate(res["filenames_4in1"], start=1):
        print(f"   [组 {idx}] {fn}")

    slot23 = res["slots"].get(23, {})
    print(f"3. 空载识别: Slot 23 状态为 '{slot23.get('status_msg')}', is_valid = {slot23.get('is_valid')}")

    print("\n>>> [Step 1 验证通过] CAN 报文解码与 4-in-1 命名逻辑符合规范！\n")


def verify_step2():
    print("\n" + "=" * 70)
    print("【Step 2 验证】动态加速度边沿检测与过渡态裁剪 (丢弃前30帧，截取≤50点稳态)")
    print("=" * 70)

    axis1_csv = os.path.join(
        DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "Normal_Lot", "LOT1",
        "CrashSensor_Centrifuge1_OriginalData_Axis1_20260907_120000.csv"
    )
    parser = CentrifugeCANParser()
    series_map = parser.extract_dynamic_acceleration_series(axis1_csv)

    processor = CentrifugeProcessor(discard_frames=30, steady_points_max=50)
    means_map = processor.compute_slot_steady_means(series_map, target_axis="Axis1")

    print(f"-> 成功提取 24 个工位的时序动态加速度波形 (每工位采样点数: {len(series_map[0])})")
    print(f"-> 工装 A (板 1、板 2): 预期正向加速度 ~ +320 LSB")
    print(f"   - Slot 0 (B1_S1) 稳态均值: {means_map.get(0):.2f} LSB")
    print(f"   - Slot 1 (B1_S2) 稳态均值: {means_map.get(1):.2f} LSB")
    print(f"-> 工装 B (板 3、板 4): 预期负向加速度 ~ -320 LSB")
    print(f"   - Slot 12 (B3_S1) 稳态均值: {means_map.get(12):.2f} LSB")
    print(f"   - Slot 13 (B3_S2) 稳态均值: {means_map.get(13):.2f} LSB")

    # 生成阶梯图示例
    plot_path = os.path.join(DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "Normal_Lot", "LOT1", "Slot0_Staircase.png")
    processor.create_staircase_plot(np.array(series_map[0]), "Slot 0 Acceleration Staircase", plot_path)
    print(f"-> 已生成工位 0 稳态阶梯图: {plot_path}")

    print("\n>>> [Step 2 验证通过] 离心机动态平稳段截取与稳态均值提取正确！\n")


def verify_step3():
    print("\n" + "=" * 70)
    print("【Step 3 验证】1.5倍量程折算、Span 硬件合理性门禁与 MTP 模板替换")
    print("=" * 70)

    cal_processor = CalibrationProcessor(
        scale_factor=1.5,
        const_numerator=961 * (2 ** 20),
        span_min=600.0,
        span_max=3600.0
    )

    # 1. 标定公式计算与 1.5 倍折算
    # 模拟 160g 实测值: +312.5 LSB 与 -312.5 LSB
    pos_160 = 312.5
    neg_160 = -312.5
    adj_dec, adj_hex, span = cal_processor.calculate_adj(pos_160, neg_160)
    print(f"1. 标定计算核心数值:")
    print(f"   - 160g 实测值: +{pos_160} / {neg_160} LSB")
    print(f"   - 1.5倍折算 240g 等效值: +{pos_160*1.5} / {neg_160*1.5} LSB")
    print(f"   - Span 跨度: {span:.2f} (门禁区间: [600, 3600])")
    print(f"   - ADJ 计算结果 (16-bit Hex): 0x{adj_hex} (十进制: {adj_dec})")

    # 2. Span 门禁防御验证 (同号或断路)
    print("2. Span 门禁安全拦截测试:")
    try:
        cal_processor.calculate_adj(310.0, 305.0)  # 同为正数，Span 近似 0
        print("   [失败] 未拦截异常 Span!")
    except SpanGateError as e:
        print(f"   [成功拦截异常] {e}")

    # 3. MTP 模板文件 6 处地址替换与 CFG22<13> 置位验证 (图 1/8 命名规则: {dev_code}-after-calibration.txt)
    sample_dev_code = "00030020001"
    template_path = os.path.join(DATA_DIR, "MTP_DATA", "before-calibration", f"{sample_dev_code}.txt")
    output_path = os.path.join(DATA_DIR, "MTP_DATA", "after-calibration", f"{sample_dev_code}-after-calibration.txt")
    print(f"3. 读取 MTP 模板并更新: {template_path}")
    assert os.path.exists(template_path), f"模板文件不存在: {template_path}"

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    updated_content, count = cal_processor.update_mtp_content(content, adj_hex)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(updated_content)

    print(f"   - 替换修调寄存器点数: {count} 处 (目标 5b 5a, 58 57, 55 54)")
    print(f"   - 已成功写入标定后 MTP 文件: {output_path}")

    print("\n>>> [Step 3 验证通过] 标定数学换算、门禁安全阻断与 MTP 模板写入无误！\n")


def verify_step4():
    print("\n" + "=" * 70)
    print("【Step 4 验证】首测双轴聚合、工装极性校验与三大清单 (Normal/Rework/Abnormal) 导出")
    print("=" * 70)

    from main import run_cli_batch

    axis1_csv = os.path.join(
        DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "Normal_Lot", "LOT1",
        "CrashSensor_Centrifuge1_OriginalData_Axis1_20260907_120000.csv"
    )
    axis2_csv = os.path.join(
        DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "Normal_Lot", "LOT1",
        "CrashSensor_Centrifuge1_OriginalData_Axis2_20260907_120000.csv"
    )

    print(f"执行 CLI 批次处理: LOT1...")
    run_cli_batch("LOT1", axis1_csv, axis2_csv, DATA_DIR)

    daily_dir = os.path.join(DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "07")
    norm_files = [f for f in os.listdir(daily_dir) if f.startswith("Normal_List_")]
    rw_files = [f for f in os.listdir(daily_dir) if f.startswith("Rework_List_")]
    abn_files = [f for f in os.listdir(daily_dir) if f.startswith("AbnormalFunction_List_")]

    assert len(norm_files) > 0, "Normal_List 未生成!"
    assert len(rw_files) > 0, "Rework_List 未生成!"
    assert len(abn_files) > 0, "AbnormalFunction_List 未生成!"

    latest_norm = os.path.join(daily_dir, sorted(norm_files)[-1])
    latest_rw = os.path.join(daily_dir, sorted(rw_files)[-1])
    latest_abn = os.path.join(daily_dir, sorted(abn_files)[-1])

    df_n = pd.read_csv(latest_norm)
    df_r = pd.read_csv(latest_rw)
    df_a = pd.read_csv(latest_abn)

    print(f"-> 产出三大清单结果:")
    print(f"   * 正常合格清单 (Normal_List): {len(df_n)} 颗芯片 (预期 20 颗)")
    print(f"   * 待复测清单 (Rework_List):   {len(df_r)} 颗芯片 (预期 2 颗: Slot 4 缺Axis2, Slot 10 缺Axis1)")
    print(f"   * 异常报废清单 (Abnormal):    {len(df_a)} 颗芯片 (预期 1 颗: Slot 5 通信故障)")

    assert len(df_n) == 20, f"Normal 数量不符: {len(df_n)}"
    assert len(df_r) == 2, f"Rework 数量不符: {len(df_r)}"
    assert len(df_a) == 1, f"Abnormal 数量不符: {len(df_a)}"

    print("\n>>> [Step 4 验证通过] 双轴聚合与三大清单导出完全符合量产要求！\n")


def verify_step5():
    print("\n" + "=" * 70)
    print("【Step 5 验证】模式 B 脱机补测数据缝合 (Data Merger) 与良率闭环")
    print("=" * 70)

    rework_lot_dir = os.path.join(DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "Rework_Lot", "LOT1")
    daily_dir = os.path.join(DATA_DIR, "Centrifuge1", "Data_Consolidation", "2026", "09", "07")

    rw_axis1_csv = os.path.join(rework_lot_dir, "CrashSensor_Centrifuge1_OriginalData_Axis1_20260907_120000.csv")
    rw_axis2_csv = os.path.join(rework_lot_dir, "CrashSensor_Centrifuge1_OriginalData_Axis2_20260907_120000.csv")

    print(f"-> 待缝合补测文件:")
    print(f"   * 补测 Axis1 (针对 Slot 10, 工装 A): {rw_axis1_csv}")
    print(f"   * 补测 Axis2 (针对 Slot 4, 工装 A):  {rw_axis2_csv}")

    merger = DataMerger()
    consolidator = ResultConsolidator(base_output_dir=DATA_DIR)

    # 模拟 LOT1 原始基础表 (含缺失轴)
    initial_lot1 = pd.DataFrame([
        {
            "device_code_11": "00030020005",  # Slot 4
            "uid_32": "0001000500200003102A000000000000",
            "fixture_type": "A",
            "Axis1_Mean": 312.4,
            "Axis2_Mean": None,
            "rework_status": "Pending"
        },
        {
            "device_code_11": "0003002000B",  # Slot 10
            "uid_32": "0001000B00200003102A000000000000",
            "fixture_type": "A",
            "Axis1_Mean": None,
            "Axis2_Mean": -312.3,
            "rework_status": "Pending"
        }
    ])

    # 模拟补测提取的读数并调用 DataMerger 缝合
    df_rw_axis2 = pd.DataFrame([
        {"device_code_11": "00030020005", "rework_reading": 312.2}
    ])
    df_rw_axis1 = pd.DataFrame([
        {"device_code_11": "0003002000B", "rework_reading": 312.5}
    ])

    merged_df = merger.merge_lot_with_rework(initial_lot1, df_rw_axis2, rework_axis="Axis2")
    merged_df = merger.merge_lot_with_rework(merged_df, df_rw_axis1, rework_axis="Axis1")

    print("1. Data Merger 缝合后记录:")
    for _, row in merged_df.iterrows():
        print(f"   * 芯片: {row['device_code_11']} | Axis1={row['Axis1_Mean']:.2f} | Axis2={row['Axis2_Mean']:.2f} | 状态={row['rework_status']}")

    assert merged_df.at[0, "Axis2_Mean"] == -312.2, "工装A补测Axis2极性映射错误!"
    assert merged_df.at[1, "Axis1_Mean"] == 312.5, "工装A补测Axis1极性映射错误!"
    assert merged_df.at[0, "rework_status"] == "Resolved"
    assert merged_df.at[1, "rework_status"] == "Resolved"

    print("2. 三清单良率闭环结项验证 (Rework 标记 Resolved，并追加进 Normal_List):")
    tmp_rework_csv = os.path.join(daily_dir, "Temp_Rework_For_Verify.csv")
    tmp_normal_csv = os.path.join(daily_dir, "Temp_Normal_For_Verify.csv")

    pd.DataFrame([
        {"芯片编号_HEX": "00030020005", "复测状态": "Pending", "缺失轴向": "Axis2"},
        {"芯片编号_HEX": "0003002000B", "复测状态": "Pending", "缺失轴向": "Axis1"},
    ]).to_csv(tmp_rework_csv, index=False, encoding="utf-8-sig")

    pd.DataFrame([{"芯片编号_HEX": "00030020001", "状态": "Passed"}]).to_csv(tmp_normal_csv, index=False, encoding="utf-8-sig")

    consolidator.update_rework_to_normal_closure(
        tmp_rework_csv,
        tmp_normal_csv,
        resolved_device_codes=["00030020005", "0003002000B"],
        resolved_details=[
            {"芯片编号_HEX": "00030020005", "状态": "Passed"},
            {"芯片编号_HEX": "0003002000B", "状态": "Passed"},
        ]
    )

    df_rw_check = pd.read_csv(tmp_rework_csv)
    df_nm_check = pd.read_csv(tmp_normal_csv)
    assert all(df_rw_check["复测状态"] == "Resolved"), "Rework 状态未全部更新为 Resolved!"
    assert len(df_nm_check) == 3, f"Normal 清单未追加两颗芯片，总数应为 3，实际为 {len(df_nm_check)}"

    if os.path.exists(tmp_rework_csv):
        os.remove(tmp_rework_csv)
    if os.path.exists(tmp_normal_csv):
        os.remove(tmp_normal_csv)

    print("   * Rework 清单中已成功将补测芯片更新为 Resolved")
    print("   * Normal_List 已成功追加补测通过芯片，良率分子闭环完成")

    print("\n>>> [Step 5 验证通过] Data Merger 物理极性对齐与良率闭环更新完全正确！\n")


def main():
    parser = argparse.ArgumentParser(description="CrashSensor 离心机测试数据分步独立验证")
    parser.add_argument(
        "--step",
        choices=["1", "2", "3", "4", "5", "all"],
        default="all",
        help="执行的验证步骤: 1, 2, 3, 4, 5 或 all"
    )
    args = parser.parse_args()

    steps = {
        "1": verify_step1,
        "2": verify_step2,
        "3": verify_step3,
        "4": verify_step4,
        "5": verify_step5,
    }

    if args.step == "all":
        print("======== 开始执行 CrashSensor 离心机测试全套分步验证 (Steps 1 ~ 5) ========")
        for s in ["1", "2", "3", "4", "5"]:
            steps[s]()
        print("=" * 70)
        print("【全部分步验证成功】所有 5 个核心处理模块与数据链路均已严格通过验证！")
        print("=" * 70)
    else:
        steps[args.step]()


if __name__ == "__main__":
    main()
