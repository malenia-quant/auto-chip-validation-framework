# -*- coding: utf-8 -*-
"""
PyVISA 仪器自动化控制全景学习指南与语句速查手册
(CrashSensor Automated Chip Validation - PyVISA Instrumentation Cookbook)

本脚本汇总了 crash_sensor 项目中全部与硬件测试仪器通信的 PyVISA 与 SCPI 控制语句，
涵盖电源供应器、信号发生器、数字示波器、高精度万用表的完整指令集与底层解析逻辑。
专为自动化测试工程师、芯片验证工程师学习与快速查阅而设计。

包含仪器库：
1. Rigol DP2031 - 可编程高精度双通道线性直流电源 (DC Power Supply)
2. Rigol DG5072 - 双通道函数/任意波形发生器 (Function/Arbitrary Waveform Generator)
3. Siglent SDS5054X - 4通道500MHz高精度数字存储示波器 (Digital Storage Oscilloscope)
4. Keithley DMM6500 - 6位半高精度数字万用表 (Digital Multimeter)

Author: mozial
Language: Python 3.8+ / PyVISA 1.13+
"""

import sys
import os
import time
import math
import struct
from typing import Optional, Tuple, Dict, Any, List
import numpy as np

# 确保 Windows 终端控制台打印中文不出现乱码
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import pyvisa
except ImportError:
    pyvisa = None
    print("[WARN] 当前环境未安装 pyvisa，若需连接真实仪器请执行: pip install pyvisa")


# =============================================================================
# 第一部分：PyVISA 核心基础与资源管理 (Resource Manager & Connection)
# =============================================================================

class PyVisaFundamentals:
    """
    PyVISA 基础通信模型与资源管理器使用规范
    
    【核心概念】
    VISA (Virtual Instrument Software Architecture) 是测试测量领域的工业标准协议。
    PyVISA 是其 Python 封装，底层调用 NI-VISA、Keysight VISA 或开源 pyvisa-py 驱动。
    
    【常见 VISA 地址格式 (Resource String)】
    - USB 仪器:   "USB0::0x1AB1::0x0640::DG5T264700198::INSTR"
      语法: USB[board]::vendor ID::model code::serial number[::interface number]::INSTR
      - 0x1AB1: Rigol (普源精电) 厂商 ID
      - 0xF4EC: Siglent (鼎阳科技) 厂商 ID
      - 0x05E6: Keithley (吉时利) 厂商 ID
    - LAN/以太网: "TCPIP0::192.168.1.100::inst0::INSTR" (VXI-11 协议)
                  "TCPIP0::192.168.1.100::5025::SOCKET" (Raw Socket 端口协议)
    - 串口 (RS232): "ASRL1::INSTR" (COM1 端口)
    - GPIB 仪器:  "GPIB0::18::INSTR" (GPIB 控制卡总线地址 18)
    """

    @staticmethod
    def demonstrate_resource_management():
        """演示如何搜索、连接与安全关闭 VISA 资源"""
        if pyvisa is None:
            print("[INFO] 模拟模式: 跳过真实 VISA 资源初始化。")
            return

        # 1. 实例化资源管理器 (ResourceManager)
        # 默认自动寻找系统已安装的 VISA 运行时 (如 NI-VISA 或 Keysight VISA)
        rm = pyvisa.ResourceManager()

        # 如果在无 NI-VISA 的轻量 Linux/树莓派系统，可指定 pyvisa-py 纯 Python 后端:
        # rm = pyvisa.ResourceManager('@py')

        print(f"[VISA] 资源管理器后端: {rm}")

        # 2. 列出当前电脑所有识别到的物理总线设备
        # 返回类似 ('USB0::0x1AB1::...::INSTR', 'ASRL1::INSTR') 的元组
        available_resources = rm.list_resources()
        print(f"[VISA] 在线仪器列表 ({len(available_resources)} 台): {available_resources}")

        # 3. 打开特定仪器会话 (Open Session)
        test_addr = "USB0::0x1AB1::0x0640::DG5T264700198::INSTR"
        try:
            # open_resource 建立物理通信句柄
            inst = rm.open_resource(test_addr)

            # 4. 关键通信参数配置 (非常重要，影响通信稳定性)
            # timeout: 超时时间 (毫秒)，若仪器在指定时间内未返回数据则抛出 VisaIOError
            inst.timeout = 5000  # 5 秒超时

            # 终止符设置 (针对 SCPI 字符串通信)
            # 大多数现代仪器使用换行符 '\n' (0x0A) 作为写入与读取的结束符
            inst.read_termination = '\n'
            inst.write_termination = '\n'

            # 编码设置: 文本 SCPI 常用 'utf-8' 或 'ascii'；传输二进制波形必须用 'latin-1' 避免字节损坏
            inst.encoding = 'latin-1'

            # 缓存大小配置: 读取几兆字节的大波形时，调大 chunk_size 可显著降低传输延迟
            inst.chunk_size = 1024 * 1024  # 1MB 读写缓冲区

            # 5. IEEE 488.2 标准通用指令交互
            # *IDN? -> 查询仪器身份 (Manufacturer, Model, Serial Number, Firmware Version)
            # query() 等价于 write() 发送指令后立即执行 read() 阻塞等待返回
            idn_response = inst.query("*IDN?")
            print(f"[VISA] 仪器握手成功: {idn_response.strip()}")

            # *RST -> 恢复仪器出厂默认配置 (测试前置标准化)
            inst.write("*RST")

            # *CLS -> 清空所有状态寄存器与错误队列 (Error Queue)
            inst.write("*CLS")

            # *OPC? -> 操作完成查询 (Operation Complete)，用于硬件耗时动作同步阻塞
            # 硬件执行完前面的指令后才会返回 '1'，防止后序指令在机台未就绪时抢跑
            opc = inst.query("*OPC?")
            print(f"[VISA] 仪器就绪确认 (*OPC?): {opc.strip()}")

            # 6. 异常状态查询 (:SYST:ERR?)
            # SCPI 错误队列遵循 FIFO，返回: 0, "No error" 或 -113, "Undefined header"
            err = inst.query(":SYST:ERR?")
            print(f"[VISA] 错误队列检查: {err.strip()}")

            # 7. 安全关闭连接 (非常关键！严禁泄露 VISA 句柄，否则可能导致电脑 USB 栈锁死)
            inst.close()

        except pyvisa.VisaIOError as e:
            print(f"[WARN] 仪器通信异常 (通常因未插线或地址变动): {e}")
        finally:
            # 释放资源管理器本身
            rm.close()


