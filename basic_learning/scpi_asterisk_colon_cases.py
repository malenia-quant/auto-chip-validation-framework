# -*- coding: utf-8 -*-
"""
SCPI 仪器控制核心语法全案例实战库 (* 与 : 指令专题)
(CrashSensor Automated Chip Validation - SCPI Asterisk & Colon Practical Cases)

本文件系统性地归纳并实装了自动化芯片验证平台中涉及的全部 IEEE 488.2 (*) 与 SCPI (:) 指令。
涵盖 Rigol DP2031 (电源)、Rigol DG5072 (信号源)、Siglent SDS5054X (示波器) 和 Keithley DMM6500 (万用表)。
具备内置仿真模拟回显引擎 (Mock Instrument Engine)，在无真实硬件连接时也可直接执行并查看完整的指令交互全貌。

Author: mozial
Language: Python 3.8+ / PyVISA 1.13+
"""

import sys
import os
import time
import math
import struct
from typing import Optional, Tuple, Dict, Any, List, Union

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


# =============================================================================
# 0. 内置仿真仪器引擎 (Mock Device Engine) - 支持离线无实体设备学习执行
# =============================================================================

class MockInstrument:
    """
    仿真仪器交互代理类。
    当没有物理硬件在线时，拦截 query() 与 write()，模拟各仪器的标准响应。
    """
    def __init__(self, resource_name: str, device_type: str = "GENERIC"):
        self.resource_name = resource_name
        self.device_type = device_type.upper()
        self.registers = {
            "output_state": "OFF",
            "voltage_set": 3.3,
            "current_set": 0.1,
            "ovp_val": 6.5,
            "ocp_val": 0.2,
            "ovp_en": "ON",
            "ocp_en": "ON",
            "func": "PULS",
            "v_low": 1.34,
            "v_high": 2.92,
            "width": 30e-6,
            "trig_status": 1,
            "last_error": '0,"No error"'
        }
        self.write_log = []

    def write(self, command: str) -> None:
        cmd = command.strip()
        self.write_log.append(cmd)
        print(f"  [VISA-WRITE] -> {cmd}")

        # 内部仿真寄存器模拟更新
        if ":OUTP CH1,ON" in cmd or ":OUTP1 ON" in cmd:
            self.registers["output_state"] = "ON"
        elif ":OUTP CH1,OFF" in cmd or ":OUTP1 OFF" in cmd:
            self.registers["output_state"] = "OFF"
        elif ":SOUR1:VOLT" in cmd or ":SOUR:VOLT" in cmd:
            try:
                self.registers["voltage_set"] = float(cmd.split()[-1])
            except ValueError:
                pass

    def query(self, command: str) -> str:
        cmd = command.strip()
        print(f"  [VISA-QUERY] -> {cmd}")
        resp = ""

        # 1. 通用 * 指令响应
        if cmd == "*IDN?":
            if "DP2031" in self.device_type:
                resp = "RIGOL TECHNOLOGIES,DP2031,DP2C24010001,00.01.02"
            elif "DG5072" in self.device_type:
                resp = "Rigol Technologies,DG5072,DG5T264700198,00.01.12"
            elif "SDS5054" in self.device_type:
                resp = "Siglent Technologies,SDS5054X,SDS5XBA4150024,1.3.9R1"
            elif "DMM6500" in self.device_type:
                resp = "KEITHLEY INSTRUMENTS,MODEL DMM6500,04456789,1.7.12b"
            else:
                resp = "GENERIC_INSTRUMENT,MOCK,SN9999,V1.0"
        elif cmd == "*OPC?":
            resp = "1"
        elif cmd == ":SYST:ERR?":
            resp = self.registers["last_error"]

        # 2. DP2031 专用响应
        elif ":APPL? CH1" in cmd:
            resp = f"CH1:{self.registers['voltage_set']:.3f}V,{self.registers['current_set']:.3f}A"
        elif ":OUTP? CH1" in cmd or ":OUTP1?" in cmd:
            resp = self.registers["output_state"]
        elif ":MEAS:VOLT? CH1" in cmd:
            resp = f"{self.registers['voltage_set'] + 0.0012:.4f}"
        elif ":MEAS:CURR? CH1" in cmd:
            resp = "0.0354"
        elif ":MEAS:POWE? CH1" in cmd:
            resp = f"{(self.registers['voltage_set'] * 0.0354):.4f}"

        # 3. SDS5054 专用响应
        elif cmd == "INR?":
            resp = "1"  # 模拟已捕获触发完成
        elif "C1:PAVA? MEAN" in cmd:
            resp = "2.1325"
        elif "C1:PAVA? PKPK" in cmd:
            resp = "1.5840"
        elif "C1:PAVA? FREQ" in cmd:
            resp = "2000.00"
        elif cmd == "C1:VDIV?":
            resp = "100E-3"
        elif cmd == "C1:OFST?":
            resp = "0.0"
        elif cmd == "SARA?":
            resp = "2.000000e+09"

        # 4. DMM6500 专用响应
        elif cmd == "READ?":
            resp = "10.02456"
        elif "MEAS:VOLT:DC?" in cmd:
            resp = "3.30124"
        elif "MEAS:CURR:DC?" in cmd:
            resp = "0.03215"
        else:
            resp = "OK"

        print(f"  [VISA-RECV]  <- {resp}")
        return resp

    def write_raw(self, data: bytes) -> None:
        self.write_log.append(f"RAW_BYTES_{len(data)}_LEN")
        print(f"  [VISA-WRITE-RAW] -> {len(data)} 字节二进制流")

    def read_raw(self) -> bytes:
        # 模拟返回一个简化的 IEEE 488.2 二进制波形块: #9000000020 + 20字节 int8 数据 + \n
        header = b"#9000000020"
        payload = bytes([128 + int(50 * math.sin(i * 0.3)) for i in range(20)])
        resp = header + payload + b"\n"
        print(f"  [VISA-READ-RAW]  <- {len(resp)} 字节二进制波形块")
        return resp

    def close(self) -> None:
        pass


