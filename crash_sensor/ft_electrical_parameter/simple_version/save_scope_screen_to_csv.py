import os
import sys
import time
import csv
import numpy as np
import pyvisa
import re

def extract_float(raw_str, fallback):
    """Robustly extract a float from SCPI response strings like 'TDIV 5.00E-04S'"""
    try:
        matches = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", raw_str)
        if matches:
            return float(matches[-1])
        return fallback
    except:
        return fallback

def main():
    print("==================================================")
    print(" SDS5054 Oscilloscope Screen Data CSV Exporter ")
    print("==================================================")
    
    rm = pyvisa.ResourceManager()
    try:
        resources = rm.list_resources()
    except Exception as e:
        print(f" [!] PyVISA failed to list resources: {e}")
        return
        
    target = next((r for r in resources if 'SDS' in r or 'USB' in r), None)
    if not target:
        print(" [!] No SDS oscilloscope found! Please make sure the USB or LAN cable is connected and powered ON.")
        print(f" [*] Available VISA Resources: {resources}")
        return
        
    print(f"[*] Connecting to: {target} ...")
    try:
        inst = rm.open_resource(target)
        inst.encoding = 'latin-1'
        inst.timeout = 120000  # Increased timeout for MAX memory transfer
        try:
            inst.clear()
        except:
            pass
        idn = inst.query('*IDN?').strip()
        print(f"[+] Connected to: {idn}")
    except Exception as e:
        print(f" [!] Connection failed: {e}")
        return

    # 1. Force all 4 channels to be ON to capture simultaneously
    active_channels = ['C1', 'C2', 'C3', 'C4']
    print("[*] Activating channels C1-C4 to capture all 4 channels simultaneously...")
    for ch in active_channels:
        try:
            inst.write(f"{ch}:TRA ON")
        except Exception as e:
            print(f" [!] Warning: Could not explicitly turn on {ch}: {e}")
    time.sleep(0.5) # allow scope to apply changes
    print(f"[+] Target Channels: {active_channels}")

    # 2. Configure Siglent SCPI Transfer to fetch screen data
    # MAX captures the maximum points available (the actual acquisition memory)
    inst.write('WAV:POIN:MODE MAX')
    inst.write('WAV:DATA:FMT BYTE')
    
    # Fetch sample rate robustly
    sara_raw = inst.query("SARA?").strip()
    sara = extract_float(sara_raw, 250e6)
    print(f"[*] Current Sampling Rate (SARA): {sara / 1e6:.3f} MSa/s")

    channel_data = {}
    min_length = None
    
    # 3. Retrieve waveform data for each active channel
    for ch in active_channels:
        print(f"[*] Downloading waveform for: {ch}...")
        try:
            inst.write(f'WAV:SOUR {ch}')
            
            # Fetch scale & offset using robust extraction
            vdiv_raw = inst.query(f"{ch}:VDIV?").strip()
            vdiv = extract_float(vdiv_raw, 1.0)
            
            voffset_raw = inst.query(f"{ch}:OFST?").strip()
            voffset = extract_float(voffset_raw, 0.0)
            
            # Fetch raw bytes
            inst.write("WAV:DATA?")
            raw = inst.read_raw()
            
            # Strip Siglent TMD header (#9000010000...)
            header_len = 0
            if raw[0:1] == b'#':
                len_of_len = int(chr(raw[1]))
                header_len = 2 + len_of_len
                
            raw_data = raw[header_len:-1]
            data_int = np.frombuffer(raw_data, dtype=np.int8)
            
            # Convert raw A/D byte values into actual physical voltages
            v = data_int * (vdiv / 25.0) - voffset
            channel_data[ch] = v
            
            if min_length is None or len(v) < min_length:
                min_length = len(v)
            print(f"  [+] Successfully fetched {len(v)} points from {ch} (VDIV={vdiv:.3f}V, OFST={voffset:.3f}V)")
        except Exception as e:
            print(f"  [!] Failed to download channel {ch}: {e}")

    if not channel_data or min_length is None or min_length == 0:
        print(" [!] No waveform data could be collected.")
        return

    # Trim array lengths to match exactly (to avoid sizing mismatch in columns)
    for ch in list(channel_data.keys()):
        channel_data[ch] = channel_data[ch][:min_length]
        
    # Check if we successfully got all 4 channels
    saved_channels = list(channel_data.keys())

    # 4. Generate the accurate Time vector
    try:
        tdiv_raw = inst.query("TDIV?").strip()
        if not tdiv_raw or "ERROR" in tdiv_raw.upper():
            tdiv_raw = inst.query("TIM:SCAL?").strip()
        tdiv = extract_float(tdiv_raw, 0.0002)
        
        toff_raw = inst.query("TRDL?").strip()
        if not toff_raw or "ERROR" in toff_raw.upper():
            toff_raw = inst.query("TIM:OFFS?").strip()
        toff = extract_float(toff_raw, 0.0)
        print(f"[*] Timebase parsed: TDIV={tdiv:.6f}s, OFFSET={toff:.6f}s")
    except Exception as e:
        print(f" [!] Warning: Could not read Timebase configurations: {e}")
        tdiv = 0.0002
        toff = 0.0

    # Align points to the horizontal center/trigger point of the oscilloscope screen
    t = toff + (np.arange(min_length) - (min_length / 2.0)) / sara

    # 5. Output to CSV file
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_filename = f"sds5054_screen_data_{timestamp}.csv"
    csv_path = os.path.join(os.getcwd(), csv_filename)
    
    print(f"[*] Writing to CSV file: {csv_path}...")
    try:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Write headers
            header = ["Time (s)"] + [f"{ch} (V)" for ch in saved_channels]
            writer.writerow(header)
            
            # Write data rows
            for i in range(min_length):
                row_vals = [f"{t[i]:.12f}"] + [f"{channel_data[ch][i]:.5f}" for ch in saved_channels]
                writer.writerow(row_vals)
                
        print(f"\n[+] EXPORT SUCCESSFUL!")
        print(f"    - Saved File: {csv_filename}")
        print(f"    - Total Points: {min_length}")
        print(f"    - Channels Saved: {saved_channels}")
    except Exception as e:
        print(f" [!] Error saving CSV: {e}")
    print("==================================================")

if __name__ == '__main__':
    main()
