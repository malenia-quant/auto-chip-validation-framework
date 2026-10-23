# -*- coding:utf-8 -*-
'''
    支持的设备有 USBCANFD-100U mini   USBCANFD-100U/200U/400U/800U
    例程使用之前，请确定Line455 opendevice打开的是对应型号的设备

    [mozial 修改]：针对 USBCANFD-200U 纯读取记录需求定制化裁剪。
    根据截图配置：CAN FD ISO, BRS加速, 仲裁域 1Mbps, 数据域 2Mbps, 启用终端电阻。
'''

import sys
import os
import threading
import time
import csv
import queue
from datetime import datetime

# 强制标准输出使用 UTF-8 编码，防止跨进程管道传输中文出现乱码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ================= 确切环境依赖注入 =================
# [mozial 修改] 遵循“以盲想业务为耻，以人类确认为荣”原则
# 动态定位当前脚本文件所在路径，彻底避免硬编码绝对路径
script_dir = os.path.dirname(os.path.abspath(__file__))
zlgcan_real_dir = os.path.join(script_dir, "zlgcan_python_251211")
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
print(f"强制优先加载并注册指定驱动及子依赖库目录: {zlgcan_real_dir}")

# 4. 终极物理隔离打破：强行将当前工作目录切换到驱动文件夹，确保依赖 DLL 顺利载入
original_cwd = os.getcwd()
try:
    os.chdir(zlgcan_real_dir)
    from zlgcan import *
    print(f"成功在指定目录加载 Zlgcan 环境，并已注册子依赖库目录")
finally:
    os.chdir(original_cwd)
# ===================================================
#             实时数据终端显示配置 (DISPLAY CONFIG)
# ===================================================
# DISPLAY_MODE 支持以下显示模式:
#   "interval" - 周期汇总模式：按照 DISPLAY_INTERVAL 设定的周期时间，在终端汇总输出（推荐，防止刷屏卡顿）
#   "always"   - 始终接收模式：每收到一帧数据，立即在终端实时打印输出
#   "mute"     - 屏蔽实时显示模式：终端不打印任何实时接收数据，仅静默且完整地写入 CSV 文件
DISPLAY_MODE = "interval"

# 当选择 "interval" 周期汇总模式时，终端汇总数据输出的刷新频率 (设为 15 秒，参考用户指定要求)
DISPLAY_INTERVAL = 15

# 兼容旧配置：如果配置的 DISPLAY_MODE 是一个以 's' 结尾的字符串或纯数字，自动转为 "interval" 模式并解析出对应的秒数
if isinstance(DISPLAY_MODE, (int, float)):
    DISPLAY_INTERVAL = float(DISPLAY_MODE)
    DISPLAY_MODE = "interval"
elif isinstance(DISPLAY_MODE, str):
    if DISPLAY_MODE.endswith("s") and DISPLAY_MODE[:-1].replace(".", "", 1).isdigit():
        try:
            DISPLAY_INTERVAL = float(DISPLAY_MODE[:-1])
            DISPLAY_MODE = "interval"
        except ValueError:
            pass
    elif DISPLAY_MODE.replace(".", "", 1).isdigit():
        try:
            DISPLAY_INTERVAL = float(DISPLAY_MODE)
            DISPLAY_MODE = "interval"
        except ValueError:
            pass

# 当选择 "interval" 模式时，每个周期内最多打印的帧数
MAX_PRINT_PER_PERIOD = 3

# 终端打印同步锁、数据缓冲、全局接收计数器与采集启动时间
print_buffer_lock = threading.Lock()
pending_prints = []
initial_print_count = 0
MAX_INITIAL_PRINTS = 3
global_received_count = 0
capture_proc_start_time = time.time()
# ===================================================

thread_flag = True
print_lock = threading.Lock()  # 线程锁，只是为了打印不冲突
enable_merge_receive = 0  # 合并接收标识
enable_bus_usage = 0  # 总线利用率上报标识

