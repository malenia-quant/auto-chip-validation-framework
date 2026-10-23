import os
import sys
import csv
import subprocess

# Add current directory to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(script_dir)

try:
    from main_controller_simple import update_psi5_results
except ImportError:
    # Inline fallback if import fails
    def update_psi5_results(csv_path, dut_name, zb_range, zb_span, zb_mean, zb_rms):
        if not os.path.exists(csv_path):
            return False
        rows = []
        header = []
        try:
            with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                header = next(reader)
                if 'Zero_Bias_Range' not in header: header.append('Zero_Bias_Range')
                if 'Zero_Bias_Span' not in header: header.append('Zero_Bias_Span')
                if 'Zero_Bias_Mean' not in header: header.append('Zero_Bias_Mean')
                if 'Zero_Bias_RMS' not in header: header.append('Zero_Bias_RMS')
                
                range_idx = header.index('Zero_Bias_Range')
                span_idx = header.index('Zero_Bias_Span')
                mean_idx = header.index('Zero_Bias_Mean')
                rms_idx = header.index('Zero_Bias_RMS')
                
                for row in reader:
                    if not row: continue
                    while len(row) < len(header): row.append('')
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
            return True
        except Exception as e:
            print(f" [!] Error updating {csv_path}: {e}")
            return False

def calculate_rms_from_processed(processed_csv):
    try:
        values = []
        with open(processed_csv, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader) # Skip 'Processed_Value'
            for row in reader:
                if row:
                    values.append(float(row[0]))
        
        if not values:
            return 0.0
        sum_sq = sum(v ** 2 for v in values)
        avg_sq = sum_sq / len(values)
        rms = (avg_sq ** 0.5) * 500
        return rms
    except Exception as e:
        print(f" [!] Error calculating RMS from {processed_csv}: {e}")
        return None

def main():
    target_date_dir = os.path.join(script_dir, "pz_test_data", "20260517")
    if not os.path.exists(target_date_dir):
        print(f" [!] Target date directory not found at: {target_date_dir}")
        return
        
    print(f"[*] Starting Zero Bias RMS Repair Script for directory: {target_date_dir}")
    subdirs = [d for d in os.listdir(target_date_dir) if os.path.isdir(os.path.join(target_date_dir, d))]
    print(f"[*] Found {len(subdirs)} device subdirectories to process.")
    
    python_exe = sys.executable
    workspace_root = os.path.dirname(project_root)
    candidate_zlgcan_dirs = [
        os.path.join(workspace_root, "zlgcan_file"),
        r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file",
        os.path.join(project_root, "zlgcan_file"),
    ]
    zlgcan_dir = next((d for d in candidate_zlgcan_dirs if os.path.isdir(d)), candidate_zlgcan_dirs[0])
    pz_zero_bias_script = os.path.join(zlgcan_dir, "pz_zero_bias.py")
    historical_csv = os.path.join(project_root, "simple_version", "Test_Results_20260424", "psi5_results.csv")
    
    repaired_count = 0
    
    for dut in subdirs:
        dut_dir = os.path.join(target_date_dir, dut)
        processed_csv = os.path.join(dut_dir, f"CAN_Record_{dut}_processed.csv")
        raw_csv = os.path.join(dut_dir, f"CAN_Record_{dut}.csv")
        zb_stats_csv = os.path.join(dut_dir, f"CAN_Record_{dut}_zero_bias.csv")
        local_results_csv = os.path.join(dut_dir, f"psi5_results_{dut}.csv")
        
        print(f"\n--- Processing Device {dut} ---")
        
        # 1. Check if processed CSV exists. If not, generate it using pz_zero_bias.py CLI
        if not os.path.exists(processed_csv):
            if os.path.exists(raw_csv):
                print(f" [!] Processed CSV not found. Running pz_zero_bias.py on raw CSV: {raw_csv}")
                res = subprocess.run([python_exe, pz_zero_bias_script, raw_csv, "Data_Hex"], capture_output=True, text=True)
                if res.returncode != 0:
                    print(f" [!] Failed to run pz_zero_bias.py on {raw_csv}: {res.stderr}")
                    continue
            else:
                print(f" [!] Neither processed nor raw CSV found for DUT {dut} in {dut_dir}")
                continue
                
        # 2. Calculate Zero Bias RMS
        rms_val = calculate_rms_from_processed(processed_csv)
        if rms_val is None:
            continue
        
        rms_str = f"{rms_val:.3f}"
        print(f" [+] Calculated Zero Bias RMS: {rms_str} mg")
        
        # 3. Read other stats from zb_stats_csv
        zero_bias_range = "N/A"
        zero_bias_span = "N/A"
        zero_bias_mean = "N/A"
        
        if os.path.exists(zb_stats_csv):
            try:
                stats_rows = []
                with open(zb_stats_csv, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            stats_rows.append(row)
                            if row[0] == 'Fluctuation Range':
                                zero_bias_range = row[1]
                            elif row[0] == 'Fluctuation Span':
                                zero_bias_span = row[1]
                            elif row[0] == 'Zero Bias Mean':
                                zero_bias_mean = row[1]
                                
                # Write back stats with RMS included
                has_rms_row = False
                for r in stats_rows:
                    if r[0] == 'Zero Bias RMS':
                        r[1] = rms_str
                        has_rms_row = True
                        break
                if not has_rms_row:
                    stats_rows.append(['Zero Bias RMS', rms_str])
                    
                with open(zb_stats_csv, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerows(stats_rows)
            except Exception as e:
                print(f" [!] Error parsing zero bias stats for {dut}: {e}")
                
        # 4. Update local results CSV
        if os.path.exists(local_results_csv):
            update_psi5_results(local_results_csv, dut, zero_bias_range, zero_bias_span, zero_bias_mean, rms_str)
            
        # 5. Update historical results CSV
        if os.path.exists(historical_csv):
            update_psi5_results(historical_csv, dut, zero_bias_range, zero_bias_span, zero_bias_mean, rms_str)
            
        repaired_count += 1
        
    # 6. Re-run consolidation to update the Excel master sheet
    print("\n==========================================")
    print(f"[*] Successfully repaired {repaired_count} devices.")
    print("[*] Running final consolidation to compile Excel...")
    
    consolidate_script = os.path.join(script_dir, "consolidate_results.py")
    subprocess.run([python_exe, consolidate_script], cwd=script_dir)
    print("==========================================")
    print("[+] REPAIR COMPLETE!")

if __name__ == "__main__":
    main()
