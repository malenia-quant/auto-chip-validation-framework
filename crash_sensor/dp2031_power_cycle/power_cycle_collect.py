# -*- coding: utf-8 -*-
"""
    DP2031 DC Power Source Cycling & ZLG CANFD Data Collector
    
    This script performs automated cyclical power-on testing:
    1. Discovers and connects to Rigol DP2031 power supply via VISA.
    2. Initializes ZLG USBCANFD-200U device in 1M/2M CANFD mode.
    3. Runs an infinite loop:
       - Clears ZLG frame buffers.
       - Turns DP2031 power output ON.
       - Captures CAN FD frames for 10 seconds.
       - Turns DP2031 power output OFF.
       - Saves captured data into a cycle-specific CSV inside a date-based directory.
       - Waits for 3 minutes (180 seconds) with a countdown timer, then repeats.
    4. Automatically ensures power output is turned OFF on exit or crash.
"""

import sys
import os
import time
import csv
import queue
import threading
from datetime import datetime
from ctypes import *

# ==============================================================================
#                      GLOBAL CONFIGURATION / 全局参数配置
# ==============================================================================
# 每次上电输出电压 (V)
POWER_VOLTAGE = 12.0
# 每次上电限流值 (A)
POWER_CURRENT_LIMIT = 1.0
# 过压保护阈值 (V)
POWER_OVP = 13.5
# 过流保护限制 (A)
POWER_OCP = 1.5
# DP2031 控制通道 (通道号，默认为 1)
POWER_CHANNEL = 1

# 上电维持及数据采集持续时间 (秒)
CAPTURE_DURATION_SEC = 10
# 采集结束后断电等待持续时间 (分钟)
WAIT_DURATION_MIN = 3
# ==============================================================================

# ================= 确切环境依赖注入 =================
script_dir = os.path.dirname(os.path.abspath(__file__))
# 动态定位驱动目录
candidate_dirs = [
    os.path.abspath(os.path.join(script_dir, "..", "zlgcan_file", "zlgcan_python_251211")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file\zlgcan_python_251211",
    os.path.abspath(os.path.join(script_dir, "..", "..", "zlgcan_file", "zlgcan_python_251211")),
]
zlgcan_real_dir = next((d for d in candidate_dirs if os.path.exists(d)), candidate_dirs[0])
kernel_dir = os.path.join(zlgcan_real_dir, "kerneldlls")

# 1. 提升 Python 包搜索优先级
sys.path.insert(0, zlgcan_real_dir)

# 2. 针对 Python 3.8+ (包括 3.11) 必须注册 DLL 安全目录
if hasattr(os, 'add_dll_directory'):
    try:
        os.add_dll_directory(zlgcan_real_dir)
        if os.path.exists(kernel_dir):
            os.add_dll_directory(kernel_dir)
    except Exception as e:
        print(f"Warning: Failed to add DLL directory: {e}")

# 3. 兼容老版本及 C 底层查找，注入环境变量
os.environ['PATH'] = zlgcan_real_dir + os.pathsep + kernel_dir + os.pathsep + os.environ['PATH']

# 4. 强行将当前工作目录切换到驱动文件夹进行导入，确保依赖 DLL 顺利载入
original_cwd = os.getcwd()
try:
    os.chdir(zlgcan_real_dir)
    from zlgcan import *
    print(f"成功在指定目录加载 Zlgcan 环境，并已注册子依赖库目录")
finally:
    os.chdir(original_cwd)
# ===================================================

# Import pyvisa for instrument control
try:
    import pyvisa
except ImportError:
    print(" [!] pyvisa is not installed. Please run: pip install pyvisa")
    sys.exit(1)

# Thread-safe logging structures
data_queue = queue.Queue()
record_active = False
thread_flag = True

# ZLG CANFD Receiver Thread
def receive_thread(device_handle, chn_handle):
    global record_active, thread_flag
    while thread_flag:
        time.sleep(0.005)
        # 1. Receive standard CAN frames
        rcv_num = zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
        if rcv_num:
            rcv_msg, rcv_num = zcanlib.Receive(chn_handle, min(rcv_num, 100), 100)
            for msg in rcv_msg[:rcv_num]:
                frame = msg.frame
                direction = "TX" if frame._pad & 0x20 else "RX"
                frame_type = "扩展帧" if frame.can_id & (1 << 31) else "标准帧"
                frame_format = "远程帧" if frame.can_id & (1 << 30) else "数据帧"
                can_id = hex(frame.can_id & 0x1FFFFFFF)
                dlc = frame.can_dlc
                data = " ".join([f"{num:02X}" for num in frame.data[:dlc]])
                
                if record_active:
                    data_queue.put([
                        msg.timestamp, 
                        f"CAN{chn_handle & 0xFF}", 
                        "CAN", 
                        direction, 
                        can_id, 
                        frame_type, 
                        frame_format, 
                        dlc, 
                        data
                    ])

        # 2. Receive CANFD frames
        rcv_canfd_num = zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CANFD)
        if rcv_canfd_num:
            rcv_canfd_msgs, rcv_canfd_num = zcanlib.ReceiveFD(chn_handle, min(rcv_canfd_num, 100), 100)
            for msg in rcv_canfd_msgs[:rcv_canfd_num]:
                frame = msg.frame
                brs = "加速" if frame.flags & 0x1 else ""
                can_type = "CANFD" + (" " + brs if brs else "")
                direction = "TX" if frame.flags & 0x20 else "RX"
                frame_type = "扩展帧" if frame.can_id & (1 << 31) else "标准帧"
                frame_format = "数据帧"
                can_id = hex(frame.can_id & 0x1FFFFFFF)
                data = " ".join([f"{num:02X}" for num in frame.data[:frame.len]])
                
                if record_active:
                    data_queue.put([
                        msg.timestamp, 
                        f"CAN{chn_handle & 0xFF}", 
                        can_type.strip(), 
                        direction, 
                        can_id, 
                        frame_type, 
                        frame_format, 
                        frame.len, 
                        data
                    ])