# [新增数据缓冲队列]
data_queue = queue.Queue()


# [新增功能模块] CSV 异步写入线程
def csv_writer_thread(custom_output_path=None):
    if custom_output_path:
        full_path = os.path.abspath(custom_output_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
    else:
        # 确保默认保存目录存在
        save_dir = os.path.join(script_dir, "pz_test_data")
        os.makedirs(save_dir, exist_ok=True)
        # 生成带有时间戳的文件名，防止多次运行覆盖文件
        base_filename = datetime.now().strftime("CAN_Record_%Y%m%d_%H%M%S.csv")
        full_path = os.path.join(save_dir, base_filename)

    with open(full_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # 写入 CSV 表头
        writer.writerow(['Timestamp', 'Channel', 'CAN_Type', 'Direction', 'ID', 'Frame_Type', 'Frame_Format', 'DLC_Len',
                         'Data_Hex'])
        f.flush()

        flush_interval = 0.5
        last_flush = time.time()
        while thread_flag or not data_queue.empty():
            try:
                # 设置超时，避免主线程退出时该线程死锁
                row = data_queue.get(timeout=0.2)
                writer.writerow(row)
                now = time.time()
                if now - last_flush >= flush_interval:
                    f.flush()
                    last_flush = now
            except queue.Empty:
                continue
        f.flush()
    print(f"所有缓冲数据已保存至文件: {full_path} (累计捕获帧数: {global_received_count})", flush=True)
    sys.stdout.flush()


# [新增功能模块] 实时数据分流处理与终端打印控制
def log_and_queue_frame(timestamp, chnl_str, can_type, direction, can_id, frame_type, frame_format, dlc, data):
    global initial_print_count, global_received_count
    # 1. 存入 CSV 写入队列（无论何种显示模式，都在后台完整记录）
    data_queue.put([timestamp, chnl_str, can_type, direction, can_id, frame_type, frame_format, dlc, data])
    global_received_count += 1
    
    # 2. 实时终端显示控制
    if DISPLAY_MODE == "mute":
        return
        
    log_str = f"[{timestamp}] {chnl_str} {can_type:<8} {direction} ID:{can_id:<10} {frame_type} {frame_format} DLC:{dlc:<2} Data: {data}"
    
    if DISPLAY_MODE == "always":
        with print_lock:
            print(log_str)
            sys.stdout.flush()
    elif DISPLAY_MODE == "interval":
        with print_buffer_lock:
            # 最开始运行的时候实时输出一次，显示通信握手成功
            if initial_print_count < MAX_INITIAL_PRINTS:
                initial_print_count += 1
                if initial_print_count == 1:
                    print("\n--- [CAN 实时数据监控] 成功捕获首批数据： ---")
                print(f"[CAN首批握手] {log_str}")
                sys.stdout.flush()
                if initial_print_count == MAX_INITIAL_PRINTS:
                    print(f"... 首批握手帧接收成功，后续每 {DISPLAY_INTERVAL}s 汇总抽样输出最新数据\n")
                    sys.stdout.flush()
            else:
                # 放入缓冲，用于周期汇总
                pending_prints.append(log_str)


# [新增功能模块] 周期性终端汇总打印线程
def periodic_printer_thread():
    while thread_flag:
        sleep_elapsed = 0.0
        while thread_flag and sleep_elapsed < DISPLAY_INTERVAL:
            time.sleep(0.1)
            sleep_elapsed += 0.1
            
        if not thread_flag:
            break
            
        with print_buffer_lock:
            total_period_count = len(pending_prints)
            if total_period_count > 0:
                latest_sample = pending_prints[-1]
                with print_lock:
                    print(f"[CAN实时监控] 过去 {DISPLAY_INTERVAL}s 接收 {total_period_count} 帧 (累计: {global_received_count} 帧) | 最新抽样: {latest_sample}", flush=True)
                pending_prints.clear()
            else:
                # 若当前没有任何帧接收到，且已经启动 > 2 秒，给出明确的提示预警
                elapsed_total = time.time() - capture_proc_start_time
                if global_received_count == 0 and elapsed_total >= 2.0:
                    with print_lock:
                        print(f"[CAN总线监控] [警告] 总线静默，当前仍未接收到任何 CAN 帧 (已等待 {int(elapsed_total)}s)！请确认: 1. 离心机/被测器件是否已上电；2. CAN_H/CAN_L 物理接线与终端电阻。", flush=True)


# 读取设备信息
def Read_Device_Info(device_handle):
    # 获取设备信息
    info = zcanlib.GetDeviceInf(device_handle)
    print("设备信息: \n%s" % info, flush=True)

    print("----------------------: %s" % info.fw_version, flush=True)

    can_number = info.can_num
    return can_number


# 接收线程
def receive_thread(device_handle, chn_handle):
    # 方便打印对齐 --无实际作用
    CANType_width = len("CANFD加速    ")
    id_width = len(hex(0x1FFFFFFF))

    while thread_flag:
        try:
            time.sleep(0.005)
            rcv_num = zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)  # CAN
            if rcv_num:
                if rcv_num > 100:
                    rcv_msg, rcv_num = zcanlib.Receive(chn_handle, 100, 100)
                else:
                    rcv_msg, rcv_num = zcanlib.Receive(chn_handle, rcv_num, 100)
                if rcv_msg:
                    for msg in rcv_msg[:rcv_num]:
                        can_type = "CAN   "
                        frame = msg.frame
                        direction = "TX" if frame._pad & 0x20 else "RX"
                        frame_type = "扩展帧" if frame.can_id & (1 << 31) else "标准帧"
                        frame_format = "远程帧" if frame.can_id & (1 << 30) else "数据帧"
                        can_id = hex(frame.can_id & 0x1FFFFFFF)

                        if frame.can_id & (1 << 30):
                            data = ""
                            dlc = 0
                        else:
                            dlc = frame.can_dlc
                            data = " ".join([f"{num:02X}" for num in frame.data[:dlc]])

                        log_and_queue_frame(msg.timestamp, f"CAN{chn_handle & 0xFF}", can_type.strip(), direction, can_id, frame_type, frame_format, dlc, data)

            rcv_canfd_num = zcanlib.GetReceiveNum(chn_handle, ZCAN_TYPE_CANFD)  # CANFD
            if rcv_canfd_num:
                if rcv_canfd_num > 100:
                    rcv_canfd_msgs, rcv_canfd_num = zcanlib.ReceiveFD(chn_handle, 100, 100)
                else:
                    rcv_canfd_msgs, rcv_canfd_num = zcanlib.ReceiveFD(chn_handle, rcv_canfd_num, 100)
                if rcv_canfd_msgs:
                    for msg in rcv_canfd_msgs[:rcv_canfd_num]:
                        frame = msg.frame
                        brs = "加速" if frame.flags & 0x1 else "   "
                        can_type = "CANFD" + brs
                        direction = "TX" if frame.flags & 0x20 else "RX"
                        frame_type = "扩展帧" if frame.can_id & (1 << 31) else "标准帧"
                        frame_format = "远程帧" if frame.can_id & (1 << 30) else "数据帧"  # CANFD没有远程帧
                        can_id = hex(frame.can_id & 0x1FFFFFFF)
                        data = " ".join([f"{num:02X}" for num in frame.data[:frame.len]])

                        log_and_queue_frame(msg.timestamp, f"CAN{chn_handle & 0xFF}", can_type.strip(), direction, can_id, frame_type, frame_format, frame.len, data)

            rcv_merge_num = zcanlib.GetReceiveNum(device_handle, ZCAN_TYPE_MERGE)  # CANFD
            if rcv_merge_num:
                if rcv_merge_num > 100:
                    rcv_merger_msgs, rcv_merge_num = zcanlib.ReceiveData(device_handle, 100, 100)
                else:
                    rcv_merger_msgs, rcv_merge_num = zcanlib.ReceiveData(device_handle, rcv_merge_num, 100)
                if rcv_merger_msgs:
                    for msg in rcv_merger_msgs[:rcv_merge_num]:
                        if msg.dataType == ZCAN_DT_ZCAN_CAN_CANFD_DATA:
                            flag = msg.zcanfddata.flag
                            frame = msg.zcanfddata.frame
                            type = "CANFD" if flag.frameType else "CAN"
                            brs = "加速" if (frame.flags & 0x1) else "   "
                            can_type = type + brs
                            direction = "TX" if msg.zcanfddata.flag.txEchoed else "RX"
                            frame_type = "扩展帧" if frame.can_id & (1 << 31) else "标准帧"
                            frame_format = "远程帧" if frame.can_id & (1 << 30) else "数据帧"
                            can_id = frame.can_id & 0x1FFFFFFF
                            data = " ".join([f"{num:02X}" for num in frame.data[:frame.len]])

                            log_and_queue_frame(msg.zcanfddata.timestamp, f"CAN{msg.chnl}", can_type.strip(), direction, hex(can_id), frame_type, frame_format, frame.len, data)
        except Exception as e:
            with print_lock:
                print(f"[CAN接收通道异常] 通道句柄 {chn_handle}: {e}", flush=True)
            time.sleep(0.05)


# 设置滤波  白名单过滤(只接收范围内的数据)    USBCANFD设备支持设置最多64组滤波
def Set_Filter(device_handle, chn):
    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_clear", "0".encode("utf-8"))  # 清除滤波
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_clear failed!" % chn)
        return None

    # 流程为：for【set_mode(与前一组滤波同类型可以省略) + set_start + set_end】+ ack
    # 这里设置第一道滤波：标准帧0~0x7F，第二道滤波：标准帧0xFF~0x1FF，第三道滤波：扩展帧0xFF~0x2FF
    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_mode", "0".encode("utf-8"))  # 设置滤波模式 标准帧滤波
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_mode failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_start", "0".encode("utf-8"))  # 设置白名单范围 起始ID
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_start failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_end", "0x7F".encode("utf-8"))  # 设置白名单范围 结束ID
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_end failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_start", "0xFF".encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_start failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_end", "0x1FF".encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_end failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_mode", "1".encode("utf-8"))  # 扩展帧滤波
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_mode failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_start", "0xFF".encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_start failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_end", "0x2FF".encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_end failed!" % chn)
        return None

    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_ack", "0".encode("utf-8"))  # 使能滤波
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  filter_ack failed!" % chn)
        return None


# 启动通道
def USBCANFD_Start(zcanlib, device_handle, chn):
    # 设置控制器设备类型，如果不是 Non-ISO CANFD 可注释掉按设备默认即可 CAN/CANFD 都是默认
    # [mozial 修改]：根据截图配置，这里强制解除注释并设置为 0 (ISO标准)
    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/canfd_standard", "0".encode("utf-8"))

    # 仲裁域波特率 和 数据域波特率
    # [mozial 修改]：根据截图，仲裁域修改为1Mbps (原500k)，数据域保持2Mbps
    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/canfd_abit_baud_rate", "1000000".encode("utf-8"))
    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/canfd_dbit_baud_rate", "2000000".encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d baud failed!" % chn)
        return None

    # 终端电阻
    # [mozial 核对]：截图显示使能，保持原状 "1"
    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/initenal_resistance", "1".encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Open CH%d resistance failed!" % chn)
        return None

    # 清除任何历史残留滤波规则，确保所有 ID 正常接收
    try:
        zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_clear", "0".encode("utf-8"))
        zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/filter_ack", "0".encode("utf-8"))
    except Exception:
        pass

    # 初始化通道
    chn_init_cfg = ZCAN_CHANNEL_INIT_CONFIG()
    chn_init_cfg.can_type = ZCAN_TYPE_CANFD  # USBCANFD 必须选择CANFD
    chn_init_cfg.config.canfd.mode = 0  # 0-正常模式 1-只听模式
    chn_init_cfg.config.canfd.acc_code = 0
    chn_init_cfg.config.canfd.acc_mask = 0xFFFFFFFF  # 明确全通掩码，接收所有 CAN 帧
    chn_init_cfg.config.canfd.filter = 0
    chn_handle = zcanlib.InitCAN(device_handle, chn, chn_init_cfg)
    if chn_handle is None:
        print("initCAN failed!" % chn)
        return None

    # 设置发送回显
    ret = zcanlib.ZCAN_SetValue(device_handle, str(chn) + "/set_device_tx_echo",
                                "0".encode("utf-8"))  # 发送回显设置，0-禁用，1-开启
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d  set_device_tx_echo failed!" % (chn))
        return None

    # 使能/关闭合并接收(startCAN 之前)    0-关闭 1-使能
    ret = zcanlib.ZCAN_SetValue(device_handle, str(0) + "/set_device_recv_merge", str(enable_merge_receive).encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Open CH%d recv merge failed!" % chn)
        return None

    # 使能总线利用率上报
    ret = zcanlib.ZCAN_SetValue(device_handle, "0/set_bus_usage_enable", str(enable_bus_usage).encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d set_bus_usage_enable failed!" % chn)
        return None

    # 设置总线利用率信息上报周期 20~2000ms
    ret = zcanlib.ZCAN_SetValue(device_handle, "0/set_bus_usage_period", "50".encode("utf-8"))
    if ret != ZCAN_STATUS_OK:
        print("Set CH%d set_bus_usage_enable failed!" % chn)
        return None

    # 启动通道
    ret = zcanlib.StartCAN(chn_handle)
    if ret != ZCAN_STATUS_OK:
        print("startCAN failed!" % chn)
        return None

    return chn_handle


# 设置自定义序列号
def Set_Device_Name(device_handle):
    ret = zcanlib.ZCAN_SetValue(handle, "0/set_cn", "A001".encode("utf-8"))
    if ret == ZCAN_STATUS_OK:
        t = zcanlib.ZCAN_GetValue(handle, "0/get_cn/1")
        print(c_char_p(t).value.decode("utf-8"))
    return


# 总线利用率上报线程
def read_bus_usage(device_handle, chn_index):
    while thread_flag:
        time.sleep(1)
        pBus = zcanlib.ZCAN_GetValue(device_handle, "0/get_bus_usage/1")
        if pBus == None:
            print("Get CH%d BusUsage failed!" % (chn_index))
            continue
        usage = cast(pBus, POINTER(BusUsage))
        new_usage = float(usage.contents.nBusUsage) / 100
        print(f"busload: {new_usage:.2f}")


if __name__ == "__main__":
    import argparse
    cli_parser = argparse.ArgumentParser(description="ZLG USBCANFD-200U 采集记录脚本")
    cli_parser.add_argument("--output", "-o", type=str, default=None, help="目标 CSV 输出文件完整路径")
    cli_args, _ = cli_parser.parse_known_args()

    print(">>> 正在加载 Zlgcan DLL 驱动依赖...", flush=True)
    # 在尝试实例化之前，优先检查 DLL 是否也能被找到，防止后续调用崩溃
    try:
        zcanlib = ZCAN()
        print(">>> Zlgcan DLL 驱动载入成功！", flush=True)
    except Exception as e:
        print(f"初始化 ZCAN 失败，可能是缺少核心 DLL 依赖，错误信息: {e}", flush=True)
        sys.exit(1)

    # [新增注释] 为了程序的健壮性，引入 try-finally 结构确保资源释放
    try:
        # 打开设备
        print(">>> 正在尝试打开 USBCANFD-200U 设备...", flush=True)
        print("[提示]: 如果设备被其他程序（如 ZCanPro 调试软件）占用，或硬件 USB 未正确插入，程序可能会在此处等待。", flush=True)
        handle = zcanlib.OpenDevice(ZCAN_USBCANFD_200U, 0, 0)
        if handle == INVALID_DEVICE_HANDLE:
            print("打开设备失败！请确认设备是否已被其他软件占用，或者插拔 USB 后重试。", flush=True)
            sys.exit(1)
        print(">>> 成功打开设备！设备句柄: %d." % handle, flush=True)

        # 获取设备信息
        can_number = Read_Device_Info(handle)

        # 设置自定义序列号
        Set_Device_Name(handle)

        # 启动通道
        print(">>> 正在初始化并启动各通道...", flush=True)
        chn_handles = []
        threads = []
        for i in range(can_number):
            chn_handle = USBCANFD_Start(zcanlib, handle, i)
            if chn_handle is None:
                print("启动通道%d失败！" % i, flush=True)
                sys.exit(1)
            chn_handles.append(chn_handle)  # 将通道句柄添加到列表中
            print("通道%d启动成功！通道句柄: %d." % (i, chn_handle), flush=True)

        # [新增改动] 在读取硬件数据前，先拉起底层的 CSV 异步消费者线程
        print(">>> 正在启动异步 CSV 数据记录线程...", flush=True)
        csv_thread = threading.Thread(target=csv_writer_thread, args=(cli_args.output,))
        csv_thread.start()

        # [新增改动] 如果开启了周期性终端汇总，拉起定时打印线程
        if DISPLAY_MODE == "interval":
            print(f">>> 正在启动终端实时数据显示线程 (显示周期: {DISPLAY_INTERVAL}s)...", flush=True)
            p_thread = threading.Thread(target=periodic_printer_thread, daemon=True)
            threads.append(p_thread)
            p_thread.start()

        if enable_merge_receive == 1:  # 若开启合并接收，所有通道都由一个接收线程处理
            print(">>> 正在启动合并接收数据线程...", flush=True)
            thread = threading.Thread(target=receive_thread, args=(handle, chn_handles[0]))  # 开启独立接收线程
            threads.append(thread)
            thread.start()
        else:  # 若没有开启合并接收，所有通道的数据需要各自开一个线程接收
            print(">>> 正在启动各通道数据接收线程...", flush=True)
            for i in range(len(chn_handles)):
                thread = threading.Thread(target=receive_thread, args=(handle, chn_handles[i]))  # 开启独立接收线程
                threads.append(thread)
                thread.start()

        if enable_bus_usage == 1:  # 开启总线利用率上报
            thread = threading.Thread(target=read_bus_usage, args=(handle, 0))  # 开启独立线程获取通道0的总线利用率
            threads.append(thread)
            thread.start()

        print("正在监控CAN总线数据并异步写入CSV... 按下回车键(Enter)结束监控并保存文件。", flush=True)
        # 回车退出，同时兼容管道 EOF 与 KeyboardInterrupt
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass

    except KeyboardInterrupt:
        print("\n检测到外部中断信号。", flush=True)

    finally:
        print("正在执行清理和关闭流程，正在将队列残余数据落盘...", flush=True)
        thread_flag = False

        # 关闭接收线程 (加入超时防止阻塞拖延退出)
        if 'threads' in locals():
            for t in threads:
                if t.is_alive():
                    t.join(timeout=0.5)

        # 等待 CSV 后台异步写入线程将队列残留数据全部处理完
        if 'csv_thread' in locals() and csv_thread.is_alive():
            csv_thread.join(timeout=3.0)

        # 关闭通道
        if 'chn_handles' in locals():
            for i in range(len(chn_handles)):
                ret = zcanlib.ResetCAN(chn_handles[i])
                if ret == 1:
                    print(f"关闭通道{i}成功")

        # 关闭设备
        if 'handle' in locals() and handle != INVALID_DEVICE_HANDLE:
            ret = zcanlib.CloseDevice(handle)
            if ret == 1:
                print("关闭设备成功")