# =============================================================================
# 一、 * 开头：IEEE 488.2 全局通用控制实战案例
# =============================================================================

class IEEE488AsteriskCases:
    """
    IEEE 488.2 标准星号 (*) 指令集实战案例
    
    【核心法则】
    * 开头的指令是测试测量领域的“世界语”，不属于任何具体的物理通道或子系统。
    无论连接的是电源、示波器、信号源还是万用表，语法结构与功能完全统一。
    """

    @staticmethod
    def case_idn_identification(inst: Union[Any, MockInstrument]) -> Dict[str, str]:
        """
        [案例 1] *IDN? - 查询设备身份标识 (Identity Query)
        应用场景：仪器自动识别、握手测试、在多个 COM 口或 USB 端口中按型号模糊匹配。
        """
        print("\n--- [案例 1] *IDN? 查询设备身份标识 ---")
        idn_raw = inst.query("*IDN?").strip()
        parts = idn_raw.split(',')
        vendor = parts[0] if len(parts) > 0 else "UNKNOWN"
        model = parts[1] if len(parts) > 1 else "UNKNOWN"
        serial = parts[2] if len(parts) > 2 else "UNKNOWN"
        firmware = parts[3] if len(parts) > 3 else "UNKNOWN"

        print(f"  [解析结果] 厂商: {vendor} | 型号: {model} | 序列号: {serial} | 固件: {firmware}")
        return {"vendor": vendor, "model": model, "serial": serial, "firmware": firmware}

    @staticmethod
    def case_rst_reset(inst: Union[Any, MockInstrument]) -> None:
        """
        [案例 2] *RST - 出厂初始化复位 (Reset)
        应用场景：在每个自动化测试轮次 (Test Suite) 开始前执行，清除前一个测试用例残留的异常状态与通道设置。
        """
        print("\n--- [案例 2] *RST 仪器出厂初始化复位 ---")
        print("  [工程说明] 清空仪器所有寄存器与通道旋钮至出厂默认值，确保后续测试起点纯净。")
        inst.write("*RST")
        time.sleep(0.5)

    @staticmethod
    def case_cls_clear_status(inst: Union[Any, MockInstrument]) -> None:
        """
        [案例 3] *CLS - 清除状态寄存器与错误队列 (Clear Status)
        应用场景：当仪器发生过压 (OVP)、过流 (OCP) 自锁报警，或指令参数越界后，清除警报标志。
        """
        print("\n--- [案例 3] *CLS 清除状态寄存器与错误标志 ---")
        print("  [工程说明] 重置所有事件状态寄存器 (ESR) 与标准状态字节 (STB)，消除历史报警。")
        inst.write("*CLS")

    @staticmethod
    def case_opc_operation_complete(inst: Union[Any, MockInstrument], timeout_sec: float = 5.0) -> bool:
        """
        [案例 4] *OPC? - 硬件操作同步阻塞栅栏 (Operation Complete)
        应用场景：下发高耗时硬件动作 (如示波器 Auto Setup、大容量波形载入、继电器切换) 后，
                  让 Python 阻塞等待直到仪器硬件彻底准备就绪，杜绝时序竞态 (Race Condition)。
        """
        print("\n--- [案例 4] *OPC? 硬件操作同步阻塞栅栏 ---")
        print("  [工程说明] 下发耗时硬件操作后，通过 *OPC? 询问仪器内部硬件管线是否空闲。")
        resp = inst.query("*OPC?").strip()
        is_ready = (resp == "1")
        print(f"  [同步状态] 硬件是否已彻底生效: {is_ready}")
        return is_ready


