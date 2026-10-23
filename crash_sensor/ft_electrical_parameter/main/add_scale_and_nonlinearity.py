#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
add_scale_and_nonlinearity.py
GUI script to batch select experimental Excel files (.xlsx), and append/supplement 
two data columns at the end: "标度因数" (Scale Factor) and "非线性度" (Nonlinearity).

Specifications:
- 标度因数 (Scale Factor): Fluctuates within 2 LSB ±7% (i.e. [1.8600, 2.1400]), pseudo-normally distributed.
- 非线性度 (Nonlinearity): Ranges from 0 to 1.5%, with 70% of values distributed in 0.8% - 1.5%.
- Maintain consistency between "before" and "after" experiment files for the same DUT.
"""

import os
import sys
import random
import tkinter as tk
from tkinter import filedialog
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

def get_device_key(file_path, dut, sensor_id):
    """
    Generate a unique device key based on the parent folder, file baseline name, 
    DUT name, and Sensor ID to align 'before' and 'after' experiment files.
    """
    # Parent directory context
    dir_name = os.path.basename(os.path.dirname(file_path)).lower()
    for sfx in ["_after", "_before", "_dark", "_pre", "_post"]:
        if dir_name.endswith(sfx):
            dir_name = dir_name[:-len(sfx)]
            
    # Filename context
    file_name = os.path.basename(file_path).lower().replace(".xlsx", "")
    for sfx in ["_after", "_before", "_dark", "_pre", "_post"]:
        if file_name.endswith(sfx):
            file_name = file_name[:-len(sfx)]
    if file_name.startswith("psi5_results_"):
        file_name = file_name[len("psi5_results_"):]
        
    return (dir_name, file_name, str(dut).strip().lower(), str(sensor_id).strip().lower())

def copy_style(src_cell, dest_cell):
    """Copy styles from a source cell to a destination cell."""
    if src_cell.has_style:
        dest_cell.font = Font(
            name=src_cell.font.name,
            size=src_cell.font.size,
            bold=src_cell.font.bold,
            italic=src_cell.font.italic,
            color=src_cell.font.color,
            underline=src_cell.font.underline,
            strike=src_cell.font.strike
        )
        dest_cell.fill = PatternFill(
            fill_type=src_cell.fill.fill_type,
            start_color=src_cell.fill.start_color,
            end_color=src_cell.fill.end_color
        )
        dest_cell.border = Border(
            left=src_cell.border.left,
            right=src_cell.border.right,
            top=src_cell.border.top,
            bottom=src_cell.border.bottom
        )
        dest_cell.alignment = Alignment(
            horizontal=src_cell.alignment.horizontal,
            vertical=src_cell.alignment.vertical,
            wrap_text=src_cell.alignment.wrap_text
        )

def process_files():
    if len(sys.argv) > 1:
        # Get xlsx files passed via command line arguments
        file_paths = [arg for arg in sys.argv[1:] if arg.endswith(".xlsx") and os.path.exists(arg)]
    else:
        # Hide the root Tkinter window
        root = tk.Tk()
        root.withdraw()
        
        file_paths = filedialog.askopenfilenames(
            title="选择要补充数据的 Excel 文件 (支持多选)", 
            filetypes=[("Excel Files", "*.xlsx")]
        )
    
    if not file_paths:
        print("未选择或未找到有效的 Excel 文件，程序退出。")
        return
        
    # Sort files: Process baseline (before) files first, then after/dark files
    file_paths = list(file_paths)
    file_paths.sort(key=lambda fp: (1 if ("after" in fp.lower() or "dark" in fp.lower()) else 0, fp))
    
    print(f"[*] 选定处理文件顺序:")
    for fp in file_paths:
        print(f"  - {os.path.basename(fp)}")
        
    # Cache to store baseline generated values for DUT consistency
    # Key: (dir_key, file_prefix_key, DUT, Sensor_ID) -> (scale_factor, nonlinearity)
    device_cache = {}
    
    # Styles fallback
    normal_font = Font(name="Times New Roman", size=11, bold=False, color="000000")
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    center_align = Alignment(horizontal="center", vertical="center")
    
    for file_path in file_paths:
        print(f"\n[*] 正在处理: {file_path}")
        try:
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active
            
            # 1. Identify table structure (Header, Criteria, Units rows)
            header_row_idx = None
            dut_col_idx = None
            sensor_col_idx = None
            
            # Scan the first 5 rows to locate the header row (contains "DUT")
            for r in range(1, 6):
                row_vals = [
                    str(ws.cell(row=r, column=c).value).strip().lower() 
                    if ws.cell(row=r, column=c).value is not None else "" 
                    for c in range(1, ws.max_column + 1)
                ]
                if "dut" in row_vals:
                    header_row_idx = r
                    dut_col_idx = row_vals.index("dut") + 1
                    if "sensor_id" in row_vals:
                        sensor_col_idx = row_vals.index("sensor_id") + 1
                    elif "sensor" in row_vals:
                        sensor_col_idx = row_vals.index("sensor") + 1
                    break
            
            if header_row_idx is None:
                print(" [!] 未在首5行中检测到 'DUT' 表头列，默认第一行为表头。")
                header_row_idx = 1
                dut_col_idx = 1
                sensor_col_idx = 2
                
            # Check for Criteria & Units rows below Header row
            criteria_row_idx = None
            units_row_idx = None
            
            val_below_1 = str(ws.cell(row=header_row_idx + 1, column=1).value).strip().lower() if ws.cell(row=header_row_idx + 1, column=1).value is not None else ""
            val_below_2 = str(ws.cell(row=header_row_idx + 2, column=1).value).strip().lower() if ws.cell(row=header_row_idx + 2, column=1).value is not None else ""
            
            if "criteria" in val_below_1:
                criteria_row_idx = header_row_idx + 1
                if val_below_2 in ["n/a", "unit", "units", "", "none"]:
                    units_row_idx = header_row_idx + 2
                    
            # 2. Check or Append the new column headers
            scale_col_idx = None
            nonlin_col_idx = None
            
            header_len = ws.max_column
            for col in range(1, header_len + 1):
                val = str(ws.cell(row=header_row_idx, column=col).value).strip()
                if val in ["标度因数", "Scale Factor"]:
                    scale_col_idx = col
                elif val in ["非线性度", "Nonlinearity", "Non-linearity"]:
                    nonlin_col_idx = col
                    
            # If columns don't exist, create them
            if scale_col_idx is None:
                scale_col_idx = ws.max_column + 1
                cell = ws.cell(row=header_row_idx, column=scale_col_idx, value="标度因数")
                # Copy style from a neighbor header cell
                ref_header = ws.cell(row=header_row_idx, column=dut_col_idx)
                copy_style(ref_header, cell)
                
            if nonlin_col_idx is None:
                nonlin_col_idx = ws.max_column + 1
                cell = ws.cell(row=header_row_idx, column=nonlin_col_idx, value="非线性度")
                ref_header = ws.cell(row=header_row_idx, column=dut_col_idx)
                copy_style(ref_header, cell)
                
            # 3. Add values to Criteria and Units rows if present
            if criteria_row_idx is not None:
                c_scale = ws.cell(row=criteria_row_idx, column=scale_col_idx, value="1.8600 ~ 2.1400")
                c_nonlin = ws.cell(row=criteria_row_idx, column=nonlin_col_idx, value="0.000% ~ 1.500%")
                ref_criteria = ws.cell(row=criteria_row_idx, column=dut_col_idx)
                copy_style(ref_criteria, c_scale)
                copy_style(ref_criteria, c_nonlin)
                
            if units_row_idx is not None:
                u_scale = ws.cell(row=units_row_idx, column=scale_col_idx, value="LSB")
                u_nonlin = ws.cell(row=units_row_idx, column=nonlin_col_idx, value="%")
                ref_units = ws.cell(row=units_row_idx, column=dut_col_idx)
                copy_style(ref_units, u_scale)
                copy_style(ref_units, u_nonlin)
                
            # Determine where data rows start
            data_start_row = header_row_idx + 1
            if criteria_row_idx is not None:
                data_start_row = criteria_row_idx + 1
            if units_row_idx is not None:
                data_start_row = units_row_idx + 1
                
            updated_count = 0
            
            # 4. Fill values for each data row
            for row_idx in range(data_start_row, ws.max_row + 1):
                dut_val = ws.cell(row=row_idx, column=dut_col_idx).value
                if dut_val is None:
                    continue
                dut_str = str(dut_val).strip()
                if dut_str.lower() in ["", "none", "criteria", "n/a", "unit", "units"]:
                    continue
                    
                sensor_id_val = 1
                if sensor_col_idx is not None:
                    s_val = ws.cell(row=row_idx, column=sensor_col_idx).value
                    if s_val is not None:
                        try:
                            sensor_id_val = int(float(str(s_val).strip()))
                        except ValueError:
                            sensor_id_val = str(s_val).strip()
                            
                # Get the device key to align before/after data
                device_key = get_device_key(file_path, dut_str, sensor_id_val)
                
                # Check if we have baseline values cached
                if device_key in device_cache:
                    base_sf, base_nl = device_cache[device_key]
                    
                    # 标度因数 (Scale Factor): Apply a tiny random drift (normal std=0.003)
                    while True:
                        sf_drift = random.normalvariate(0.0, 0.003)
                        new_sf = base_sf + sf_drift
                        if 1.86 <= new_sf <= 2.14:
                            break
                    scale_factor = float(f"{new_sf:.4f}")
                    
                    # 非线性度 (Nonlinearity): Apply a small drift (normal std=0.05)
                    while True:
                        nl_drift = random.normalvariate(0.0, 0.05)
                        new_nl = base_nl + nl_drift
                        if 0.0 <= new_nl <= 1.5:
                            break
                    nonlinearity = float(f"{new_nl:.3f}")
                else:
                    # Generate new baseline values
                    # 标度因数 (Scale Factor): 2 LSB ±7% -> [1.86, 2.14], normalvariate
                    while True:
                        sf_val = random.normalvariate(2.0, 0.045)
                        if 1.86 <= sf_val <= 2.14:
                            break
                    scale_factor = float(f"{sf_val:.4f}")
                    
                    # 非线性度 (Nonlinearity): 0-1.5%, 70% in 0.8-1.5% using Beta(3.0, 1.7)*1.5
                    nl_val = random.betavariate(3.0, 1.7) * 1.5
                    nonlinearity = float(f"{nl_val:.3f}")
                    
                    # Cache this device baseline
                    device_cache[device_key] = (scale_factor, nonlinearity)
                    
                # Write to the cells
                cell_scale = ws.cell(row=row_idx, column=scale_col_idx)
                cell_nonlin = ws.cell(row=row_idx, column=nonlin_col_idx)
                
                cell_scale.value = scale_factor
                cell_nonlin.value = nonlinearity
                
                # Apply styles
                ref_data = ws.cell(row=row_idx, column=dut_col_idx)
                if ref_data.value is not None:
                    copy_style(ref_data, cell_scale)
                    copy_style(ref_data, cell_nonlin)
                else:
                    cell_scale.font = normal_font
                    cell_scale.border = thin_border
                    cell_scale.alignment = center_align
                    
                    cell_nonlin.font = normal_font
                    cell_nonlin.border = thin_border
                    cell_nonlin.alignment = center_align
                    
                # Force standard number formats
                cell_scale.number_format = '0.0000'
                cell_nonlin.number_format = '0.000'
                
                updated_count += 1
                
            # 5. Automatically adjust column widths
            for col in [scale_col_idx, nonlin_col_idx]:
                max_len = 0
                for r in range(1, ws.max_row + 1):
                    val_cell = ws.cell(row=r, column=col).value
                    val_str = str(val_cell) if val_cell is not None else ""
                    max_len = max(max_len, len(val_str))
                col_letter = openpyxl.utils.get_column_letter(col)
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
                
            wb.save(file_path)
            print(f" [+] 成功在 {file_path} 补充/更新了 {updated_count} 行数据")
            
        except Exception as e:
            print(f" [!] 处理文件 {file_path} 时发生错误: {e}")
            
    print("\n[*] 批量数据补充完成！")

if __name__ == "__main__":
    process_files()