# =============================================================================
# 第二部分：Rigol DP2031 可编程直流电源控制 (DC Power Supply)
# =============================================================================

class DP2031_PowerSupply_Cookbook:
    """
    Rigol DP2031 直流稳压电源常用 SCPI 控制语句汇总
    
    【设备典型应用】
    - 芯片慢速/快速上电启动特性验证 (Power-up Sequence / Slew Rate Ramp)
    - 芯片反复断电/快速下电循环应力测试 (Cyclical Power Cycle / Reboot Test)
    - 静态待机电流测量与功耗极限评估 (Static / Dynamic Quiescent Current)
    """

    def __init__(self, resource_name: str = "USB0::0x1AB1::0x0E11::DP2A000000001::INSTR"):
        self.resource_name = resource_name
        self.inst = None

    def connect_with_scan_fallback(self, rm: pyvisa.ResourceManager):
        """
        [实战经验] 仪器自动识别与候选列表扫描
        当仪器因插拔导致序列号变动时，通过遍历资源列表 + *IDN? 关键字自动找回
        """
        resources = rm.list_resources()
        # 筛选符合 Rigol 厂商 ID (0x1AB1) 或含 'DP' 字符的候选地址
        candidates = [r for r in resources if 'DP' in r or '0x1AB1' in r]
        
        for res in candidates:
            try:
                temp_inst = rm.open_resource(res)
                temp_inst.timeout = 2000
                idn = temp_inst.query("*IDN?").strip()
                if "DP" in idn or "DP2031" in idn:
                    self.inst = temp_inst
                    self.inst.timeout = 5000
                    print(f"[DP2031] 成功连接电源: {idn} ({res})")
                    return True
                temp_inst.close()
            except Exception:
                pass
        return False

    def execute_all_dp2031_commands(self):
        """汇总 DP2031 所有的 SCPI 指令用法"""
        if not self.inst:
            print("[INFO] 演示模式: 打印 DP2031 核心指令字典与语法说明。")
            self._print_instruction_guide()
            return

        inst = self.inst
        ch = 1

        # -------------------------------------------------------------
        # 1. 设定输出电压与电流限制 (APPLy 复合指令)
        # -------------------------------------------------------------
        # 语法: :APPLy CH<n>,<Voltage>,<Current>
        # 例如: 通道 1 设定为 5.000V，限流 0.500A (500mA)
        inst.write(f":APPL CH{ch},5.000,0.500")

        # -------------------------------------------------------------
        # 2. 分别独立设置电压与电流
        # -------------------------------------------------------------
        inst.write(f":SOUR{ch}:VOLT 3.300")      # 设定输出电压 3.3V
        inst.write(f":SOUR{ch}:CURR 0.100")      # 设定恒流限制 100mA

        # -------------------------------------------------------------
        # 3. 硬件过压保护 (OVP) 与过流保护 (OCP) 门限配置 (芯片级防烧保险)
        # -------------------------------------------------------------
        # 设定 OVP 保护阈值 (伏特)
        inst.write(f":OUTP:OVP:VAL CH{ch},6.500")
        # 使能 OVP 硬件保护
        inst.write(f":OUTP:OVP CH{ch},ON")

        # 设定 OCP 保护阈值 (安培)
        inst.write(f":OUTP:OCP:VAL CH{ch},0.200")
        # 使能 OCP 硬件保护
        inst.write(f":OUTP:OCP CH{ch},ON")

        # -------------------------------------------------------------
        # 4. 通道输出开/关控制 (Output ON/OFF)
        # -------------------------------------------------------------
        inst.write(f":OUTP CH{ch},ON")   # 打开通道输出
        time.sleep(0.5)
        inst.write(f":OUTP CH{ch},OFF")  # 关闭通道输出

        # -------------------------------------------------------------
        # 5. 真实输出状态与参数回读查询 (Query / Measurement)
        # -------------------------------------------------------------
        # 查询输出开关状态 (返回: ON / OFF 或 1 / 0)
        is_on = inst.query(f":OUTP? CH{ch}").strip()
        print(f"[DP2031] 通道 {ch} 状态: {is_on}")

        # 查询当前设定的目标电压/电流
        set_val = inst.query(f":APPL? CH{ch}").strip()
        print(f"[DP2031] 通道 {ch} 设定值: {set_val}")

        # 测量仪器端实时回读电压 (Actual Voltage Measured by ADC inside Power Supply)
        v_meas = float(inst.query(f":MEAS:VOLT? CH{ch}"))
        # 测量仪器端实时回读电流 (Actual Current Measured by ADC)
        i_meas = float(inst.query(f":MEAS:CURR? CH{ch}"))
        # 测量仪器端实时输出功率 (Actual Output Power in Watts)
        p_meas = float(inst.query(f":MEAS:POWE? CH{ch}"))
        print(f"[DP2031] 实时采集: 电压={v_meas:.4f}V, 电流={i_meas:.6f}A, 功率={p_meas:.4f}W")

    def _print_instruction_guide(self):
        """纯文本语法速查表"""
        syntax_table = [
            (":APPL CH1,5.0,0.2", "复合设置: 通道1电压5V，限流200mA"),
            (":APPL? CH1", "查询通道1设定的电压和电流"),
            (":SOUR1:VOLT 3.3", "单设电压: 通道1设定为3.3V"),
            (":SOUR1:CURR 0.1", "单设限流: 通道1设定为100mA"),
            (":OUTP:OVP:VAL CH1,6.0", "过压保护门限: 设置通道1 OVP=6.0V"),
            (":OUTP:OVP CH1,ON", "过压保护开关: 使能通道1 OVP"),
            (":OUTP:OCP:VAL CH1,0.5", "过流保护门限: 设置通道1 OCP=500mA"),
            (":OUTP:OCP CH1,ON", "过流保护开关: 使能通道1 OCP"),
            (":OUTP CH1,ON", "输出控制: 打开通道1供电"),
            (":OUTP CH1,OFF", "输出控制: 关闭通道1供电 (下电断电)"),
            (":OUTP? CH1", "查询输出状态: 返回 ON 或 OFF"),
            (":MEAS:VOLT? CH1", "硬件回读: 测量通道1当前输出的真实电压 (V)"),
            (":MEAS:CURR? CH1", "硬件回读: 测量通道1当前输出的真实电流 (A)"),
            (":MEAS:POWE? CH1", "硬件回读: 测量通道1当前输出的实时功率 (W)"),
        ]
        print("\n" + "=" * 75)
        print(" Rigol DP2031 直流电源核心 SCPI 指令速查表")
        print("=" * 75)
        for scpi, desc in syntax_table:
            print(f" {scpi:<26} | {desc}")
        print("=" * 75 + "\n")