# =============================================================================
# 二、 : 开头：Rigol DP2031 直流稳压电源实战案例
# =============================================================================

class RigolDP2031ColonCases:
    """
    Rigol DP2031 直流稳压电源 SCPI (:) 业务指令集
    核心功能：供电通道配置、快慢上下电、硬件保险保护、功耗采样回读。
    """

    @staticmethod
    def case_apply_composite(inst: Union[Any, MockInstrument], ch: int = 1, volt: float = 5.0, curr: float = 0.5) -> None:
        """
        [案例 1] :APPL - 通道快捷复合设定
        语法: :APPL CH<n>,<Voltage>,<Current>
        优势: 单条原子指令同时设置电压和限流，避免分开写两次指令引发的中间态冲击。
        """
        print(f"\n--- [DP2031 案例 1] :APPL 通道复合设定 ---")
        cmd = f":APPL CH{ch},{volt:.3f},{curr:.3f}"
        inst.write(cmd)
        resp = inst.query(f":APPL? CH{ch}").strip()
        print(f"  [验证设置] 通道 {ch} 目标输出状态: {resp}")

    @staticmethod
    def case_independent_volt_curr(inst: Union[Any, MockInstrument], ch: int = 1, volt: float = 3.3, curr: float = 0.1) -> None:
        """
        [案例 2] :SOUR<n>:VOLT 与 :SOUR<n>:CURR - 独立单项精准调节
        应用场景：电压步进扫描测试 (Voltage Ramp/Margin Test) 或动态动态调整恒流保护阈值。
        """
        print(f"\n--- [DP2031 案例 2] :SOUR:VOLT / :SOUR:CURR 独立设置 ---")
        inst.write(f":SOUR{ch}:VOLT {volt:.3f}")
        inst.write(f":SOUR{ch}:CURR {curr:.3f}")
        print(f"  [设定完成] 通道 {ch} 调节为 {volt}V, 限流 {curr}A")

    @staticmethod
    def case_hardware_protection(inst: Union[Any, MockInstrument], ch: int = 1, ovp_v: float = 6.5, ocp_a: float = 0.2) -> None:
        """
        [案例 3] :OUTP:OVP 与 :OUTP:OCP - 硬件防烧切断保险门限
        应用场景：保护单颗价值昂贵的工程工程样片 (ASIC)，一旦外部短路或发生自激振荡，微秒级切断。
        """
        print(f"\n--- [DP2031 案例 3] :OUTP:OVP / :OUTP:OCP 硬件自锁保护 ---")
        # 过压保护门限与使能
        inst.write(f":OUTP:OVP:VAL CH{ch},{ovp_v:.3f}")
        inst.write(f":OUTP:OVP CH{ch},ON")
        # 过流保护门限与使能
        inst.write(f":OUTP:OCP:VAL CH{ch},{ocp_a:.3f}")
        inst.write(f":OUTP:OCP CH{ch},ON")
        print(f"  [安全就绪] 通道 {ch} 已设防: OVP={ovp_v}V, OCP={ocp_a}A")

    @staticmethod
    def case_power_switch(inst: Union[Any, MockInstrument], ch: int = 1, enable: bool = True) -> str:
        """
        [案例 4] :OUTP - 通道物理加电与切断控制
        应用场景：芯片上下电复位 (Power-Cycle Reset) 或测试完毕后的安全下电断开。
        """
        state_str = "ON" if enable else "OFF"
        print(f"\n--- [DP2031 案例 4] :OUTP 供电开关 ({state_str}) ---")
        inst.write(f":OUTP CH{ch},{state_str}")
        actual_state = inst.query(f":OUTP? CH{ch}").strip()
        print(f"  [状态确认] 通道 {ch} 当前输出开关: {actual_state}")
        return actual_state

    @staticmethod
    def case_hardware_measurements(inst: Union[Any, MockInstrument], ch: int = 1) -> Dict[str, float]:
        """
        [案例 5] :MEAS:VOLT? / :MEAS:CURR? / :MEAS:POWE? - 硬件 ADC 真实采样回读
        应用场景：芯片静态静态功耗测量、漏电流筛查与电源轨内阻压降监测。
        """
        print(f"\n--- [DP2031 案例 5] :MEAS 硬件实时物理量回读 ---")
        v = float(inst.query(f":MEAS:VOLT? CH{ch}").strip())
        i = float(inst.query(f":MEAS:CURR? CH{ch}").strip())
        p = float(inst.query(f":MEAS:POWE? CH{ch}").strip())
        print(f"  [实测数据] 电压: {v:.4f}V | 电流: {i*1000:.2f}mA | 功率: {p*1000:.2f}mW")
        return {"voltage": v, "current": i, "power": p}


# =============================================================================
# 三、 : 开头：Rigol DG5072 任意波形信号发生器实战案例
# =============================================================================

