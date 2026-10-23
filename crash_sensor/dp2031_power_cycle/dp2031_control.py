# -*- coding: utf-8 -*-
"""
    DP2031 Dual Channel Control & ZLG CANFD Data Collector
"""

import sys
import os
import time
import threading
import queue
import matplotlib.pyplot as plt
from datetime import datetime

# ==============================================================================
#                      GLOBAL CONFIGURATION / 全局参数配置
# ==============================================================================
# ---- CH1 配置 (一直供电) ----
CH1_VOLTAGE = 6.0          # CH1 电压 (V)
CH1_CURRENT_LIMIT = 0.100  # CH1 限流 (A), 100mA

# ---- CH2 配置 (高低电平循环) ----
CH2_V_HIGH = 2.0           # CH2 高电平电压 (V)
CH2_V_LOW = 1.0            # CH2 低电平电压 (V)
CH2_CURRENT_LIMIT = 0.010  # CH2 限流 (A), 10mA
CYCLE_INTERVAL_SEC = 2.0   # 循环时间间隔 (秒)
TOTAL_DURATION_SEC = 10.0  # 总运行采集时长 (秒)

# CAN 发送指令时间间隔 (秒)
CMD_INTERVAL = 0.02
# ==============================================================================

# ================= 确切环境依赖注入 =================
script_dir = os.path.dirname(os.path.abspath(__file__))
candidate_dirs = [
    os.path.abspath(os.path.join(script_dir, "..", "zlgcan_file", "zlgcan_python_251211")),
    r"d:\project_momo\auto-chip-validation-framework\crash_sensor\zlgcan_file\zlgcan_python_251211",
    os.path.abspath(os.path.join(script_dir, "..", "..", "zlgcan_file", "zlgcan_python_251211")),
]
zlgcan_real_dir = next((d for d in candidate_dirs if os.path.exists(d)), candidate_dirs[0])
kernel_dir = os.path.join(zlgcan_real_dir, "kerneldlls")

sys.path.insert(0, zlgcan_real_dir)

if hasattr(os, 'add_dll_directory'):
    try:
        os.add_dll_directory(zlgcan_real_dir)
        if os.path.exists(kernel_dir):
            os.add_dll_directory(kernel_dir)
    except Exception as e:
        print(f"Warning: Failed to add DLL directory: {e}")

os.environ['PATH'] = zlgcan_real_dir + os.pathsep + kernel_dir + os.pathsep + os.environ.get('PATH', '')

original_cwd = os.getcwd()
try:
    os.chdir(zlgcan_real_dir)
    from zlgcan import *
    print(f"成功在指定目录加载 Zlgcan 环境")
finally:
    os.chdir(original_cwd)
# ===================================================

try:
    import pyvisa
except ImportError:
    print(" [!] pyvisa is not installed. Please run: pip install pyvisa")
    sys.exit(1)

# Thread-safe logging structures
data_queue = queue.Queue()
thread_flag = True

def receive_thread(device_handle, chn_handle):
    global thread_flag
    print_count = 0
    last_print_time = 0
    
    while thread_flag:
        time.sleep(0.005)
        
        # 1. 尝试接收标准 CAN 报文
        rcv_num = zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
        if rcv_num:
            rcv_msg, rcv_num = zcanlib.Receive(chn_handle, min(rcv_num, 100), 100)
            for msg in rcv_msg[:rcv_num]:
                frame = msg.frame
                dlc = frame.can_dlc
                data_list = [f"{num:02X}" for num in frame.data[:dlc]]
                data_str = " ".join(data_list)
                
                # 每秒或每 50 帧打印一次
                print_count += 1
                if print_count <= 5 or time.time() - last_print_time > 1.0:
                    print(f" [CAN] 收 数据: {data_str} (ID: {hex(frame.can_id & 0x1FFFFFFF)})")
                    last_print_time = time.time()

                if len(data_list) >= 5:
                    hex_str = data_list[3] + data_list[4]
                    raw_val = int(hex_str, 16)
                    dec_val = 32767 - raw_val
                    data_queue.put({"hw_time": msg.timestamp, "sw_time": time.time(), "val": dec_val})

        # 2. 尝试接收 CANFD 报文
        rcv_canfd_num = zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CANFD)
        if rcv_canfd_num:
            rcv_canfd_msgs, rcv_canfd_num = zcanlib.ReceiveFD(chn_handle, min(rcv_canfd_num, 100), 100)
            for msg in rcv_canfd_msgs[:rcv_canfd_num]:
                frame = msg.frame
                data_list = [f"{num:02X}" for num in frame.data[:frame.len]]
                data_str = " ".join(data_list)
                
                print_count += 1
                if print_count <= 5 or time.time() - last_print_time > 1.0:
                    print(f" [CANFD] 收 数据: {data_str} (ID: {hex(frame.can_id & 0x1FFFFFFF)})")
                    last_print_time = time.time()
                
                if len(data_list) >= 5:
                    hex_str = data_list[3] + data_list[4]
                    raw_val = int(hex_str, 16)
                    dec_val = 32767 - raw_val
                    data_queue.put({"hw_time": msg.timestamp, "sw_time": time.time(), "val": dec_val})