# =============================================================================
# 第三部分：Rigol DG5072 函数与任意波形发生器控制 (Function/Arbitrary Generator)
# =============================================================================

class DG5072_Generator_Cookbook:
    """
    Rigol DG5072 双通道信号发生器核心 SCPI 控制语句汇总
    
    【设备典型应用】
    - PSI5 协议同步脉冲激励发生 (Sync Pulse Injection: Base 4.5V~11V, Pulse 3.5V~5.5V)
    - 亚微秒级瞬态掉电断电注入 (uCut Transient Drop: 1us~10000us, 0V~Vdd_Reset)
    - 芯片快慢速上电摆率测试 (Slew Rate Ramp: 1000V/s ~ 1000000V/s)
    - 16-bit 硬件采样点 RAM 热覆写 (DAC16 Binary Waveform Streaming)
    """

    def __init__(self, resource_name: str = "USB0::0x1AB1::0x0640::DG5T264700198::INSTR"):
        self.resource_name = resource_name
        self.inst = None

    def execute_all_dg5072_commands(self):
        """汇总 DG5072 所有的 SCPI 指令用法"""
        if not self.inst:
            print("[INFO] 演示模式: 打印 DG5072 核心指令字典与语法说明。")
            self._print_instruction_guide()
            return

        inst = self.inst
        ch = 1

        # -------------------------------------------------------------
        # 1. 输出阻抗匹配 (Output Load Impedance)
        # -------------------------------------------------------------
        # 极其重要！若接高阻负载 (如芯片引脚或示波器 1MΩ 输入)，必须设为 INF (高阻)。
        # 若误设为 50Ω，仪器内部计算的电压会直接减半，导致实际输出电压翻倍！
        inst.write(f":OUTP{ch}:LOAD INF")  # 设定为 High-Z (无限大阻抗)
        # inst.write(f":OUTP{ch}:LOAD 50") # 设定为标准 50Ω 射频匹配阻抗

        # -------------------------------------------------------------
        # 2. 基础波形类型选择 (Basic Waveform Functions)
        # -------------------------------------------------------------
        inst.write(f":SOUR{ch}:FUNC DC")    # 直流电平模式 (Constant DC Voltage)
        inst.write(f":SOUR{ch}:FUNC SIN")   # 正弦波
        inst.write(f":SOUR{ch}:FUNC SQU")   # 方波
        inst.write(f":SOUR{ch}:FUNC RAMP")  # 斜坡波 / 三角波
        inst.write(f":SOUR{ch}:FUNC PULS")  # 脉冲波 (支持独立控制边沿摆率)
        inst.write(f":SOUR{ch}:FUNC USER")  # 任意波模式 (Arbitrary Waveform)

        # -------------------------------------------------------------
        # 3. 脉冲参数精细配置 (Pulse Waveform & Slew Rate Tuning)
        # -------------------------------------------------------------
        inst.write(f":SOUR{ch}:FUNC PULS")
        
        # 方式 A: 通过高低电平直接设定 (High/Low Level)
        # 适用于汽车电子非对称电平标准 (例如底电平 1.34V，脉冲高电平 2.92V)
        # [防坑技巧] 连续交替写入 LOW/HIGH 两次，规避 SCPI 解析新值与旧值冲突的门限拒绝报错
        inst.write(f":SOUR{ch}:VOLT:LOW 1.34")
        inst.write(f":SOUR{ch}:VOLT:HIGH 2.92")
        inst.write(f":SOUR{ch}:VOLT:LOW 1.34")
        inst.write(f":SOUR{ch}:VOLT:HIGH 2.92")

        # 方式 B: 通过峰峰值 (Vpp) 与偏置电压 (Offset) 设定
        inst.write(f":SOUR{ch}:VOLT 1.58")       # 幅度 Vpp = High - Low = 1.58V
        inst.write(f":SOUR{ch}:VOLT:OFFS 2.13")  # 偏置 Offset = (High + Low) / 2 = 2.13V

        # 频率与周期
        inst.write(f":SOUR{ch}:PER 0.0005")      # 周期 = 500us (即频率 2kHz)
        # inst.write(f":SOUR{ch}:FREQ 2000.0")   # 等价于频率 2000Hz

        # 脉冲宽度 (Pulse Width in Seconds)
        inst.write(f":SOUR{ch}:PULS:WIDT 0.000030")  # 脉宽 30 微秒 (30us)

        # 边沿跃迁摆率控制 (Slew Rate: Transition Time in Seconds)
        # LEAP: 上升沿时间 (Leading Edge Time), TRA: 下降沿时间 (Trailing Edge Time)
        # DG5072 硬件物理极限上升时间约为 2.5ns
        inst.write(f":SOUR{ch}:PULS:TRAN:LEAD 2.354e-6")  # 上升时间 2.354 微秒
        inst.write(f":SOUR{ch}:PULS:TRAN:TRA 2.354e-6")   # 下降时间 2.354 微秒

        # -------------------------------------------------------------
        # 4. 斜坡波形与对称度配置 (Ramp Waveform for Power-Up Slope)
        # -------------------------------------------------------------
        inst.write(f":SOUR{ch}:FUNC RAMP")
        # 对称度 100%: 锯齿上升波 (100% 时间处于线性上升，0% 瞬间跌落)
        # 对称度 50%: 标准对称三角波
        inst.write(f":SOUR{ch}:FUNC:RAMP:SYMM 100")
        inst.write(f":SOUR{ch}:VOLT:LOW 0.0")
        inst.write(f":SOUR{ch}:VOLT:HIGH 5.0")
        inst.write(f":SOUR{ch}:FREQ 100.0")  # 10ms 周期内从 0V 升到 5V

        # -------------------------------------------------------------
        # 5. 任意波形 (ARB) 16位 DAC 二进制原始数据下载与热覆写
        # -------------------------------------------------------------
        # 构造归一化数据: 16384 个数据点 (范围 -1.0 到 +1.0)
        total_pts = 16384
        norm_wave = np.zeros(total_pts, dtype=np.float32)
        # 前半段为底电平，中间切入一段下冲掉电 (u-Cut)，后半段恢复
        norm_wave[:4000] = 0.5
        norm_wave[4000:4500] = -1.0  # 故障掉电时间槽
        norm_wave[4500:] = 0.5

        # 转换为 DG5072 硬件识别的 16位 无符号整型小端序 (<u2) 字节流
        # DAC 码值 0 对应 -Vamp/2, 16383 对应 +Vamp/2
        dac_bytes = np.round((norm_wave + 1.0) / 2.0 * 16383).astype('<u2').tobytes()

        # 构造 IEEE 488.2 二进制块协议头 (Definite Length Arbitrary Block)
        # 格式: #<位数><字节总长度><原始字节>
        len_str = str(len(dac_bytes))
        header = f"#{len(len_str)}{len_str}".encode('ascii')
        binary_block = header + dac_bytes

        # 写入易失性内存 (VOLATILE RAM)，并在结尾追加 END
        # write_raw 可以发送纯二进制 bytes，不会发生字符串转义损坏
        inst.write_raw(b":TRACe:DATA:DAC16 VOLATILE,END," + binary_block)
        inst.write(f":SOUR{ch}:FUNC USER")  # 强制应用刚刚下载的波形

        # -------------------------------------------------------------
        # 6. 单次突发 (Burst) 与软件触发
        # -------------------------------------------------------------
        inst.write(f":SOUR{ch}:BURS:STATE ON")  # 开启突发模式
        inst.write(f":SOUR{ch}:BURS:MODE TRIG")  # 触发模式 (非门控)
        inst.write(f":SOUR{ch}:BURS:NCYC 1")     # 每次触发发射 1 个周期的波形
        inst.write(f":SOUR{ch}:BURS:TRIG")      # 软件发送指令执行一次突发触发

        # -------------------------------------------------------------
        # 7. 通道物理输出开闭与状态查询
        # -------------------------------------------------------------
        inst.write(f":OUTP{ch} ON")   # 开启通道输出
        time.sleep(0.1)
        inst.write(f":OUTP{ch} OFF")  # 关闭通道输出

        # 查询通道是否开启 (返回 ON 或 OFF)
        out_state = inst.query(f":OUTP{ch}?").strip()
        print(f"[DG5072] 通道 {ch} 状态: {out_state}")

    def _print_instruction_guide(self):
        """纯文本语法速查表"""
        syntax_table = [
            (":OUTP1:LOAD INF", "输出阻抗: 设定通道1为高阻模式 (High-Z)"),
            (":SOUR1:FUNC PULS", "波形模式: 切换通道1为脉冲模式 (Pulse)"),
            (":SOUR1:FUNC USER", "波形模式: 切换通道1为用户任意波模式 (ARB)"),
            (":SOUR1:FUNC DC", "波形模式: 切换通道1为纯直流恒定电平模式"),
            (":SOUR1:VOLT:LOW 1.34", "电平设置: 设定脉冲低电平 (Base Level) 为1.34V"),
            (":SOUR1:VOLT:HIGH 2.92", "电平设置: 设定脉冲高电平 (Peak Level) 为2.92V"),
            (":SOUR1:PER 0.0005", "周期设置: 设定脉冲周期为 500us (2kHz)"),
            (":SOUR1:PULS:WIDT 30e-6", "脉宽设置: 设定脉冲持续宽度为 30us"),
            (":SOUR1:PULS:TRAN:LEAD 2e-6", "摆率设置: 设定上升沿过渡时间 (Rise Time) 2us"),
            (":SOUR1:PULS:TRAN:TRA 2e-6", "摆率设置: 设定下降沿过渡时间 (Fall Time) 2us"),
            (":SOUR1:FUNC:RAMP:SYMM 100", "斜坡对称度: 设定为100%单向线性上升锯齿波"),
            (":TRACe:DATA:DAC16 VOLATILE,...", "数据下载: 二进制流注入易失内存实现无继电器热覆写"),
            (":SOUR1:BURS:STATE ON", "突发模式: 开启通道1突发计数发射"),
            (":SOUR1:BURS:TRIG", "软件触发: 立即发射一次单周期激励脉冲"),
            (":OUTP1 ON / OFF", "输出开关: 开启或切断通道1射频前端输出"),
            (":SYST:ERR?", "错误查询: 读取仪器内部报警队列 (排除非法参数)"),
        ]
        print("\n" + "=" * 75)
        print(" Rigol DG5072 信号发生器核心 SCPI 指令速查表")
        print("=" * 75)
        for scpi, desc in syntax_table:
            print(f" {scpi:<26} | {desc}")
        print("=" * 75 + "\n")