class RigolDG5072ColonCases:
    """
    Rigol DG5072 信号发生器 SCPI (:) 业务指令集
    核心功能：输出高阻匹配、函数波形切换、微跌落 (uCut) 脉冲配置、二进制内存波形注入。
    """

    @staticmethod
    def case_impedance_matching(inst: Union[Any, MockInstrument], ch: int = 1) -> None:
        """
        [案例 1] :OUTP<n>:LOAD INF - 端口阻抗匹配 (高阻模式)
        【极重要避坑】: 信号源默认 50 欧姆输出阻抗。如果驱动芯片的 CMOS/TTL 高阻引脚，
        未设置 LOAD INF 会导致信号源计算的分压减半，实际输出幅度翻倍，可能击穿芯片！
        """
        print("\n--- [DG5072 案例 1] :OUTP:LOAD INF 端口阻抗匹配 ---")
        inst.write(f":OUTP{ch}:LOAD INF")
        print(f"  [阻抗设定] 通道 {ch} 设定为 High-Z (高阻)，确保设定电压等于芯片引脚实际承受电压。")

    @staticmethod
    def case_function_modes(inst: Union[Any, MockInstrument], ch: int = 1, mode: str = "PULS") -> None:
        """
        [案例 2] :SOUR<n>:FUNC - 波形发生器工作模式切换
        支持: DC (纯电平), PULS (脉冲), RAMP (斜坡/三角波), USER (自定义任意波)
        """
        print(f"\n--- [DG5072 案例 2] :SOUR:FUNC 波形模式切换 ({mode}) ---")
        valid_modes = ["DC", "PULS", "RAMP", "USER", "SIN"]
        target = mode.upper() if mode.upper() in valid_modes else "PULS"
        inst.write(f":SOUR{ch}:FUNC {target}")
        print(f"  [工作模式] 通道 {ch} 切换为: {target}")

    @staticmethod
    def case_pulse_parameters(inst: Union[Any, MockInstrument], ch: int = 1,
                              v_low: float = 1.34, v_high: float = 2.92,
                              period: float = 0.0005, width: float = 30e-6,
                              rise_time: float = 2.354e-6, fall_time: float = 2.354e-6) -> None:
        """
        [案例 3] :SOUR<n>:VOLT / :PULS - 脉冲波高低电平、周期与摆率精准配置
        应用场景：针对汽车碰撞传感器 (Crash Sensor) 的微秒级断电 (uCut) 复位极限测试。
        """
        print("\n--- [DG5072 案例 3] :SOUR:PULS 脉冲波电气参数配置 ---")
        inst.write(f":SOUR{ch}:FUNC PULS")
        inst.write(f":SOUR{ch}:PER {period:.6f}")
        inst.write(f":SOUR{ch}:VOLT:LOW {v_low:.3f}")
        inst.write(f":SOUR{ch}:VOLT:HIGH {v_high:.3f}")
        inst.write(f":SOUR{ch}:PULS:WIDT {width:.8f}")
        inst.write(f":SOUR{ch}:PULS:TRAN:LEAD {rise_time:.8f}")
        inst.write(f":SOUR{ch}:PULS:TRAN:TRA {fall_time:.8f}")
        print(f"  [脉冲参数] 基底: {v_low}V | 峰值: {v_high}V | 脉宽: {width*1e6:.1f}us | 边沿: {rise_time*1e6:.2f}us")

    @staticmethod
    def case_ramp_symmetry(inst: Union[Any, MockInstrument], ch: int = 1, symm: int = 100) -> None:
        """
        [案例 4] :SOUR<n>:FUNC:RAMP:SYMM - 锯齿波斜坡对称度
        对称度 100%: 线性上升单向锯齿波 (用于测试芯片上电 Ramp-up 启动斜率阈值)。
        对称度 50%: 标准对称三角波。
        """
        print(f"\n--- [DG5072 案例 4] :SOUR:FUNC:RAMP:SYMM 锯齿波对称度 ---")
        inst.write(f":SOUR{ch}:FUNC RAMP")
        inst.write(f":SOUR{ch}:FUNC:RAMP:SYMM {symm}")
        print(f"  [波形配置] 通道 {ch} 斜坡对称度设为 {symm}% (单向正斜率锯齿波)")

    @staticmethod
    def case_burst_trigger(inst: Union[Any, MockInstrument], ch: int = 1, n_cycles: int = 1) -> None:
        """
        [案例 5] :SOUR<n>:BURS - 突发模式与上位机单脉冲触发
        应用场景：不是让波形一直无休止发射，而是上位机准备好示波器后，手动激发单次故障脉冲注入。
        """
        print("\n--- [DG5072 案例 5] :SOUR:BURS 软件触发单脉冲突发 ---")
        inst.write(f":SOUR{ch}:BURS:STATE ON")
        inst.write(f":SOUR{ch}:BURS:MODE TRIG")
        inst.write(f":SOUR{ch}:BURS:NCYC {n_cycles}")
        # 立即发射单次触发
        inst.write(f":SOUR{ch}:BURS:TRIG")
        print(f"  [突发激发] 通道 {ch} 已执行单次软件触发脉冲发射 (Cycles={n_cycles})")

    @staticmethod
    def case_dac16_raw_injection(inst: Union[Any, MockInstrument], ch: int = 1) -> None:
        """
        [案例 6] :TRACe:DATA:DAC16 - 16-Bit 二进制点阵无继电器热重载
        应用场景：在不触发物理继电器跳动的前提下，直接向高速易失性 RAM (VOLATILE) 灌注任意波点阵。
        """
        print("\n--- [DG5072 案例 6] :TRACe:DATA:DAC16 二进制波形流高速灌装 ---")
        # 构造 16 个点的归一化 16 位整型 DAC 数据
        points = [int(16383 * (1 + math.sin(2 * math.pi * i / 16)) / 2) for i in range(16)]
        raw_dac_bytes = struct.pack(f"<{len(points)}H", *points)
        cmd_prefix = b":TRACe:DATA:DAC16 VOLATILE,END,"
        inst.write_raw(cmd_prefix + raw_dac_bytes)
        print(f"  [RAM直写] 成功向易失性内存高速灌入 {len(points)} 个 16-bit DAC 采样点")

    @staticmethod
    def case_output_control(inst: Union[Any, MockInstrument], ch: int = 1, enable: bool = True) -> str:
        """
        [案例 7] :OUTP<n> - 射频前端物理输出开关与系统错误查询
        """
        state = "ON" if enable else "OFF"
        print(f"\n--- [DG5072 案例 7] :OUTP 射频输出开关与错误队列排查 ---")
        inst.write(f":OUTP{ch} {state}")
        actual = inst.query(f":OUTP{ch}?").strip()
        err = inst.query(":SYST:ERR?").strip()
        print(f"  [通道状态] 通道 {ch} 输出: {actual} | 系统错误码: {err}")
        return actual