def USBCANFD_Start(zcanlib, device_handle, chn):
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/canfd_standard", "0".encode("utf-8"))
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/canfd_abit_baud_rate", "1000000".encode("utf-8"))
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/canfd_dbit_baud_rate", "2000000".encode("utf-8"))
    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/initenal_resistance", "1".encode("utf-8"))

    chn_init_cfg = ZCAN_CHANNEL_INIT_CONFIG()
    chn_init_cfg.can_type = ZCAN_TYPE_CANFD
    chn_init_cfg.config.canfd.mode = 0
    
    chn_handle = zcanlib.InitCAN(device_handle, chn, chn_init_cfg)
    if chn_handle is None:
        print(f" [!] InitCAN for CH{chn} failed")
        return None

    zcanlib.ZCAN_SetValue(device_handle, f"{chn}/set_device_tx_echo", "0".encode("utf-8"))
    zcanlib.ZCAN_SetValue(device_handle, "0/set_device_recv_merge", "0".encode("utf-8"))

    ret = zcanlib.StartCAN(chn_handle)
    if ret != ZCAN_STATUS_OK:
        print(f" [!] StartCAN for CH{chn} failed")
        return None

    return chn_handle

def connect_dp2031():
    try:
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        candidates = [r for r in resources if 'DP' in r or '0x1AB1' in r]
        
        dp_resource = None
        for res in candidates:
            try:
                inst = rm.open_resource(res)
                inst.timeout = 2000
                idn = inst.query("*IDN?").strip()
                if "DP" in idn:
                    dp_resource = res
                    inst.close()
                    break
                inst.close()
            except:
                pass
                
        if dp_resource:
            inst = rm.open_resource(dp_resource)
            inst.timeout = 5000
            return inst
        return None
    except Exception as e:
        print(f" [!] VISA error connecting to DP2031: {e}")
        return None

def send_canfd_cmd(zcanlib, chn_handle, can_id, data_str, mute=False):
    msg = ZCAN_TransmitFD_Data()
    msg.transmit_type = 0 # 正常发送
    msg.frame.can_id = can_id
    
    data_bytes = bytes.fromhex(data_str.replace(" ", ""))
    msg.frame.len = len(data_bytes)
    for i in range(msg.frame.len):
        msg.frame.data[i] = data_bytes[i]
        
    ret = zcanlib.TransmitFD(chn_handle, msg, 1)
    if not mute:
        if ret == 1:
            print(f" [+] 发送 CAN ID {hex(can_id)} 数据 {data_str} 成功")
        else:
            print(f" [!] 发送 CAN ID {hex(can_id)} 数据 {data_str} 失败")

