"""TPMS 车型分类打标与全基地数据汇总软件 - 主程序入口

支持两种启动模式：
1. 图形界面模式 (GUI):
   python main.py
2. 命令行批处理模式 (CLI):
   python main.py --cli --spec data/车型分类规范.xlsx --country data/国家列表.xlsx --inputs data/raw/*.xlsx --output data/output/
"""

import os
import sys
import argparse
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from processor.config_manager import ConfigManager
from processor.tagger import ModelTagger
from processor.consolidator import DataConsolidator


def run_cli(args):
    print("==================================================")
    print("TPMS 车型打标与全基地数据汇总 CLI 模式")
    print("==================================================")

    # 1. 加载规范
    cfg = ConfigManager(args.spec, args.country)
    tagger = ModelTagger(cfg)
    consolidator = DataConsolidator(tagger)

    # 2. 解析输入文件
    input_files = []
    for pattern in args.inputs:
        matches = glob.glob(pattern)
        if matches:
            input_files.extend(matches)
        elif os.path.exists(pattern):
            input_files.append(pattern)

    input_files = sorted(list(set(input_files)))
    if not input_files:
        print("[错误] 未找到任何符合条件的输入文件！")
        return 1

    print(f"[*] 找到待处理单基地文件 {len(input_files)} 个:")
    for f in input_files:
        print(f"  - {os.path.basename(f)}")

    # 3. 批量打标
    out_dir = args.output
    os.makedirs(out_dir, exist_ok=True)
    print("\n[*] 正在执行单基地批量打标...")
    processed_files = []
    for orig, proc_path, count in consolidator.batch_process_files(input_files, output_dir=out_dir):
        base_name = consolidator.extract_base_name_from_filename(orig)
        print(f"  [√] [{base_name}] -> {os.path.basename(proc_path)} ({count}行有效车型，已自动选取车型汇总Sheet并剔除合计行)")
        processed_files.append(proc_path)

    # 4. 全基地合并汇总
    print("\n[*] 正在执行跨基地数据汇总与尾部时间戳备注写入...")
    summary_path, df_summary = consolidator.consolidate_bases(
        file_paths=processed_files,
        output_dir=out_dir,
        summary_filename=args.summary_name
    )
    print(f"  [√] 汇总完成: {summary_path}")
    print(f"  [√] 总计合并行数: {len(df_summary)} 行")
    print("\n[完成] 全流程执行完毕！")
    return 0


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_dir() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return getattr(sys, "_MEIPASS")
    return os.path.dirname(os.path.abspath(__file__))


def find_default_file(rel_path: str, fallback_names: list = None) -> str:
    # 优先检查本地运行目录
    local_p = os.path.join(get_app_dir(), rel_path)
    if os.path.exists(local_p):
        return local_p
    if fallback_names:
        parent_dir = os.path.dirname(local_p)
        for fb in fallback_names:
            fb_local = os.path.join(parent_dir, fb)
            if os.path.exists(fb_local):
                return fb_local

    # 其次检查内嵌打包资源目录
    bundled_p = os.path.join(get_resource_dir(), rel_path)
    if os.path.exists(bundled_p):
        return bundled_p
    if fallback_names:
        parent_b = os.path.dirname(bundled_p)
        for fb in fallback_names:
            fb_bundled = os.path.join(parent_b, fb)
            if os.path.exists(fb_bundled):
                return fb_bundled

    return local_p


def main():
    parser = argparse.ArgumentParser(description="TPMS 车型分类打标与全基地数据汇总软件")
    parser.add_argument("--cli", action="store_true", help="以命令行模式运行（默认启动 GUI）")
    parser.add_argument("--spec", default=find_default_file(os.path.join("data", "车型分类规范.xlsx"), ["车型分类规范.xls"]), help="车型分类规范 Excel 路径")
    parser.add_argument("--country", default=find_default_file(os.path.join("data", "地区列表.xlsx"), ["国家列表.xlsx", "地区列表.xls", "国家列表.xls"]), help="地区/国家列表 Excel 路径")
    parser.add_argument("--inputs", nargs="+", default=[os.path.join(get_app_dir(), "data", "raw", "*.xlsx")], help="待处理单基地月计划文件路径或通配符")
    parser.add_argument("--output", default=os.path.join(get_app_dir(), "data", "output"), help="输出目录")
    parser.add_argument("--summary-name", default="★秘密★全基地车型数据汇总.xlsx", help="汇总文件名")

    args = parser.parse_args()

    if args.cli:
        sys.exit(run_cli(args))
    else:
        import tkinter as tk
        from gui import TPMSAppGUI
        root = tk.Tk()
        app = TPMSAppGUI(root)
        root.mainloop()


if __name__ == "__main__":
    main()