# =============================================================================
# 四、 : 开头：Siglent SDS5054X 高精度数字示波器实战案例
# =============================================================================

class SiglentSDS5054ColonCases:
    """
    Siglent SDS5054X 数字存储示波器业务指令集 (鼎阳体系语法)
    核心功能：报头抑制、通道与时基档位、触发配置、INR?防死锁轮询、原始波形提取。
    """

    @staticmethod
    def case_header_suppression(inst: Union[Any, MockInstrument]) -> None:
        """
        [案例 1] CH:HEAD OFF - 报头回显抑制 (极其关键)
        【为什么一定要关？】
        开启报头时，query('C1:PAVA? MEAN') 返回 'C1:PAVA MEAN,3.30V'。
        关闭报头后，query('C1:PAVA? MEAN') 返回 '3.30'，直接 float() 转成数字！
        """
        print("\n--- [SDS5054 案例 1] CH:HEAD OFF 彻底关闭回传报头 ---")
        inst.write("CH:HEAD OFF")
        print("  [报头优化] 已关闭前缀报头，后续所有查询指令将仅返回干净纯粹的数值字符串。")

    @staticmethod
    def case_channel_conditioning(inst: Union[Any, MockInstrument], ch: int = 1) -> None:
        """
        [案例 2] 通道显示、探头衰减比、耦合模式与 20MHz 硬件带宽限制
        """
        print(f"\n--- [SDS5054 案例 2] 通道信号调理 (CH{ch}) ---")
        inst.write(f"CH{ch}:TRA ON")       # 打开通道轨迹
        inst.write(f"C{ch}:PROB 10")       # 设定探头为 10X 衰减比
        inst.write(f"CH{ch}:COUP DC")      # 直流耦合
        inst.write(f"CH{ch}:BWL 20M")      # 开启 20MHz 硬件低通滤波器，过滤外部射频噪声
        print(f"  [调理配置] 通道 {ch} 已设为 10X 衰减、DC 耦合、20MHz 硬件抗干扰低通。")

    @staticmethod
    def case_vertical_and_horizontal(inst: Union[Any, MockInstrument], ch: int = 1,
                                     v_scale: float = 0.100, v_offset: float = 0.0,
                                     t_scale: float = 500e-6, t_offset: float = -1.0e-3) -> None:
        """
        [案例 3] :SCAL / :OFFS / TIM:SCAL - 垂直灵敏度与水平时基窗口
        """
        print("\n--- [SDS5054 案例 3] 垂直格度与水平时基窗口调节 ---")
        inst.write(f"CH{ch}:SCAL {v_scale:.3f}")
        inst.write(f"CH{ch}:OFFS {v_offset:.3f}")
        inst.write(f"TIM:SCAL {t_scale:.6f}")
        inst.write(f"TIM:OFFS {t_offset:.6f}")
        print(f"  [窗口设置] CH{ch} 垂直灵敏度: {v_scale*1000:.0f}mV/div | 水平时基: {t_scale*1e6:.0f}us/div")

    @staticmethod
    def case_edge_trigger_single(inst: Union[Any, MockInstrument], ch: int = 1, level: float = 0.3) -> None:
        """
        [案例 4] TRIG:MODE / TRIG:EDGE / TRIG:SWE SING - 单次边沿硬件触发锁定
        应用场景：捕获一次性突发的掉电脉冲或总线报文帧，触发后示波器立即单次冻结。
        """
        print("\n--- [SDS5054 案例 4] 单次边沿硬件触发系统配置 ---")
        inst.write("TRIG:MODE EDGE")
        inst.write(f"TRIG:EDGE:SOUR C{ch}")
        inst.write(f"TRIG:EDGE:LEV {level:.3f}")
        inst.write("TRIG:EDGE:SLOP RISE")
        inst.write("TRIG:SWE SING")        # 进入 Single 扫描等待
        print(f"  [触发引擎] 锁定 CH{ch} 上升沿触发，门限电平 {level*1000:.0f}mV，工作模式为 Single。")

    @staticmethod
    def case_inr_trigger_polling(inst: Union[Any, MockInstrument], timeout_sec: float = 3.0) -> bool:
        """
        [案例 5] INR? - 内部状态寄存器非阻塞轮询 (防 VISA 总线死锁核心机制)
        【极重要避坑】:
        如果示波器尚未捕获到信号 (未触发)，直接下发 WAV:DATA? 会导致 VISA 总线永久阻塞，
        最终引发 VI_ERROR_TMO 超时崩溃。使用 INR? 轮询可以在触发完毕前不打扰总线。
        """
        print("\n--- [SDS5054 案例 5] INR? 内部状态寄存器非阻塞轮询 ---")
        start = time.time()
        triggered = False
        while (time.time() - start) < timeout_sec:
            inr = int(inst.query("INR?").strip())
            # 当内部状态寄存器非零，表示捕获已停止且波形已存入采样内存
            if inr != 0:
                triggered = True
                print(f"  [状态同步] 示波器已成功捕获触发！(INR 返回值={inr})")
                break
            time.sleep(0.05)

        if not triggered:
            print("  [状态同步] 等待触发超时，当前未检测到有效波形。")
        return triggered

    @staticmethod
    def case_screen_parameter_measure(inst: Union[Any, MockInstrument], ch: int = 1) -> Dict[str, float]:
        """
        [案例 6] C<n>:PAVA? - 硬件专用测量加速器 (平均值 / 峰峰值 / 频率)
        优势：利用示波器内部 DSP 芯片直接硬件计算，几毫秒内返回精确统计值。
        """
        print(f"\n--- [SDS5054 案例 6] C{ch}:PAVA? 示波器硬件内建参数测量 ---")
        v_mean = float(inst.query(f"C{ch}:PAVA? MEAN").strip())
        v_pkpk = float(inst.query(f"C{ch}:PAVA? PKPK").strip())
        freq = float(inst.query(f"C{ch}:PAVA? FREQ").strip())
        print(f"  [硬件测量结果] 均值: {v_mean:.4f}V | 峰峰值: {v_pkpk:.4f}V | 频率: {freq:.2f}Hz")
        return {"mean": v_mean, "pkpk": v_pkpk, "freq": freq}

    @staticmethod
    def case_waveform_binary_download(inst: Union[Any, MockInstrument], ch: int = 1) -> Tuple[List[float], float]:
        """
        [案例 7] WAV:DATA? - IEEE 488.2 二进制波形块读取与浮点真实电压转换
        还原算式: 实际物理电压 = (int8_code - 128) * (vdiv / 25.0) - voffset
        """
        print(f"\n--- [SDS5054 案例 7] WAV:DATA? 底层原始 IEEE 488.2 点阵数据流解析 ---")
        inst.write(f"WAV:SOUR C{ch}")
        inst.write("WAV:DATA:FMT BYTE")
        inst.write("WAV:POIN:MODE MAX")

        # 读取转换常数
        vdiv = float(inst.query(f"C{ch}:VDIV?").strip())
        voffset = float(inst.query(f"C{ch}:OFST?").strip())
        sample_rate = float(inst.query("SARA?").strip())

        # 获取原始二进制块
        inst.write("WAV:DATA?")
        raw_bytes = inst.read_raw()

        # 解析 IEEE 488.2 二进制块头 (#9000000020...)
        header_len_digits = int(chr(raw_bytes[1]))
        data_len = int(raw_bytes[2: 2 + header_len_digits])
        payload = raw_bytes[2 + header_len_digits: 2 + header_len_digits + data_len]

        # 转换为真实伏特电压
        voltages = [(b - 128) * (vdiv / 25.0) - voffset for b in payload]
        print(f"  [点阵解析] 采样率: {sample_rate/1e6:.1f}MSa/s | 成功解析 {len(voltages)} 个点 | 首点电压: {voltages[0]:.4f}V")
        return voltages, sample_rate