# ZLG Channel Initialization Helper
def USBCANFD_Start(zcanlib, device_handle, chn):
    # ISO Standard mode (0)
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/canfd_standard".encode("utf-8"), "0".encode("utf-8"))

    # Abit (Arbitration baudrate) and Dbit (Data baudrate)
    # Abit = 1Mbps, Dbit = 2Mbps
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/canfd_abit_baud_rate".encode("utf-8"), "1000000".encode("utf-8"))
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/canfd_dbit_baud_rate".encode("utf-8"), "2000000".encode("utf-8"))

    # Terminal resistance (Enable = 1)
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/initenal_resistance".encode("utf-8"), "1".encode("utf-8"))

    # Init config
    chn_init_cfg = ZCAN_CHANNEL_INIT_CONFIG()
    chn_init_cfg.can_type = ZCAN_TYPE_CANFD
    chn_init_cfg.config.canfd.mode = 0  # Normal mode
    
    chn_handle = zcanlib.InitCAN(device_handle, chn, chn_init_cfg)
    if chn_handle is None:
        print(f" [!] InitCAN for CH{chn} failed")
        return None

    # Disable tx echo
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/set_device_tx_echo".encode("utf-8"), "0".encode("utf-8"))

    # Enable merge receive
    zcanlib.ZCAN_SetValue(device_handle, "0/set_device_recv_merge".encode("utf-8"), "0".encode("utf-8"))

    # Start CAN channel
    ret = zcanlib.StartCAN(chn_handle)
    if ret != ZCAN_STATUS_OK:
        print(f" [!] StartCAN for CH{chn} failed")
        return None

    return chn_handle

# DP2031 Search and Connection Helper
def connect_dp2031():
    try:
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        print(f"[*] Scanned VISA resources: {resources}")
        
        # Rigol USB Vendor ID is '0x1AB1'
        candidates = [r for r in resources if 'DP' in r or '0x1AB1' in r]
        
        dp_resource = None
        for res in candidates:
            try:
                inst = rm.open_resource(res)
                inst.timeout = 2000
                idn = inst.query("*IDN?").strip()
                print(f" [+] Found device IDN: {idn} on resource {res}")
                if "DP" in idn:
                    dp_resource = res
                    inst.close()
                    break
                inst.close()
            except Exception as e:
                print(f" [!] Error querying resource {res}: {e}")
                
        if not dp_resource:
            # Fallback search through all resources
            for res in resources:
                if res in candidates:
                    continue
                try:
                    inst = rm.open_resource(res)
                    inst.timeout = 1000
                    idn = inst.query("*IDN?").strip()
                    if "DP" in idn:
                        dp_resource = res
                        inst.close()
                        break
                    inst.close()
                except:
                    pass
                    
        if dp_resource:
            print(f" [+] Connecting to DP2031 at: {dp_resource}")
            inst = rm.open_resource(dp_resource)
            inst.timeout = 5000
            return inst
        else:
            print(" [!] DP2031 not found. Please verify connections.")
            return None
    except Exception as e:
        print(f" [!] VISA error connecting to DP2031: {e}")
        return None