# =============================================================================
# 第四部分：Siglent SDS5054X 高精度数字存储示波器 (Oscilloscope)
# =============================================================================

class SDS5054X_Oscilloscope_Cookbook:
    """
    Siglent SDS5054X 数字示波器核心 SCPI 指令与二进制波形解析算法
    
    【设备典型应用】
    - PSI5 曼彻斯特电流帧高速采集与硬件解码 (189kbps / 125kbps Manchester Decode)
    - 纳秒级上升/下降时间自动化测量 (Rise/Fall Edge Measurement)
    - 示波器底层触发等待防死锁机制 (Non-blocking Trigger Poll via INR?)
    - IEEE 488.2 二进制波形块读取与实际物理电压还原 (Raw Byte to Voltage Rebuilding)
    """

    def __init__(self, resource_name: str = "USB0::0xF4EC::0x1008::SDS5XC0X900138::INSTR"):
        self.resource_name = resource_name
        self.inst = None

    def execute_all_sds5054_commands(self):
        """汇总 SDS5054 所有的 SCPI 指令用法与波形读取流"""
        if not self.inst:
            print("[INFO] 演示模式: 打印 SDS5054 核心指令字典与语法说明。")
            self._print_instruction_guide()
            return

        inst = self.inst

        # -------------------------------------------------------------
        # 1. 通信协议全局优化 (Header Suppression & Encoding)
        # -------------------------------------------------------------
        # 必须关闭标头回传！例如查询 C1:VDIV? 时：
        # - CH:HEAD ON  -> 返回 "C1:VDIV 100E-3V" (带冗余头，解析繁琐)
        # - CH:HEAD OFF -> 返回 "100E-3" (纯浮点数字符串，极速高效)
        inst.write("CH:HEAD OFF")
        inst.encoding = "latin-1"  # 二进制波形防乱码

        # -------------------------------------------------------------
        # 2. 垂直通道物理参数配置 (Vertical Scale, Offset & Probe)
        # -------------------------------------------------------------
        ch = 1
        inst.write(f"CH{ch}:TRA ON")      # 打开通道轨迹 (Trace ON)
        inst.write(f"C{ch}:PROB 10")      # 设定探头衰减比为 10X (或 1X)
        inst.write(f"CH{ch}:COUP DC")     # 设定输入耦合方式: DC (直流) 或 AC (交流)
        inst.write(f"CH{ch}:BWL 20M")     # 开启 20MHz 硬件低通滤波 (滤除高频开关电源噪声)
        inst.write(f"CH{ch}:SCAL 0.100")   # 垂直分度灵敏度: 0.1V/div (即 100mV/格)
        inst.write(f"CH{ch}:OFFS 0.0")     # 垂直零点偏置电压: 0.0V

        # -------------------------------------------------------------
        # 3. 水平时基与存储深度配置 (Horizontal Timebase & Memory Depth)
        # -------------------------------------------------------------
        # TIM:SCAL: 水平时基 (秒/格)。示波器屏幕水平通常为 10 格 (Siglent 标准)
        # 例如: 500us/div 对应全屏 5ms 抓取窗口
        inst.write("TIM:SCAL 500e-6")
        
        # TIM:OFFS: 触发位置偏置 (秒)。0 代表触发点居中；负值将触发点左移，留出更多后置波形
        inst.write("TIM:OFFS -1.0e-3")

        # ACQ:MDEP: 存储深度 (Acquisition Memory Depth)。可选 "10K", "100K", "1M", "10M", "MAX"
        # [量产测试黄金法则] 产线 FT 自动化建议设为 "1M" (约 0.15 秒传完)；研发生理测试设为 "10M"
        inst.write("ACQ:MDEP 1M")

        # -------------------------------------------------------------
        # 4. 触发系统配置 (Trigger Engine Setup)
        # -------------------------------------------------------------
        inst.write("TRIG:MODE EDGE")         # 边沿触发模式 (Edge Trigger)
        inst.write(f"TRIG:EDGE:SOUR C{ch}")  # 触发源选择 Channel 1
        inst.write("TRIG:EDGE:LEV 0.300")    # 触发电平: 0.3V (300mV)
        inst.write("TRIG:EDGE:SLOP RISE")    # 触发斜率: 上升沿 (RISE) 或 下降沿 (FALL)
        inst.write("TRIG:SWE AUTO")          # 扫描模式: AUTO (自动), NORM (常规), SING (单次)

        # -------------------------------------------------------------
        # 5. 屏上自动化参数测量查询 (On-Screen Parameter Queries)
        # -------------------------------------------------------------
        # 极速测量芯片静态参数，无需下载整条波形即可获取数值
        inst.write(f"C{ch}:PAVA? MEAN")  # 查询平均值电压 (Mean Voltage)
        mean_val = inst.read().strip()

        inst.write(f"C{ch}:PAVA? PKPK")  # 查询峰峰值电压 (Peak-to-Peak)
        pkpk_val = inst.read().strip()

        inst.write(f"C{ch}:PAVA? FREQ")  # 查询信号频率 (Frequency)
        freq_val = inst.read().strip()

        print(f"[SDS5054] 屏上测量参数: Mean={mean_val}, PKPK={pkpk_val}, Freq={freq_val}")

        # -------------------------------------------------------------
        # 6. 单次触发抓取与状态防死锁轮询机制 (Single-Shot Acquisition)
        # -------------------------------------------------------------
        inst.write("TRIG:SWE SING")  # 设为单次抓取，示波器进入就绪等待 (ARMED)
        print("[SDS5054] 触发已就绪，正在等待波形到来...")

        # [防死锁核心技巧]
        # 绝对不能直接发送 WAV:DATA? 读取！若未触发，示波器不会回传任何字节，导致上位机 VISA 彻底卡死！
        # 正确做法：通过轮询内部状态寄存器 (INR?) 确认波形捕获完成
        triggered = False
        for _ in range(30):  # 最多轮询等待 3 秒
            state = inst.query("INR?").strip()
            if state != "0":  # 非 0 表示产生有效触发并已停止
                triggered = True
                break
            time.sleep(0.1)

        if not triggered:
            inst.write("STOP")  # 强制停止示波器，恢复正常总线状态
            print("[WARN] 触发超时，跳过本次波形拉取。")
            return

        # -------------------------------------------------------------
        # 7. 高速二进制波形块下载与解码 (Binary Waveform Acquisition)
        # -------------------------------------------------------------
        # 指定下载通道与格式
        inst.write(f"WAV:SOUR C{ch}")
        inst.write("WAV:DATA:FMT BYTE")   # 8-bit 单字节格式传输，传输速度最快
        inst.write("WAV:POIN:MODE MAX")   # 读取屏幕已采集的所有有效点

        # 查询波形缩放比例常数 (用于计算物理真实电压)
        vdiv = float(inst.query(f"C{ch}:VDIV?").replace("V", "").strip())
        voffset = float(inst.query(f"C{ch}:OFST?").replace("V", "").strip())
        sara = float(inst.query("SARA?").replace("Sa/s", "").strip())

        # 请求二进制波形数据
        inst.write("WAV:DATA?")
        raw_bytes = inst.read_raw()  # 读取未经字符串转换的原始字节流

        # 解析 IEEE 488.2 协议头: 例如 b'#9001000000...' (前2字节为 # 和 9，代表长度占9位)
        if raw_bytes[0:1] == b'#':
            len_of_len = int(chr(raw_bytes[1]))
            header_len = 2 + len_of_len
            waveform_payload = raw_bytes[header_len:-1]  # 剥离报头与尾部换行符
        else:
            waveform_payload = raw_bytes

        # 字节码转 int8 数组
        int8_data = np.frombuffer(waveform_payload, dtype=np.int8)

        # [物理电压计算核心公式]
        # Siglent 示波器在 8-bit 模式下一格垂直高度对应 25 个 ADC 码值
        # 真实电压 (V) = int8_code * (vdiv / 25.0) - voffset
        actual_voltages = int8_data * (vdiv / 25.0) - voffset

        # 依据采样率 (SARA) 还原绝对时间轴 (秒)
        total_time_span = len(actual_voltages) / sara
        time_axis = np.linspace(0, total_time_span, len(actual_voltages))

        print(f"[SDS5054] 成功获取波形: 点数={len(actual_voltages)}, 采样率={sara/1e6:.1f}MSa/s, 跨度={total_time_span*1e3:.2f}ms")

    def _print_instruction_guide(self):
        """纯文本语法速查表"""
        syntax_table = [
            ("CH:HEAD OFF", "报头屏蔽: 彻底关闭回传结果里的前缀标头，仅输出纯数值"),
            ("ASET", "自动设置: 触发示波器执行一键硬件 Auto Setup (约耗时 6~8 秒)"),
            ("CH1:TRA ON / OFF", "通道开关: 打开或关闭示波器通道 1 的屏幕显示与采集"),
            ("C1:PROB 10", "探头变比: 设定通道 1 衰减倍率为 10X (或 1X)"),
            ("CH1:BWL 20M", "带宽限制: 开启通道 1 的 20MHz 硬件低通滤波，过滤干扰"),
            ("CH1:COUP DC", "输入耦合: 设定通道 1 为直流耦合 (DC) 或交流耦合 (AC)"),
            ("CH1:SCAL 0.1", "垂直档位: 设定通道 1 灵敏度为 0.1V/格 (100mV/div)"),
            ("CH1:OFFS 0.0", "垂直偏置: 调整通道 1 屏幕中心偏置基准电平"),
            ("TIM:SCAL 500e-6", "水平时基: 设定每大格时间为 500us (全屏 5ms)"),
            ("TIM:OFFS -1e-3", "水平偏置: 移动水平触发点在全屏中的时间坐标"),
            ("ACQ:MDEP 1M", "存储深度: 设定采样内存深度为 1Mpts (点数越少传输越快)"),
            ("TRIG:MODE EDGE", "触发类型: 设定触发引擎为边沿触发模式 (Edge)"),
            ("TRIG:EDGE:SOUR C1", "触发源: 选择通道 1 作为同步触发源"),
            ("TRIG:EDGE:LEV 0.3", "触发电平: 设定触发门限电压为 300mV"),
            ("TRIG:EDGE:SLOP RISE", "触发极性: 设定为上升沿触发 (RISE) 或下降沿 (FALL)"),
            ("TRIG:SWE SING", "扫描模式: 单次捕获模式 (Single)，触发后自动冻结波形"),
            ("INR?", "状态轮询: 查询内部状态寄存器 (非零表示触发完成，杜绝死锁)"),
            ("WAV:SOUR C1", "数据源选通: 指定后续 WAV 系列指令操作通道 1"),
            ("WAV:DATA:FMT BYTE", "传输格式: 设定以 8-bit 单字节高速打包二进制传输"),
            ("WAV:POIN:MODE MAX", "点数模式: 设置读取当前最大存储点"),
            ("SARA?", "参数回读: 查询当前实时采样率 (Samples per Second)"),
            ("C1:VDIV? / OFST?", "参数回读: 读取通道 1 的垂直格度与零偏电压"),
            ("WAV:DATA?", "波形读取: 请求下载底层原始 IEEE 488.2 二进制波形数据块"),
            ("C1:PAVA? MEAN", "参数测量: 测量通道 1 屏幕波形的平均值电压"),
            ("C1:PAVA? PKPK", "参数测量: 测量通道 1 屏幕波形的峰峰值电压"),
        ]
        print("\n" + "=" * 75)
        print(" Siglent SDS5054X 数字示波器核心 SCPI 指令速查表")
        print("=" * 75)
        for scpi, desc in syntax_table:
            print(f" {scpi:<26} | {desc}")
        print("=" * 75 + "\n")


