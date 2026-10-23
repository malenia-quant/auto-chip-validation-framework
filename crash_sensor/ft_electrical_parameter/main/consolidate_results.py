#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
consolidate_results.py
Utility script to recursively scan a selected parent directory for batch subfolders,
for each subfolder, find all device-level psi5_results.csv files, de-duplicate the records,
sort them numerically/alphabetically, and compile them into a master psi5_results_{subfolder}.xlsx workbook
saved in the parent directory.
"""

import os
import csv
import tkinter as tk
from tkinter import filedialog
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

def get_valid_folders(parent_dir):
    valid_folders = set()
    for root_dir, dirs, files in os.walk(parent_dir):
        for d in dirs:
            # 排除 8 位数字的日期目录，如 "20260517"
            if d.isdigit() and len(d) == 8:
                continue
            valid_folders.add(d.lower())
    return valid_folders

def safe_float(val):
    if val is None:
        return None
    try:
        return float(str(val).strip())
    except ValueError:
        return None
        
def check_cell_fail(col_idx, val, sensor_id):
    f_val = safe_float(val)
    if f_val is None:
        if col_idx == 19:
            return str(val).strip().upper() == "NO"
        return False
        
    if col_idx == 3:  # Base Current (mA)
        return not (12.0 <= f_val <= 20.0)
    elif col_idx == 4:  # Sink Current (mA)
        return not (35.0 <= f_val <= 45.0)
    elif col_idx == 5:  # Sink Rise Mean (ns)
        return not (550.0 <= f_val <= 850.0)
    elif col_idx == 7:  # Sink Fall Mean (ns)
        return not (550.0 <= f_val <= 850.0)
    elif col_idx == 9:  # Bit Time Avg 125k (us)
        return not (7.600 <= f_val <= 8.400)
    elif col_idx == 11:  # Max Clock Drift Rate (%)
        return f_val >= 1.5
    elif col_idx == 13:  # Duty Cycle Mean (%)
        return not (49.0 <= f_val <= 51.0)
    elif col_idx == 14:  # Start Time tDelay (us)
        if sensor_id == 1:
            return not (44.1 <= f_val <= 55.9)
        elif sensor_id == 2:
            return not (181.6 <= f_val <= 206.6)
        elif sensor_id == 3:
            return not (329.7 <= f_val <= 369.0)
    elif col_idx == 15:  # End Time (us)
        if sensor_id == 1:
            return not (142.0 <= f_val <= 165.1)
        elif sensor_id == 2:
            return not (281.2 <= f_val <= 315.8)
        elif sensor_id == 3:
            return not (429.3 <= f_val <= 478.1)
    elif col_idx == 17:  # Cycle Time tCycle (us)
        return not (495.0 <= f_val <= 505.0)
    elif col_idx == 26:  # Zero Bias RMS
        return f_val >= 200.0
        
    return False

def is_row_valid(row, valid_folders):
    if not row or not any(row):
        return False
    dut_name = str(row[0]).strip().lower()
    if dut_name == "criteria":
        return False
    if not dut_name:
        return False
    clean_dut = dut_name.replace("dut_scan_", "").replace("dut_test_", "").strip()
    return (dut_name in valid_folders or clean_dut in valid_folders)

def process_batch(batch_name, csv_files, parent_dir, valid_folders, header_names, criteria_row, header_units):
    master_results_xlsx = os.path.join(parent_dir, f"psi5_results_{batch_name}.xlsx")
    
    dut_to_row = {}

    loaded_history = False
    if os.path.exists(master_results_xlsx):
        try:
            wb = openpyxl.load_workbook(master_results_xlsx, data_only=True)
            ws = wb.active
            
            # 判断旧版 Excel 兼容性，新版数据的第3行为Units单位行，第4行才开始是数据。
            val_a3 = str(ws.cell(row=3, column=1).value).strip().lower()
            start_row = 4 if val_a3 in ["n/a", "unit", "units", "", "none"] else 3
            
            for row_idx in range(start_row, ws.max_row + 1):
                row = [ws.cell(row=row_idx, column=col_idx).value for col_idx in range(1, len(header_names) + 1)]
                if not row or not any(row):
                    continue
                row = [str(x) if x is not None else '' for x in row]
                if not is_row_valid(row, valid_folders):
                    continue
                dut_key = str(row[0]).strip().lower()
                dut_to_row[dut_key] = row
            print(f" [+] Loaded {len(dut_to_row)} valid historical records from master Excel sheet: {master_results_xlsx}")
            loaded_history = True
        except Exception as e:
            print(f" [!] Warning: Failed to load master Excel history for {batch_name}: {e}")
            
    if not loaded_history:
        legacy_csv = master_results_xlsx.replace(".xlsx", ".csv")
        if os.path.exists(legacy_csv):
            try:
                with open(legacy_csv, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.reader(f)
                    try:
                        next(reader)
                        next(reader)
                    except StopIteration:
                        pass
                    for row in reader:
                        if not row or not any(row):
                            continue
                        if not is_row_valid(row, valid_folders):
                            continue
                        while len(row) < len(header_names):
                            row.append('')
                        row = row[:len(header_names)]
                        dut_key = str(row[0]).strip().lower()
                        dut_to_row[dut_key] = row
                print(f" [+] Successfully migrated {len(dut_to_row)} historical records from legacy CSV: {legacy_csv}")
                try:
                    os.remove(legacy_csv)
                except Exception:
                    pass
            except Exception as e:
                print(f" [!] Warning: Failed to load legacy CSV history for {batch_name}: {e}")
    
    # 扫描当前批次中的CSV
    csv_found = False
    for file_path in csv_files:
        if os.path.abspath(file_path) == os.path.abspath(master_results_xlsx):
            continue
        csv_found = True
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                try:
                    next(reader) # skip original csv header
                except StopIteration:
                    continue
                    
                for row in reader:
                    if not row or not any(row):
                        continue
                    if not is_row_valid(row, valid_folders):
                        continue
                        
                    while len(row) < len(header_names):
                        row.append('')
                    row = row[:len(header_names)]
                    
                    dut_key = str(row[0]).strip().lower()
                    dut_to_row[dut_key] = row
        except Exception as e:
            print(f" [!] Warning: Failed to parse {file_path}: {e}")

    all_rows = list(dut_to_row.values())
    if not all_rows:
        if csv_found:
            print(f" [!] No valid test data rows found in {batch_name}.")
        return
        
    try:
        all_rows.sort(key=lambda r: (
            0 if r[0].isdigit() else 1,
            int(r[0]) if r[0].isdigit() else r[0],
            int(r[1]) if r[1].isdigit() else r[1]
        ))
    except Exception:
        all_rows.sort(key=lambda r: (r[0], r[1]))
        
    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "PSI5 Test Results"
        ws.views.sheetView[0].showGridLines = True
        
        ws.append(header_names)
        ws.append(criteria_row)
        ws.append(header_units)
        
        for r in all_rows:
            ws.append(r)
            
        header_font = Font(name="Times New Roman", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        
        criteria_font = Font(name="Times New Roman", size=11, bold=True, italic=True, color="595959")
        criteria_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
        
        units_font = Font(name="Times New Roman", size=10, bold=False, italic=True, color="FFFFFF")
        
        normal_font = Font(name="Times New Roman", size=11, bold=False, color="000000")
        fail_font = Font(name="Times New Roman", size=11, bold=True, color="C00000")
        
        thin_border = Border(
            left=Side(style='thin', color='D9D9D9'),
            right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'),
            bottom=Side(style='thin', color='D9D9D9')
        )
        
        # 1. 美化第一行 (表头名)
        for col_idx in range(1, len(header_names) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
            
        # 2. 美化第二行 (Criteria 规格参考行)
        for col_idx in range(1, len(header_names) + 1):
            cell = ws.cell(row=2, column=col_idx)
            cell.font = criteria_font
            cell.fill = criteria_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
            
        # 3. 美化第三行 (Units 单位行)
        for col_idx in range(1, len(header_names) + 1):
            cell = ws.cell(row=3, column=col_idx)
            cell.font = units_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
            
        # 4. 美化与条件判定第四行及以后的器件测试数据行
        for row_idx in range(4, len(all_rows) + 4):
            sensor_id_val = safe_float(ws.cell(row=row_idx, column=2).value)
            if sensor_id_val is None:
                sensor_id_val = 1
                
            for col_idx in range(1, len(header_names) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
                val_str = str(cell.value) if cell.value is not None else ""
                is_failed = check_cell_fail(col_idx - 1, val_str, int(sensor_id_val))
                
                if is_failed:
                    cell.font = fail_font
                else:
                    cell.font = normal_font
                    
        ws.row_dimensions[1].height = 24
        ws.row_dimensions[2].height = 20
        ws.row_dimensions[3].height = 18
        for row_idx in range(4, len(all_rows) + 4):
            ws.row_dimensions[row_idx].height = 18
            
        for col in ws.columns:
            max_len = 0
            for cell in col:
                val_str = str(cell.value) if cell.value is not None else ""
                if "[" in val_str:
                    max_len = max(max_len, 15)
                else:
                    max_len = max(max_len, len(val_str))
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
            
        wb.save(master_results_xlsx)
        print(f" [+] Success: Consolidated {len(all_rows)} rows for batch '{batch_name}' into master Excel: {master_results_xlsx}")
    except Exception as e:
        print(f" [!] Error writing master consolidated Excel for {batch_name}: {e}")


def batch_consolidate():
    root = tk.Tk()
    root.withdraw()
    parent_dir = filedialog.askdirectory(title="选择包含所有测试日期/批次的母文件夹 (如 pz_test_data)")
    
    if not parent_dir:
        print("未选择文件夹，程序退出。")
        return
        
    print(f"[*] 选定的母文件夹: {parent_dir}")
    valid_folders = get_valid_folders(parent_dir)
    print(f" [+] Scanned disk: Found {len(valid_folders)} active device directories.")
    
    header_names = [
        "DUT", "Sensor_ID", "VDDI_Avg", "Base Current", "Sink Current",
        "Sink Rise Mean", "Sink Rise Details", "Sink Fall Mean", "Sink Fall Details",
        "Bit Time Avg 125k", "Bit Time Details", "Max Clock Drift Rate",
        "Duty Cycle Per Bit", "Duty Cycle Mean", "Start Time tDelay", "End Time",
        "Frame Time tFrame", "Cycle Time tCycle", "Decoded Bits", "Valid Frame",
        "HEX", "HEX", "Decimal Value", "Zero_Bias_Range", "Zero_Bias_Span", "Zero_Bias_Mean", "Zero_Bias_RMS"
    ]
    
    header_units = [
        "N/A", "N/A", "(V)", "(mA)", "(mA)",
        "(ns)", "(ns)", "(ns)", "(ns)",
        "(us)", "(us)", "(During Frame %)",
        "(%)", "(%)", "(us)", "(us)",
        "(us)", "(us)", "N/A", "N/A",
        "(Raw)", "(Payload)", "N/A", "N/A", "N/A", "N/A", "N/A"
    ]
    
    criteria_row = [
        "Criteria", "N/A", "N/A", "12.0 ~ 20.0", "35.0 ~ 45.0",
        "550 ~ 850", "N/A", "550 ~ 850", "N/A",
        "7.600 ~ 8.400", "N/A", "< 1.500",
        "N/A", "49.0 ~ 51.0", "44.1 ~ 55.9 (S1)", "142.0 ~ 165.1 (S1)",
        "N/A", "495.0 ~ 505.0", "13 bits", "YES",
        "N/A", "N/A", "N/A", "[-1, 0]", "1", "[-1.0, 0.0]", "< 200.0"
    ]
    
    print(f"[*] 正在扫描所有 CSV 文件并识别测试批次...")
    batch_to_csvs = {}
    
    for root_dir, dirs, files in os.walk(parent_dir):
        for file in files:
            file_lower = file.lower()
            if file_lower.startswith("psi5_results_") and file_lower.endswith(".csv"):
                csv_path = os.path.join(root_dir, file)
                
                # 推断器件名称
                dut_name_clean = file_lower.replace("psi5_results_", "").replace(".csv", "")
                dut_name_raw = dut_name_clean
                try:
                    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
                        reader = csv.reader(f)
                        try:
                            next(reader) # skip header
                            row = next(reader)
                            if row and len(row) > 0:
                                val = str(row[0]).strip().lower()
                                if val and val != "criteria":
                                    dut_name_raw = val
                                    dut_name_clean = val.replace("dut_scan_", "").replace("dut_test_", "").strip()
                        except StopIteration:
                            pass
                except Exception:
                    pass
                
                immediate_folder = os.path.basename(root_dir).lower()
                
                # 判断 CSV 所在的上一级文件夹是否为 DUT 文件夹 (防止将其单独识别为一个独立批次)
                # 规则：全是数字，或是带dut前缀，或者是解析出的器件名
                is_dut_folder = (
                    immediate_folder.isdigit() or 
                    "dut" in immediate_folder or 
                    immediate_folder == dut_name_clean or
                    immediate_folder == dut_name_raw
                )
                
                if is_dut_folder:
                    batch_path = os.path.dirname(root_dir)
                    # 兜底：如果上一级是母文件夹，说明极大概率这个所谓"器件文件夹"其实是平铺的批次文件夹
                    if batch_path == parent_dir:
                        batch_path = root_dir
                else:
                    batch_path = root_dir
                    
                # 将批次路径转换为相对母文件夹的名称
                rel_path = os.path.relpath(batch_path, parent_dir)
                if rel_path == "." or rel_path == "":
                    batch_name = "root_batch"
                else:
                    batch_name = rel_path.replace(os.sep, "_").replace("/", "_").replace("\\", "_")
                    
                if batch_name not in batch_to_csvs:
                    batch_to_csvs[batch_name] = []
                batch_to_csvs[batch_name].append(csv_path)
    
    subfolders_processed = 0
    for batch_name, csv_files in batch_to_csvs.items():
        print(f"\n[*] 处理批次: {batch_name} (包含 {len(csv_files)} 个文件)")
        process_batch(batch_name, csv_files, parent_dir, valid_folders, header_names, criteria_row, header_units)
        subfolders_processed += 1
            
    if subfolders_processed == 0:
        print(f" [!] 在选定的母文件夹中未找到任何有效的 CSV 测试文件: {parent_dir}")
    else:
        print(f"\n[*] 批量聚合完成！共处理了 {subfolders_processed} 个测试批次。")

if __name__ == "__main__":
    batch_consolidate()