# DP2031 Parameter Configuration Helper
def setup_dp2031(inst):
    try:
        # Set Voltage and Current Limit
        inst.write(f":APPL CH{POWER_CHANNEL},{POWER_VOLTAGE:.3f},{POWER_CURRENT_LIMIT:.3f}")
        
        # Set OVP (Over Voltage Protection)
        inst.write(f":OUTP:OVP:VAL CH{POWER_CHANNEL},{POWER_OVP:.3f}")
        inst.write(f":OUTP:OVP CH{POWER_CHANNEL},ON")
        
        # Set OCP (Over Current Protection)
        inst.write(f":OUTP:OCP:VAL CH{POWER_CHANNEL},{POWER_OCP:.3f}")
        inst.write(f":OUTP:OCP CH{POWER_CHANNEL},ON")
        
        print(f" [+] DP2031 CH{POWER_CHANNEL} Configured: {POWER_VOLTAGE}V / {POWER_CURRENT_LIMIT}A (OVP={POWER_OVP}V, OCP={POWER_OCP}A)")
        return True
    except Exception as e:
        print(f" [!] Failed to configure DP2031 parameters: {e}")
        return False

def main():
    global record_active, thread_flag, zcanlib
    
    print("=" * 70)
    print("        DP2031 POWER CYCLER & CANFD DATA RECORDER")
    print("=" * 70)
    print(f" Output Target  : CH{POWER_CHANNEL} -> {POWER_VOLTAGE}V / {POWER_CURRENT_LIMIT}A limit")
    print(f" Capture Time   : {CAPTURE_DURATION_SEC} seconds")
    print(f" Wait Interval  : {WAIT_DURATION_MIN} minutes")
    print("=" * 70)

    # 1. Initialize ZLG ZCAN library
    try:
        zcanlib = ZCAN()
        print(">>> Zlgcan DLL 驱动载入成功！")
    except Exception as e:
        print(f" [!] 初始化 ZCAN 失败，可能是缺少核心 DLL 依赖，错误信息: {e}")
        sys.exit(1)

    # 2. Connect to DP2031 Power Supply
    dp_inst = connect_dp2031()
    if not dp_inst:
        print(" [!] Error: Cannot proceed without DP2031 power supply.")
        sys.exit(1)
        
    if not setup_dp2031(dp_inst):
        dp_inst.close()
        sys.exit(1)

    # 3. Create date-based directory dynamically
    date_str = datetime.now().strftime("%Y%m%d")
    data_dir = os.path.join(script_dir, date_str)
    os.makedirs(data_dir, exist_ok=True)
    print(f" [+] Data directory created: {data_dir}")

    # Set up ZLG device handles
    handle = INVALID_DEVICE_HANDLE
    chn_handles = []
    threads = []
    
    try:
        # 4. Open ZLG device
        print(">>> 正在尝试打开 USBCANFD-200U 设备...")
        handle = zcanlib.OpenDevice(ZCAN_USBCANFD_200U, 0, 0)
        if handle == INVALID_DEVICE_HANDLE:
            print(" [!] 打开设备失败！请确认设备是否已被其他软件占用，或者插拔 USB 后重试。")
            sys.exit(1)
        print(f" [+] 成功打开设备！设备句柄: {handle}")

        # Get device channels
        info = zcanlib.GetDeviceInf(handle)
        can_number = info.can_num

        # Start all channels
        print(">>> 正在配置并启动 CANFD 各通道...")
        for i in range(can_number):
            chn_handle = USBCANFD_Start(zcanlib, handle, i)
            if chn_handle is None:
                print(f" [!] 启动通道{i}失败！")
                sys.exit(1)
            chn_handles.append(chn_handle)
            print(f" [+] 通道{i}启动成功！通道句柄: {chn_handle}")

        # Start ZLG receiver threads
        print(">>> 正在启动数据接收线程...")
        for i in range(len(chn_handles)):
            t = threading.Thread(target=receive_thread, args=(handle, chn_handles[i]), daemon=True)
            threads.append(t)
            t.start()

        # 5. Core Cycle Loop
        cycle_num = 1
        while True:
            # Format output CSV path
            time_str = datetime.now().strftime("%H%M%S")
            filename = f"CAN_Record_Cycle{cycle_num:03d}_{time_str}.csv"
            filepath = os.path.join(data_dir, filename)

            print(f"\n=======================================================")
            print(f" >>> [Cycle {cycle_num}] Powering ON & Starting Acquisition <<<")
            print(f" Save Path: {filepath}")
            print(f"=======================================================")

            # Prepare data buffers
            record_active = False
            # Drain queue to discard any background noise/idle frames
            while not data_queue.empty():
                try:
                    data_queue.get_nowait()
                except queue.Empty:
                    break

            # Turn recording on
            record_active = True

            # Power ON the DP2031
            print(f"[*] Turning DP2031 Output ON...")
            dp_inst.write(f":OUTP CH{POWER_CHANNEL},ON")

            # Capture data for CAPTURE_DURATION_SEC
            for elapsed in range(CAPTURE_DURATION_SEC):
                time.sleep(1.0)
                print(f"  Recording... {elapsed + 1}/{CAPTURE_DURATION_SEC}s", end="\r")
            print("\n[*] Capturing complete. Powering off...")

            # Power OFF the DP2031
            dp_inst.write(f":OUTP CH{POWER_CHANNEL},OFF")
            print(f"[*] Turning DP2031 Output OFF.")

            # Short sleep to allow the last few frames to get queued
            time.sleep(0.5)

            # Turn recording off
            record_active = False

            # Drain queue and write to CSV
            frames = []
            while not data_queue.empty():
                try:
                    frames.append(data_queue.get_nowait())
                except queue.Empty:
                    break

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # Headings matching standard pipeline
                writer.writerow(['Timestamp', 'Channel', 'CAN_Type', 'Direction', 'ID', 'Frame_Type', 'Frame_Format', 'DLC_Len', 'Data_Hex'])
                writer.writerows(frames)

            print(f" [+] Success: Captured {len(frames)} frames for Cycle {cycle_num}.")
            cycle_num += 1

            # Countdown Wait Interval
            wait_seconds = WAIT_DURATION_MIN * 60
            print(f"[*] Cooling down: waiting {WAIT_DURATION_MIN} minutes ({wait_seconds}s) before next cycle...")
            for remaining in range(wait_seconds, 0, -1):
                print(f"  Next cycle in {remaining:3d}s... (Ctrl+C to Stop)", end="\r")
                time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\n[!] Test sequence stopped by user (KeyboardInterrupt).")
    finally:
        print("\n[*] Performing final cleanup and shutdown...")
        # 1. Stop receiver threads
        thread_flag = False
        for t in threads:
            if t.is_alive():
                t.join(timeout=1.0)

        # 2. Reset CAN channels
        for i, h in enumerate(chn_handles):
            try:
                zcanlib.ResetCAN(h)
                print(f" [+] Closed ZLG CAN Channel {i}")
            except Exception as e:
                print(f" [!] Error closing ZLG CAN Channel {i}: {e}")

        # 3. Close ZLG Device
        if handle != INVALID_DEVICE_HANDLE:
            try:
                zcanlib.CloseDevice(handle)
                print(" [+] Closed ZLG Device")
            except Exception as e:
                print(f" [!] Error closing ZLG Device: {e}")

        # 4. Turn off DP2031 output (CRITICAL SAFETY STEP)
        if dp_inst is not None:
            try:
                print(f"[*] Shutting down DP2031 CH{POWER_CHANNEL} output...")
                dp_inst.write(f":OUTP CH{POWER_CHANNEL},OFF")
                dp_inst.close()
                print(" [+] Closed DP2031 resource connection")
            except Exception as e:
                print(f" [!] Error shutting down DP2031: {e}")
        
        print(" [√] Cleanup complete. Exiting.")

if __name__ == "__main__":
    main()