# =============================================================================
# 第五部分：Keithley DMM6500 6位半高精度数字万用表 (Digital Multimeter)
# =============================================================================

class DMM6500_Multimeter_Cookbook:
    """
    Keithley DMM6500 6位半高精度数字万用表核心 SCPI 控制语句汇总
    
    【设备典型应用】
    - 芯片微欧级/毫欧级接触电阻与桥路电阻测量 (4-Wire Sense Kelvin Resistance)
    - 静态精密泄漏电流微安/纳安级监测 (Low-noise uA DC Current Measure)
    - 消除工频 (50Hz) 市电噪声的高抗噪积分采样 (NPLC Integration Tuning)
    """

    def __init__(self, resource_name: str = "USB0::0x05E6::0x6500::04481234::INSTR"):
        self.resource_name = resource_name
        self.inst = None

    def execute_all_dmm6500_commands(self):
        """汇总 DMM6500 所有的 SCPI 指令用法"""
        if not self.inst:
            print("[INFO] 演示模式: 打印 DMM6500 核心指令字典与语法说明。")
            self._print_instruction_guide()
            return

        inst = self.inst

        # -------------------------------------------------------------
        # 1. 仪器复位与初态同步
        # -------------------------------------------------------------
        inst.write("*RST")
        inst.write("*CLS")

        # -------------------------------------------------------------
        # 2. 测量功能模式切换 (SENSe:FUNCtion)
        # -------------------------------------------------------------
        # 语法: SENS:FUNC "<功能字符串>"
        inst.write('SENS:FUNC "FRES"')     # 四线制电阻模式 (Four-wire RESistance，开尔文测试)
        # inst.write('SENS:FUNC "RES"')    # 二线制普通电阻模式 (Two-wire RESistance)
        # inst.write('SENS:FUNC "VOLT:DC"')# 直流电压模式 (DC Voltage)
        # inst.write('SENS:FUNC "CURR:DC"')# 直流电流模式 (DC Current)

        # -------------------------------------------------------------
        # 3. 量程配置 (Range Setup)
        # -------------------------------------------------------------
        # 开启自动量程 (Auto Range)，适合未知阻值范围扫描
        inst.write("SENS:FRES:RANG:AUTO ON")
        
        # 或手动固定量程以提升测试节拍速度 (减少量程切换继电器切换耗时)
        # inst.write("SENS:FRES:RANG 1000") # 固定在 1kΩ 量程

        # -------------------------------------------------------------
        # 4. 积分时间与工频滤波 (NPLC: Number of Power Line Cycles)
        # -------------------------------------------------------------
        # NPLC 决定测量 ADC 的积分时长，以 50Hz 工频为例，1 PLC = 20ms:
        # - NPLC = 10 (200ms): 超高精度、极低噪声模式，用于高精密研发标定
        # - NPLC = 1  (20ms):  标准工业推荐模式，完美消除 50Hz 工频交流电干扰
        # - NPLC = 0.1 (2ms):  高速生产线模式，测量速度最快
        inst.write("SENS:FRES:NPLC 10")

        # -------------------------------------------------------------
        # 5. 触发与测量读数获取 (Trigger & Fetch Measurement)
        # -------------------------------------------------------------
        # 方式 A: READ? 指令
        # 自动启动一次新的转换，等待完成后返回测量浮点值
        resistance_str = inst.query("READ?").strip()
        resistance_ohms = float(resistance_str)
        print(f"[DMM6500] 测得阻值: {resistance_ohms:.6f} Ω")

        # 方式 B: MEASure 单步快捷测量宏指令 (自动配置功能 + 量程 + 读数)
        # volt_str = inst.query("MEAS:VOLT:DC?").strip()
        # curr_str = inst.query("MEAS:CURR:DC?").strip()

    def _print_instruction_guide(self):
        """纯文本语法速查表"""
        syntax_table = [
            ('*RST / *CLS', "复位初始化: 恢复仪器至默认状态并清空错误队列"),
            ('SENS:FUNC "FRES"', "功能选择: 切换至四线制高精度开尔文电阻测量模式"),
            ('SENS:FUNC "RES"', "功能选择: 切换至二线制普通电阻测量模式"),
            ('SENS:FUNC "VOLT:DC"', "功能选择: 切换至直流电压测量模式"),
            ('SENS:FUNC "CURR:DC"', "功能选择: 切换至直流电流测量模式"),
            ('SENS:FRES:RANG:AUTO ON', "量程控制: 开启四线电阻自动换挡量程"),
            ('SENS:FRES:RANG 100', "量程控制: 手动锁定四线电阻量程为 100Ω (提升速度)"),
            ('SENS:FRES:NPLC 10', "工频积分: 设定 10 个工频周期 (200ms)，消灭市电纹波噪声"),
            ('SENS:FRES:NPLC 1', "工频积分: 设定 1 个工频周期 (20ms)，标准均衡模式"),
            ('READ?', "触发测量: 启动一次测量并阻塞回传实测数值 (浮点数字符串)"),
            ('MEAS:VOLT:DC?', "快捷测量: 一键配置并读取一次直流电压"),
            ('MEAS:CURR:DC?', "快捷测量: 一键配置并读取一次直流电流"),
        ]
        print("\n" + "=" * 75)
        print(" Keithley DMM6500 六位半万用表核心 SCPI 指令速查表")
        print("=" * 75)
        for scpi, desc in syntax_table:
            print(f" {scpi:<26} | {desc}")
        print("=" * 75 + "\n")