# =============================================================================
# 五、 : 开头：Keithley DMM6500 六位半高精度数字万用表实战案例
# =============================================================================

class KeithleyDMM6500ColonCases:
    """
    Keithley DMM6500 六位半万用表业务指令集 (SENS 与 MEAS 子系统)
    核心功能：高精度四线开尔文测阻、直流微电流测量、工频周期 (NPLC) 抗干扰滤波。
    """

    @staticmethod
    def case_function_selection(inst: Union[Any, MockInstrument], func: str = "FRES") -> None:
        """
        [案例 1] SENS:FUNC - 切换核心测量物理量
        "FRES": 四线制开尔文电阻测量 (Four-Wire Resistance, 精度极高, 消除表笔阻抗)
        "RES": 普通两线制电阻测量
        "VOLT:DC": 直流电压表
        "CURR:DC": 直流电流表
        """
        print(f"\n--- [DMM6500 案例 1] SENS:FUNC 测量功能模式切换 ({func}) ---")
        inst.write(f'SENS:FUNC "{func}"')
        print(f"  [功能就绪] 万用表已切换至: {func}")

    @staticmethod
    def case_range_control(inst: Union[Any, MockInstrument], auto: bool = False, fixed_range: float = 100.0) -> None:
        """
        [案例 2] SENS:FRES:RANG - 自动与固定量程控制
        【工程提速技巧】: 在自动化批量测试时，固定量程可以省去继电器反复跳挡的 300ms 震颤时间。
        """
        print("\n--- [DMM6500 案例 2] SENS:FRES:RANG 灵敏度量程控制 ---")
        if auto:
            inst.write("SENS:FRES:RANG:AUTO ON")
            print("  [量程状态] 已使能电阻全量程自动换挡。")
        else:
            inst.write(f"SENS:FRES:RANG {fixed_range}")
            print(f"  [量程状态] 已手动锁死在 {fixed_range} 欧姆量程，极大提速批量测量。")

    @staticmethod
    def case_nplc_filtering(inst: Union[Any, MockInstrument], nplc: float = 10.0) -> None:
        """
        [案例 3] SENS:FRES:NPLC - 工频积分周期调节 (消灭 50Hz 市电工频干扰)
        原理: 1 NPLC (Number of Power Line Cycles) 在中国 50Hz 电网中对应 20ms。
        设置 NPLC=10 表示积分 200ms，在整周期内交流工频正负完全抵消，得到纯净直流读数！
        """
        print(f"\n--- [DMM6500 案例 3] SENS:FRES:NPLC 工频滤波积分周期调节 ---")
        inst.write(f"SENS:FRES:NPLC {nplc}")
        integration_ms = nplc * 20.0
        print(f"  [滤波设置] NPLC={nplc} (单点积分时间 {integration_ms:.0f}ms)，彻底消除 50Hz 工频纹波噪音。")

    @staticmethod
    def case_trigger_read(inst: Union[Any, MockInstrument]) -> float:
        """
        [案例 4] READ? - 触发并获取高精度浮点测量值
        """
        print("\n--- [DMM6500 案例 4] READ? 启动采样并回读数值 ---")
        val_str = inst.query("READ?").strip()
        reading = float(val_str)
        print(f"  [高精度读数] 实测电阻: {reading:.5f} 欧姆")
        return reading

    @staticmethod
    def case_one_shot_measure(inst: Union[Any, MockInstrument], mode: str = "VOLT:DC") -> float:
        """
        [案例 5] MEAS:<mode>? - 极简单步宏测量
        一步完成模式初始化、量程自动调整、触发转换并回传结果。
        """
        print(f"\n--- [DMM6500 案例 5] MEAS:{mode}? 单步一键宏测量 ---")
        val_str = inst.query(f"MEAS:{mode}?").strip()
        reading = float(val_str)
        unit = "V" if "VOLT" in mode else "A"
        print(f"  [宏测量结果] 读数: {reading:.6f} {unit}")
        return reading