def main():
    global thread_flag, zcanlib
    
    print("=" * 60)
    print(" DP2031 + ZLG CANFD 数据采集脚本")
    print("=" * 60)
    
    try:
        zcanlib = ZCAN()
        print(" [+] Zlgcan DLL 驱动载入成功")
    except Exception as e:
        print(f" [!] 初始化 ZCAN 失败: {e}")
        sys.exit(1)

    dp_inst = connect_dp2031()
    if not dp_inst:
        print(" [!] 无法连接到 DP2031，请检查连接。")
        sys.exit(1)
        
    print(" [+] 成功连接 DP2031")

    handle = INVALID_DEVICE_HANDLE
    chn_handle = None
    t_receive = None
    
    # 记录画图的数据
    ch2_record_times = []
    ch2_voltages = []
    
    chip_record_times = []
    chip_sw_times = []
    chip_data = []

    try:
        handle = zcanlib.OpenDevice(ZCAN_USBCANFD_200U, 0, 0)
        if handle == INVALID_DEVICE_HANDLE:
            print(" [!] 打开 USBCANFD-200U 设备失败！")
            sys.exit(1)
            
        chn_handle = USBCANFD_Start(zcanlib, handle, 0) # 假设使用通道 0
        if not chn_handle:
            sys.exit(1)

        t_receive = threading.Thread(target=receive_thread, args=(handle, chn_handle), daemon=True)
        t_receive.start()

        # ---- DP2031 初始设置及上电 ----
        # CH1 配置并打开
        dp_inst.write(f":APPL CH1,{CH1_VOLTAGE:.3f},{CH1_CURRENT_LIMIT:.3f}")
        dp_inst.write(":OUTP CH1,ON")
        print(f" [*] CH1 已打开: {CH1_VOLTAGE}V / {CH1_CURRENT_LIMIT}A")
        
        # 为了保证 1-2 通道直接时间间隔为 1s，这里先小睡一下让 CH1 稳定，再发 CAN 指令
        # 假设 CAN 指令总共耗时约 0.1s，我们直接在指令发完后补偿剩余时间
        time.sleep(0.1)
        
        # ---- 发送 CAN 指令序列 ----
        # 1. 打开 cv adc 使能
        send_canfd_cmd(zcanlib, chn_handle, 0x391, "04 00 04 00 00 7f ff ff ff ff ff ff")
        time.sleep(CMD_INTERVAL)
        
        # 2. 关快慢偏
        send_canfd_cmd(zcanlib, chn_handle, 0x391, "04 00 02 00 ff ff 00 00 ff ff ff ff")
        time.sleep(CMD_INTERVAL)
        
        # 3. 读 y 轴数据 (开启返回数据)
        send_canfd_cmd(zcanlib, chn_handle, 0x393, "04 00 11 00 00 00 00 00")
        time.sleep(CMD_INTERVAL)
        
        # 补充剩余延时，凑足 1 秒间隔
        time.sleep(1.0 - 0.1 - (3 * CMD_INTERVAL))
        
        print(" [*] 初始化指令发送完毕，开始循环切换 CH2 电平并采集数据...")
        
        # ---- 循环控制 CH2 电平 ----
        start_time = time.time()
        ch2_state_high = True
        
        print(f" [*] 正在循环采集，总时长设为 {TOTAL_DURATION_SEC} 秒...")
        while time.time() - start_time < TOTAL_DURATION_SEC:
            current_v = CH2_V_HIGH if ch2_state_high else CH2_V_LOW
            dp_inst.write(f":APPL CH2,{current_v:.3f},{CH2_CURRENT_LIMIT:.3f}")
            dp_inst.write(":OUTP CH2,ON")
            print(f"  -> 切换 CH2 电压为 {current_v}V")
            
            # 单独记录 CH2 的变化时间点
            ch2_record_times.append(time.time() - start_time)
            ch2_voltages.append(current_v)
            
            # 等待一个循环间隔，在此期间将采集数据
            cycle_start = time.time()
            while time.time() - cycle_start < CYCLE_INTERVAL_SEC:
                if time.time() - start_time >= TOTAL_DURATION_SEC:
                    break
                
                # 持续发送查询指令，让芯片不断返回数据
                send_canfd_cmd(zcanlib, chn_handle, 0x393, "04 00 11 00 00 00 00 00", mute=True)

                # 把队列中的数据取出来
                while not data_queue.empty():
                    item = data_queue.get()
                    chip_record_times.append(item['hw_time'])
                    chip_sw_times.append(item['sw_time'])
                    chip_data.append(item['val'])
                    
                time.sleep(CMD_INTERVAL)
                
            # 状态翻转
            ch2_state_high = not ch2_state_high
            
        # 为 step 图追加结束点
        if ch2_record_times:
            ch2_record_times.append(time.time() - start_time)
            ch2_voltages.append(ch2_voltages[-1])

    except KeyboardInterrupt:
        print("\n [!] 用户停止采集，准备生成图表...")
    finally:
        # 清理与关闭
        thread_flag = False
        if t_receive and t_receive.is_alive():
            t_receive.join(timeout=1.0)

        if chn_handle:
            zcanlib.ResetCAN(chn_handle)
        if handle != INVALID_DEVICE_HANDLE:
            zcanlib.CloseDevice(handle)
            
        # 清空最后残余的队列数据
        while not data_queue.empty():
            item = data_queue.get()
            chip_record_times.append(item['hw_time'])
            chip_sw_times.append(item['sw_time'])
            chip_data.append(item['val'])
            
        print(" [*] 关闭 DP2031 输出...")
        if dp_inst:
            dp_inst.write(":OUTP CH1,OFF")
            dp_inst.write(":OUTP CH2,OFF")
            dp_inst.close()

        # 绘图
        if chip_record_times and ch2_record_times:
            print(" [*] 绘制图表 (已采用底层硬件时间戳 + 右对齐逆推法)...")
            
            # CAN 数据右对齐逆推 (优先使用硬件时间戳，除数 1e6)
            max_hw_time = max(chip_record_times)
            aligned_chip_times = []
            filtered_chip_data = []
            
            time_divisor = 1000000.0
            
            for hw_t, val in zip(chip_record_times, chip_data):
                rel_t = TOTAL_DURATION_SEC - ((max_hw_time - hw_t) / time_divisor)
                if rel_t >= 0:
                    aligned_chip_times.append(rel_t)
                    filtered_chip_data.append(val)
                    
            # 自动纠错机制：如果硬件时间戳计算导致数据全部挤在一起 (例如跨度 < 0.5s，即“只有一小截”)
            # 这意味着设备的硬件时间戳单位可能不是 1us (可能是 100us)，强制回退到软件时间戳来绘图保证正确
            span_hw = max(aligned_chip_times) - min(aligned_chip_times) if aligned_chip_times else 0
            if span_hw < 0.5 and len(chip_sw_times) > 10:
                print(" [!] 检测到硬件时间戳可能导致时间轴严重挤压（只有一小截），自动启用系统时间戳对齐...")
                max_sw_time = max(chip_sw_times)
                aligned_chip_times = []
                filtered_chip_data = []
                for sw_t, val in zip(chip_sw_times, chip_data):
                    rel_t = TOTAL_DURATION_SEC - (max_sw_time - sw_t)
                    if rel_t >= 0:
                        aligned_chip_times.append(rel_t)
                        filtered_chip_data.append(val)
                    
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
            
            # 绘制 CAN 数据 (左轴 -> 上方子图 ax1)
            color1 = 'tab:blue'
            ax1.set_ylabel('CAN Decoded Value (Decimal)', color=color1, fontname='Times New Roman', fontsize=14)
            ax1.plot(aligned_chip_times, filtered_chip_data, color=color1, label='CAN Data', marker='.', linestyle='none', alpha=0.7)
            ax1.tick_params(axis='y', labelcolor=color1)
            ax1.grid(True, linestyle='--', alpha=0.5)
            ax1.set_title('Synchronized CAN Data and Power Supply Waveform', fontname='Times New Roman', fontsize=14)

            # 绘制 DP2031 CH2 电压波形 (右轴 -> 下方子图 ax2)
            color2 = 'tab:red'
            ax2.set_xlabel('Time (s)', fontname='Times New Roman', fontsize=14)
            ax2.set_ylabel('DP2031 CH2 Voltage (V)', color=color2, fontname='Times New Roman', fontsize=14)
            
            ax2.step(ch2_record_times, ch2_voltages, where='post', color=color2, label='CH2 Output', linewidth=2)
            ax2.tick_params(axis='y', labelcolor=color2)
            
            # 强制固定右轴的范围，使得方波显示居中
            y_upper_limit = CH2_V_HIGH + 2.0
            ax2.set_ylim(-1, y_upper_limit)
            ax2.grid(True, linestyle='--', alpha=0.5)
            
            # 强制限制 X 轴的显示范围，确保上下两张图的视觉起点绝对锁定在 0
            ax1.set_xlim(0, TOTAL_DURATION_SEC)
            ax2.set_xlim(0, TOTAL_DURATION_SEC)
            
            fig.tight_layout()
            
            # 保存图片到同一目录下
            img_path = os.path.join(script_dir, f"result_plot_{datetime.now().strftime('%H%M%S')}.png")
            plt.savefig(img_path)
            print(f" [+] 图表已保存至: {img_path}")
            
            plt.show()
        else:
            print(" [!] 未采集到足够的数据进行绘图")


if __name__ == "__main__":
    main()