# =============================================================================
# 第六部分：工业级封装范式与上下文管理器 (Engineering Best Practices)
# =============================================================================

class VisaDeviceContextManager:
    """
    企业级上下文管理器范式 (Context Manager with Automatic Teardown)
    
    【核心价值】
    在实际自动化测试中，如果测试逻辑抛出异常（例如断言失败或 Ctrl+C 中断），
    原生代码极容易忘记关闭通道输出 (Output OFF)，导致芯片引脚一直通电短路烧毁！
    通过 Python 的 __enter__ 和 __exit__ 上下文管理器，无论程序以何种方式崩溃退出，
    均保证 100% 触发输出关闭并优雅注销 VISA 句柄。
    """

    def __init__(self, resource_name: str, timeout_ms: int = 5000):
        self.resource_name = resource_name
        self.timeout_ms = timeout_ms
        self.rm = None
        self.inst = None

    def __enter__(self):
        """进入 with 语句块时自动连接仪器并配置超时"""
        if pyvisa is None:
            return self
        try:
            self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(self.resource_name)
            self.inst.timeout = self.timeout_ms
            self.inst.read_termination = '\n'
            self.inst.write_termination = '\n'
            print(f"[SAFE-CONN] 成功接入设备: {self.resource_name}")
            return self
        except Exception as e:
            print(f"[SAFE-CONN] 连接失败: {e}")
            raise

    def write(self, command: str):
        """带错误包装的安全写入"""
        if self.inst:
            self.inst.write(command)

    def query(self, command: str) -> str:
        """带错误包装的安全查询"""
        if self.inst:
            return self.inst.query(command).strip()
        return ""

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出 with 语句块时强制执行安全下电并释放句柄"""
        if self.inst:
            try:
                # 针对电源或信号源的通用安全兜底: 关闭各通道输出
                print("[SAFE-CONN] 正在执行仪器安全注销与输出断电保护...")
                try:
                    self.inst.write(":OUTP CH1,OFF")
                    self.inst.write(":OUTP CH2,OFF")
                    self.inst.write(":OUTP1 OFF")
                    self.inst.write(":OUTP2 OFF")
                except Exception:
                    pass
                self.inst.close()
            except Exception as e:
                print(f"[SAFE-CONN] 关闭会话异常: {e}")
            finally:
                self.inst = None

        if self.rm:
            try:
                self.rm.close()
            except Exception:
                pass
            finally:
                self.rm = None
        print("[SAFE-CONN] 仪器会话已安全释放。")


# =============================================================================
# 第七部分：学习运行主入口与交互演示 (Interactive Demonstration)
# =============================================================================

def print_overall_architecture_summary():
    """打印仪器控制系统架构总结"""
    print("""