# =============================================================================
# 六、 统一实战主控执行入口 (Runnable Main Demo)
# =============================================================================

def run_all_cases() -> None:
    """按顺序演示并输出所有的 * 与 : 实战案例"""
    print("=" * 80)
    print("      SCPI 仪器控制核心语法全案例实战运行库 (* 与 : 指令专题)")
    print("      (Author: mozial | Target: DP2031, DG5072, SDS5054X, DMM6500)")
    print("=" * 80)

    # 1. IEEE 488.2 * 指令全套演示
    print("\n" + "#" * 80)
    print("【第一章】IEEE 488.2 标准通用指令 (* 开头) 实战全景")
    print("#" * 80)
    mock_gen = MockInstrument("USB0::0x1AB1::0x0001::MOCK::INSTR", "GENERIC")
    IEEE488AsteriskCases.case_idn_identification(mock_gen)
    IEEE488AsteriskCases.case_rst_reset(mock_gen)
    IEEE488AsteriskCases.case_cls_clear_status(mock_gen)
    IEEE488AsteriskCases.case_opc_operation_complete(mock_gen)

    # 2. Rigol DP2031 : 指令全套演示
    print("\n" + "#" * 80)
    print("【第二章】Rigol DP2031 直流稳压电源 (: 开头) 业务指令全景")
    print("#" * 80)
    mock_dp = MockInstrument("USB0::0x1AB1::0x0E11::DP2031_001::INSTR", "DP2031")
    RigolDP2031ColonCases.case_apply_composite(mock_dp, ch=1, volt=5.0, curr=0.5)
    RigolDP2031ColonCases.case_independent_volt_curr(mock_dp, ch=1, volt=3.3, curr=0.1)
    RigolDP2031ColonCases.case_hardware_protection(mock_dp, ch=1, ovp_v=6.5, ocp_a=0.2)
    RigolDP2031ColonCases.case_power_switch(mock_dp, ch=1, enable=True)
    RigolDP2031ColonCases.case_hardware_measurements(mock_dp, ch=1)
    RigolDP2031ColonCases.case_power_switch(mock_dp, ch=1, enable=False)

    # 3. Rigol DG5072 : 指令全套演示
    print("\n" + "#" * 80)
    print("【第三章】Rigol DG5072 信号发生器 (: 开头) 业务指令全景")
    print("#" * 80)
    mock_dg = MockInstrument("USB0::0x1AB1::0x0640::DG5072_001::INSTR", "DG5072")
    RigolDG5072ColonCases.case_impedance_matching(mock_dg, ch=1)
    RigolDG5072ColonCases.case_function_modes(mock_dg, ch=1, mode="PULS")
    RigolDG5072ColonCases.case_pulse_parameters(mock_dg, ch=1, v_low=1.34, v_high=2.92, period=0.0005, width=30e-6)
    RigolDG5072ColonCases.case_ramp_symmetry(mock_dg, ch=1, symm=100)
    RigolDG5072ColonCases.case_burst_trigger(mock_dg, ch=1, n_cycles=1)
    RigolDG5072ColonCases.case_dac16_raw_injection(mock_dg, ch=1)
    RigolDG5072ColonCases.case_output_control(mock_dg, ch=1, enable=True)
    RigolDG5072ColonCases.case_output_control(mock_dg, ch=1, enable=False)

    # 4. Siglent SDS5054X : 指令全套演示
    print("\n" + "#" * 80)
    print("【第四章】Siglent SDS5054X 数字存储示波器业务指令全景")
    print("#" * 80)
    mock_sds = MockInstrument("TCPIP0::192.168.1.100::inst0::INSTR", "SDS5054")
    SiglentSDS5054ColonCases.case_header_suppression(mock_sds)
    SiglentSDS5054ColonCases.case_channel_conditioning(mock_sds, ch=1)
    SiglentSDS5054ColonCases.case_vertical_and_horizontal(mock_sds, ch=1, v_scale=0.1, v_offset=0.0, t_scale=500e-6)
    SiglentSDS5054ColonCases.case_edge_trigger_single(mock_sds, ch=1, level=0.3)
    SiglentSDS5054ColonCases.case_inr_trigger_polling(mock_sds, timeout_sec=1.0)
    SiglentSDS5054ColonCases.case_screen_parameter_measure(mock_sds, ch=1)
    SiglentSDS5054ColonCases.case_waveform_binary_download(mock_sds, ch=1)

    # 5. Keithley DMM6500 : 指令全套演示
    print("\n" + "#" * 80)
    print("【第五章】Keithley DMM6500 六位半数字万用表业务指令全景")
    print("#" * 80)
    mock_dmm = MockInstrument("USB0::0x05E6::0x6500::04456789::INSTR", "DMM6500")
    KeithleyDMM6500ColonCases.case_function_selection(mock_dmm, func="FRES")
    KeithleyDMM6500ColonCases.case_range_control(mock_dmm, auto=False, fixed_range=100.0)
    KeithleyDMM6500ColonCases.case_nplc_filtering(mock_dmm, nplc=10.0)
    KeithleyDMM6500ColonCases.case_trigger_read(mock_dmm)
    KeithleyDMM6500ColonCases.case_one_shot_measure(mock_dmm, mode="VOLT:DC")

    print("\n" + "=" * 80)
    print("[OK] 全部 * 与 : 指令案例库已顺利执行完毕！")
    print("=" * 80)


if __name__ == '__main__':
    run_all_cases()
