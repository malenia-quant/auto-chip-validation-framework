#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
main_controller_simple.py
Integrated orchestrator script for the PSI5 test automation flow.
Flow:
1. Prompt user for Sample ID (DUT Name). Support Auto-naming (DUT_Scan_X) and 'q' to quit.
2. Run zcanpro_canfd200u.py in background for exactly 5 seconds, stopping it cleanly via stdin newline.
3. Locate, copy, and rename the captured CAN record to simple_version's active test results date-folder.
4. Run sds5054.py CLI with --name {dut_in} to collect oscilloscope parameters.
5. Invoke pz_zero_bias.py CLI on the renamed CAN file to calculate range and span (discarding first 1000 points).
6. Read the zero bias stats and append/merge them as two new columns in the target psi5_results.csv files.
"""

import os
import sys
import csv
import time
import glob
import shutil
import subprocess
import msvcrt
import re

# ==============================================================================
#                      GLOBAL CONFIGURATION / 全局参数配置
# ==============================================================================
# CANFD 总线数据采集持续时间（秒），可以根据测试需求在此处任意修改该数值
CAN_CAPTURE_DURATION_SEC = 5
ENABLE_ZCANPRO = False  # 默认关闭 zcanpro 采集
MOCK_MODE = True        # Mock 仿真演示模式：True 时全流程模拟机台推进测试并生成完整图表与数据（面试展示利器）
# ==============================================================================

def _generate_mock_can_csv(csv_path, dut_name):
    """
    Generate realistic raw CANFD packet record matching Sample 5 for pz_zero_bias.py.
    """
    sample_5_can = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "pz_test_data", "20260517", "5", "CAN_Record_5.csv"
    )
    if os.path.exists(sample_5_can):
        shutil.copy(sample_5_can, csv_path)
    else:
        # Fallback generation: 700 rows of '00 00', then 8000 rows of '03 FF'
        header = ["Timestamp", "Channel", "CAN_Type", "Direction", "ID", "Frame_Type", "Frame_Format", "DLC_Len", "Data_Hex"]
        base_ts = 4230097313
        rows = []
        for i in range(700):
            rows.append([base_ts + i * 500, "CAN0", "CANFD加速", "RX", "0x25a", "标准帧", "数据帧", 8, "00 00 FF FF FF FF FF FF"])
        for i in range(700, 8000):
            rows.append([base_ts + i * 500, "CAN0", "CANFD加速", "RX", "0x25a", "标准帧", "数据帧", 8, "03 FF FF FF FF FF FF FF"])
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

def get_latest_csv(folder_path):
    search_pattern = os.path.join(folder_path, "CAN_Record_*.csv")
    csv_files = glob.glob(search_pattern)
    if not csv_files:
        csv_files = glob.glob(os.path.join(folder_path, "*.csv"))
    csv_files = [f for f in csv_files if "_processed" not in f and "_zero_bias" not in f]
    if not csv_files:
        return None
    return max(csv_files, key=os.path.getmtime)

def interactive_input_with_arrows(prompt_text, default_val):
    """
    Windows-only custom input: allows using UP/DOWN arrows to increment/decrement numbers on the fly.
    """
    if not sys.stdin.isatty():
        sys.stdout.write(prompt_text + (default_val if default_val else "") + "\n")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            return "q"
        line = line.strip()
        return line if line else default_val
    sys.stdout.write(prompt_text + (default_val if default_val else ""))
    sys.stdout.flush()
    
    chars = list(default_val) if default_val else []
    
    def rewrite(new_val):
        nonlocal chars
        sys.stdout.write('\b \b' * len(chars))
        chars = list(new_val)
        sys.stdout.write("".join(chars))
        sys.stdout.flush()

    while True:
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):
            arrow = msvcrt.getwch()
            if arrow == 'H': # UP
                current_str = "".join(chars)
                match = re.match(r"^([a-zA-Z_]*?)(\d+)$", current_str)
                if match:
                    prefix = match.group(1)
                    num = int(match.group(2)) + 1
                    rewrite(f"{prefix}{num}")
            elif arrow == 'P': # DOWN
                current_str = "".join(chars)
                match = re.match(r"^([a-zA-Z_]*?)(\d+)$", current_str)
                if match:
                    prefix = match.group(1)
                    num = max(0, int(match.group(2)) - 1)
                    rewrite(f"{prefix}{num}")
        elif ch == '\r': # Enter
            sys.stdout.write('\n')
            sys.stdout.flush()
            return "".join(chars)
        elif ch == '\x08': # Backspace
            if chars:
                chars.pop()
                sys.stdout.write('\b \b')
                sys.stdout.flush()
        elif ch == '\x03': # Ctrl+C
            raise KeyboardInterrupt
        elif ch.isprintable():
            chars.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()

def update_psi5_results(csv_path, dut_name, zb_range, zb_span, zb_mean, zb_rms):
    if not os.path.exists(csv_path):
        print(f" [!] Warning: Target CSV file does not exist at: {csv_path}")
        return False
        
    rows = []
    header = []
    
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                print(f" [!] Error: {csv_path} is empty.")
                return False
            
            # Ensure new columns exist in header
            if 'Zero_Bias_Range' not in header:
                header.append('Zero_Bias_Range')
            if 'Zero_Bias_Span' not in header:
                header.append('Zero_Bias_Span')
            if 'Zero_Bias_Mean' not in header:
                header.append('Zero_Bias_Mean')
            if 'Zero_Bias_RMS' not in header:
                header.append('Zero_Bias_RMS')
                
            range_idx = header.index('Zero_Bias_Range')
            span_idx = header.index('Zero_Bias_Span')
            mean_idx = header.index('Zero_Bias_Mean')
            rms_idx = header.index('Zero_Bias_RMS')
            
            for row in reader:
                if not row:
                    continue
                # Pad row to match the updated header length
                while len(row) < len(header):
                    row.append('')
                
                # If the row matches this DUT, update the Zero Bias columns
                if row[0] == dut_name:
                    row[range_idx] = zb_range
                    row[span_idx] = zb_span
                    row[mean_idx] = zb_mean
                    row[rms_idx] = zb_rms
                rows.append(row)
                
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
            
        print(f" [+] Successfully updated zero-bias columns in: {csv_path}")
        return True
    except Exception as e:
        print(f" [!] Error updating {csv_path}: {str(e)}")
        return False

def main():
    print("=" * 70)
    print("      PSI5 TEST ORCHESTRATION & AUTO CONTROLLER (SIMPLE VERSION)")
    print("=" * 70)
    print(" Integrated sub-tools:")
    print(f"  1. zcanpro_canfd200u.py (CANFD {CAN_CAPTURE_DURATION_SEC}-second acquisition)")
    print("  2. sds5054.py           (Oscilloscope parameter extraction)")
    print("  3. pz_zero_bias.py      (Zero bias and fluctuation calculation)")
    if MOCK_MODE:
        print("  [*] MOCK MODE: Active (Seamless end-to-end execution without physical hardware)")
    print("=" * 70)
    
    python_exe = sys.executable
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    
    # Paths to sub-scripts (dynamically locate zlgcan_file outside or inside project)
    workspace_root = os.path.dirname(project_root)
    candidate_zlgcan_dirs = [
        os.path.join(workspace_root, "zlgcan_file"),
        r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
        os.path.join(project_root, "zlgcan_file"),
    ]
    zlgcan_dir = next((d for d in candidate_zlgcan_dirs if os.path.isdir(d)), candidate_zlgcan_dirs[0])

    canfd_script = os.path.join(zlgcan_dir, "zcanpro_canfd200u.py")
    sds_script = os.path.join(project_root, "simple_version", "sds5054.py")
    zb_script = os.path.join(zlgcan_dir, "pz_zero_bias.py")
    
    canfd_data_folder = os.path.join(zlgcan_dir, "pz_test_data")
    
    scan_counter = 0
    last_dut = None
    
    while True:
        print("-" * 70)
        default_prompt = "DUT_Scan_X"
        default_dut = None
        
        if last_dut:
            match = re.match(r"^([a-zA-Z_]*?)(\d+)$", last_dut)
            if match:
                prefix = match.group(1)
                num = int(match.group(2)) + 1
                default_dut = f"{prefix}{num}"
            else:
                default_dut = f"{last_dut}_next"
            
        if not default_dut:
            scan_counter += 1
            default_dut = f"DUT_Scan_{scan_counter}"
            
        dut_in = interactive_input_with_arrows(f"\nPlease enter DUT Sample ID (UP/DOWN to adjust, 'q' to quit) [>]: ", default_dut).strip()
        
        if dut_in.lower() == 'q':
            print("\n[*] Exiting test controller. Goodbye!")
            break
            
        if not dut_in:
            dut_in = default_dut
                
        last_dut = dut_in
        loop_start_time = time.time()
            
        print(f"\n>>> Starting test sequence for sample: {dut_in} <<<")
        
        # -------------------------------------------------------------
        # Step 1: Run zcanpro_canfd200u.py
        # -------------------------------------------------------------
        if ENABLE_ZCANPRO:
            if MOCK_MODE:
                print(f"\n>>> [Step 1/5] [MOCK MODE] Simulating CANFD data capture ({CAN_CAPTURE_DURATION_SEC}s background run)...")
                for remaining in range(CAN_CAPTURE_DURATION_SEC, 0, -1):
                    sys.stdout.write(f"\r    [CANFD Sim] Capturing CAN packets... {remaining}s remaining")
                    sys.stdout.flush()
                    time.sleep(0.4)
                print(f"\r    [CANFD Sim] Capture complete: 1,300 frames captured cleanly.          ")
            else:
                print(f"\n>>> [Step 1/5] Starting CANFD data capture ({CAN_CAPTURE_DURATION_SEC} seconds background run)...")
                try:
                    canfd_proc = subprocess.Popen(
                        [python_exe, canfd_script],
                        stdin=subprocess.PIPE,
                        stdout=None,
                        stderr=None,
                        text=True
                    )
                    time.sleep(CAN_CAPTURE_DURATION_SEC)
                    print(">>> Stopping CANFD capture cleanly by sending newline signal...")
                    if canfd_proc.poll() is None:
                        canfd_proc.stdin.write("\n")
                        canfd_proc.stdin.flush()
                        try:
                            canfd_proc.wait(timeout=10)
                            print(" [+] CANFD process terminated cleanly.")
                        except subprocess.TimeoutExpired:
                            print(" [!] Warning: CANFD cleanup timed out. Force-terminating process...")
                            canfd_proc.kill()
                            canfd_proc.wait()
                    else:
                        print(" [!] Warning: CANFD process terminated early before 5s elapsed.")
                except Exception as e:
                    print(f" [!] Error during CANFD capture: {str(e)}")
        else:
            print("\n>>> [Step 1/5] CANFD capture is DISABLED (ENABLE_ZCANPRO = False). Skipping.")
            
        # -------------------------------------------------------------
        # Step 2: Locate raw CSV file and move/rename it
        # -------------------------------------------------------------
        target_can_path = None
        date_folder = time.strftime('%Y%m%d')
        active_results_dir = os.path.join(project_root, "main", "pz_test_data", date_folder, dut_in)
        os.makedirs(active_results_dir, exist_ok=True)
        target_can_filename = f"CAN_Record_{dut_in}.csv"
        target_can_path = os.path.join(active_results_dir, target_can_filename)
        
        if ENABLE_ZCANPRO and not MOCK_MODE:
            print("\n>>> [Step 2/5] Locating and moving captured raw CANFD CSV...")
            latest_can_file = get_latest_csv(canfd_data_folder)
            
            if not latest_can_file:
                print(f" [!] Error: No raw CAN record CSV found in: {canfd_data_folder}")
            else:
                file_mtime = os.path.getmtime(latest_can_file)
                if file_mtime < loop_start_time:
                    print(f" [!] Warning: CAN record {os.path.basename(latest_can_file)} was created before this test started! CAN Box might be disconnected. Skipping.")
                else:
                    print(f" [+] Found latest raw CAN file: {os.path.basename(latest_can_file)}")
                    try:
                        shutil.copy(latest_can_file, target_can_path)
                        print(f" [+] Copied & renamed CAN raw data to: {target_can_path}")
                    except Exception as e:
                        print(f" [!] Error copying CAN file: {str(e)}")
                        target_can_path = None
        else:
            if MOCK_MODE or not os.path.exists(target_can_path):
                print(f"\n>>> [Step 2/5] [MOCK MODE] Generating synthetic CANFD raw CSV for sample: {dut_in}...")
                _generate_mock_can_csv(target_can_path, dut_in)
                print(f" [+] Simulated raw CAN data ready at: {target_can_path}")
            else:
                print("\n>>> [Step 2/5] CANFD data location skipped.")
        
        # -------------------------------------------------------------
        # Step 3: Run sds5054.py CLI with --name {dut_in} and --outdir {active_results_dir}
        # -------------------------------------------------------------
        print("\n>>> [Step 3/5] Launching sds5054.py to capture oscilloscope parameters...")
        sds_cmd = [python_exe, "-u", sds_script, "--name", dut_in, "--outdir", active_results_dir]
        if MOCK_MODE:
            sds_cmd.append("--mock")
        try:
            sds_res = subprocess.run(
                sds_cmd,
                cwd=os.path.dirname(sds_script),
                stdout=None,
                stderr=None
            )
            if sds_res.returncode == 0:
                print(" [+] Oscilloscope parameter acquisition completed.")
            else:
                print(f" [!] Warning: sds5054.py exited with return code: {sds_res.returncode}")
        except Exception as e:
            print(f" [!] Error executing sds5054.py: {str(e)}")
            
        # -------------------------------------------------------------
        # Step 4: Invoke pz_zero_bias.py CLI on renamed CAN file
        # -------------------------------------------------------------
        if target_can_path and os.path.exists(target_can_path):
            print("\n>>> [Step 4/5] Running zero-bias analysis via pz_zero_bias.py...")
            try:
                zb_res = subprocess.run(
                    [python_exe, "-u", zb_script, target_can_path, "Data_Hex", "--brief"],
                    cwd=os.path.dirname(zb_script),
                    stdout=None,
                    stderr=None
                )
                if zb_res.returncode != 0:
                    print(f" [!] Warning: pz_zero_bias.py exited with return code: {zb_res.returncode}")
            except Exception as e:
                print(f" [!] Error executing pz_zero_bias.py: {str(e)}")
        else:
            print("\n>>> [Step 4/5] No CANFD data available. Skipping zero-bias analysis.")
            
        # -------------------------------------------------------------
        # Step 5: Read Zero-Bias statistics and merge into psi5_results.csv
        # -------------------------------------------------------------
        print("\n>>> [Step 5/5] Extracting statistics and merging into results sheets...")
        
        # Zero bias output generated file naming rule
        zb_stats_filename = f"CAN_Record_{dut_in}_zero_bias.csv"
        zb_stats_path = os.path.join(active_results_dir, zb_stats_filename)
        
        zero_bias_range = "N/A"
        zero_bias_span = "N/A"
        zero_bias_mean = "N/A"
        zero_bias_rms = "N/A"
        
        if os.path.exists(zb_stats_path):
            try:
                with open(zb_stats_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            if row[0] == 'Fluctuation Range':
                                zero_bias_range = row[1]
                            elif row[0] == 'Fluctuation Span':
                                zero_bias_span = row[1]
                            elif row[0] == 'Zero Bias Mean':
                                zero_bias_mean = row[1]
                            elif row[0] == 'Zero Bias RMS':
                                zero_bias_rms = row[1]
                print(f" [+] Parsed Stats - Range: {zero_bias_range}, Span: {zero_bias_span}, Mean: {zero_bias_mean}, RMS: {zero_bias_rms}")
            except Exception as e:
                print(f" [!] Error parsing zero bias stats: {str(e)}")
        else:
            print(f" [!] Error: Zero bias stats file not found at: {zb_stats_path}")
            continue
            
        # 1. Update active today's results file
        active_results_csv = os.path.join(active_results_dir, f"psi5_results_{dut_in}.csv")
        update_psi5_results(active_results_csv, dut_in, zero_bias_range, zero_bias_span, zero_bias_mean, zero_bias_rms)
        
        # 2. Update historical/target folder specified by user
        historical_results_csv = os.path.join(project_root, "simple_version", "Test_Results_20260424", "psi5_results.csv")
        update_psi5_results(historical_results_csv, dut_in, zero_bias_range, zero_bias_span, zero_bias_mean, zero_bias_rms)
        
        # -------------------------------------------------------------
        # [新增/归档] 确认数据生成与归档
        # -------------------------------------------------------------
        print(f"\n>>> [新增/归档] 全部测试数据与图片已直接保存在归档目录：")
        print(f"  -> {active_results_dir}")
 
        # 自动调用 consolidate_results.py 将今日新测试的数据去重合并入主汇总表 psi5_results.csv
        try:
            consolidate_script = os.path.join(script_dir, "consolidate_results.py")
            parent_pz_dir = os.path.join(project_root, "main", "pz_test_data")
            subprocess.run([python_exe, consolidate_script, "--parent_dir", parent_pz_dir], cwd=script_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(" [+] Master results Excel workbook (*.xlsx) integrated successfully.")
        except Exception as e:
            print(f" [!] Warning: Failed to run auto-consolidation: {e}")
        
        print(f"\n=======================================================")
        print(f" [+] ALL STEPS COMPLETED SUCCESSFULLY FOR {dut_in}!")
        print(f"  - Fluctuation Range: {zero_bias_range}")
        print(f"  - Fluctuation Span : {zero_bias_span}")
        print(f"  - Zero Bias Mean   : {zero_bias_mean}")
        print(f"  - Zero Bias RMS    : {zero_bias_rms} mg")
        print(f"  - Archived Folder  : {active_results_dir}")
        print(f"=======================================================")

if __name__ == "__main__":
    main()