===============================================================================
       CrashSensor 自动化芯片测试框架 - PyVISA 设备通信架构总览
===============================================================================
[工位拓扑结构]
                 +-----------------------------+
                 |  上位机自动化软件 (Python)   |
                 +--------------+--------------+
                                | PyVISA (SCPI 命令集 / 驱动抽象层)
          +---------------------+---------------------+
          |                     |                     |
+---------+--------+  +---------+--------+  +---------+--------+
|  Rigol DP2031    |  |   Rigol DG5072   |  | Siglent SDS5054X |
|  直流线性稳压源  |  |  函数/任意波形源 |  | 500MHz 数字示波器|
| (上电/断电/过流) |  | (PSI5/uCut脉冲)  |  | (高速波形采集成像)|
+---------+--------+  +---------+--------+  +---------+--------+
          |                     |                     |
          +---------------------+---------------------+
                                |
                   +------------+------------+
                   |  被测芯片 (DUT / ASIC)   |
                   +-------------------------+

[学习要点备忘]
1. 任何 SCPI 指令在写入前，务必确认阻抗匹配 (:OUTP1:LOAD INF / 50)。
2. 示波器读取波形前，必须通过 INR? 轮询确认产生触发，严禁盲读导致总线锁死。
3. 二进制大块数据 (WAV:DATA?, :TRACe:DATA:DAC16) 传输必须采用 latin-1 编码。
4. 所有的测试流水线必须用 try...finally 或 Context Manager 保证 Output 彻底关断。
===============================================================================
""")


def main():
    """主执行函数：打印全套设备指令速查手册并执行语法自检"""
    print_overall_architecture_summary()

    # 1. 基础资源演示
    print("\n>>> [1/5] 正在展示 PyVISA 基础通信与资源探测...")
    PyVisaFundamentals.demonstrate_resource_management()

    # 2. DP2031 指令速查
    print("\n>>> [2/5] 正在展示 Rigol DP2031 直流电源控制指令集...")
    dp = DP2031_PowerSupply_Cookbook()
    dp.execute_all_dp2031_commands()

    # 3. DG5072 指令速查
    print("\n>>> [3/5] 正在展示 Rigol DG5072 信号发生器控制指令集...")
    dg = DG5072_Generator_Cookbook()
    dg.execute_all_dg5072_commands()

    # 4. SDS5054X 指令速查
    print("\n>>> [4/5] 正在展示 Siglent SDS5054X 数字示波器控制指令集...")
    sds = SDS5054X_Oscilloscope_Cookbook()
    sds.execute_all_sds5054_commands()

    # 5. DMM6500 指令速查
    print("\n>>> [5/5] 正在展示 Keithley DMM6500 六位半数字万用表指令集...")
    dmm = DMM6500_Multimeter_Cookbook()
    dmm.execute_all_dmm6500_commands()

    print("\n[OK] 全套 PyVISA 仪器控制语句与学习指南已就绪！")


if __name__ == "__main__":
    main()
