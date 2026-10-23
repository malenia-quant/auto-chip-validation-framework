import os
import csv

def cleanup():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pz_test_data_dir = os.path.join(script_dir, "pz_test_data")
    
    if not os.path.exists(pz_test_data_dir):
        print(f"Error: pz_test_data directory not found at: {pz_test_data_dir}")
        return
        
    print(f"===============================================================")
    print(f"      PSI5 DEVICE-LEVEL LEGACY CSV CLEANUP & RESTRUCTURING     ")
    print(f"===============================================================")
    print(f"[*] Target directory: {pz_test_data_dir}")
    print(f"[*] Scanning for legacy psi5_results.csv files in subdirectories...")
    
    cleaned_count = 0
    deleted_count = 0
    
    for root, dirs, files in os.walk(pz_test_data_dir):
        # 跳过主目录本身（母汇总表在主目录下，不应被清理）
        if os.path.abspath(root) == os.path.abspath(pz_test_data_dir):
            continue
            
        # 获取当前子文件夹名称（例如 "35" 或 "DUT_Scan_35"）
        device_id = os.path.basename(root).strip()
        
        # 排除 8 位数字的日期目录，如 "20260517"
        if device_id.isdigit() and len(device_id) == 8:
            continue
            
        legacy_csv_path = os.path.join(root, "psi5_results.csv")
        
        if os.path.exists(legacy_csv_path):
            device_id_lower = device_id.lower()
            clean_device_id = device_id_lower.replace("dut_scan_", "").replace("dut_test_", "").strip()
            
            print(f"\n[*] Processing legacy results in: {root}")
            print(f"  -> Target Device ID: {device_id} (Cleaned: {clean_device_id})")
            
            header = None
            matching_rows = []
            
            try:
                with open(legacy_csv_path, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.reader(f)
                    try:
                        header = next(reader)
                    except StopIteration:
                        pass
                        
                    for row in reader:
                        if not row or not any(row):
                            continue
                        
                        dut_name_lower = str(row[0]).strip().lower()
                        clean_dut_lower = dut_name_lower.replace("dut_scan_", "").replace("dut_test_", "").strip()
                        
                        # 强力适配各种器件前缀与数值命名规则
                        if (dut_name_lower == device_id_lower or 
                            clean_dut_lower == clean_device_id or 
                            dut_name_lower == clean_device_id or 
                            clean_dut_lower == device_id_lower):
                            matching_rows.append(row)
                
                # 如果找到了匹配本器件的测试行，保留最后一行（最新运行记录）
                if matching_rows:
                    last_row = matching_rows[-1]
                    new_csv_name = f"psi5_results_{device_id}.csv"
                    new_csv_path = os.path.join(root, new_csv_name)
                    
                    with open(new_csv_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        if header:
                            writer.writerow(header)
                        writer.writerow(last_row)
                        
                    print(f"  [+] Created pure sheet: {new_csv_name} (with 1 matching record)")
                    cleaned_count += 1
                else:
                    print(f"  [!] Warning: No rows matching device ID '{device_id}' were found in legacy sheet.")
                
                # 安全删除被污染的旧 psi5_results.csv
                os.remove(legacy_csv_path)
                print(f"  [-] Removed legacy contaminated file: psi5_results.csv")
                deleted_count += 1
                
            except Exception as e:
                print(f"  [!] Error processing legacy CSV: {e}")
                
    print(f"\n===============================================================")
    print(f"                      CLEANUP SUMMARY                          ")
    print(f"===============================================================")
    print(f" [+] Successfully created device-specific CSVs : {cleaned_count} files")
    print(f" [-] Successfully removed legacy contaminated CSVs: {deleted_count} files")
    print(f"===============================================================\n")

if __name__ == "__main__":
    cleanup()
