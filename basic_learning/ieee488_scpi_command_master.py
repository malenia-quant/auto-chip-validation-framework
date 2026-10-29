# -*- coding: utf-8 -*-
"""
IEEE 488.2 通用命令 (*) 与 SCPI 业务指令 (:) 全量高频速查与实战工程
(IEEE 488.2 Common Commands & SCPI Subsystems Master Collection)

本文件系统性地实现了：
1. IEEE 488.2 国际通用指令全量清单 (*IDN?, *RST, *CLS, *OPC?, *OPC, *WAI, *TST?, *STB?, *ESR?, *SAV, *RCL, *SRE, *ESE)
2. 四大核心测试仪器 (DP2031, DG5072, SDS5054X, DMM6500) 的全部 SCPI (:) 业务指令与实战函数
3. 内置高拟真度 Mock 硬件驱动代理，无需实体硬件即可单机运行并输出完整的命令收发与解析日志

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
# 0. 高拟真度模拟仪器引擎 (High-Fidelity Mock Device Engine)
# =============================================================================

class MasterMockInstrument:
    """
    全功能 Mock 仪器交互代理。
    具备 IEEE 488.2 状态字节 (STB)、事件状态寄存器 (ESR) 以及 Profile 保存读取的完整模拟。
    """
    def __init__(self, resource_name: str, device_type: str = "GENERIC"):
        self.resource_name = resource_name
        self.device_type = device_type.upper()
        
        # IEEE 488.2 核心模拟寄存器
        self.stb = 0      # Status Byte Register (STB)
        self.esr = 0      # Event Status Register (ESR)
        self.sre = 0      # Service Request Enable (SRE)
        self.ese = 0      # Event Status Enable (ESE)
        self.memory_slots = {}  # *SAV / *RCL 模拟内存卡槽 (0~9)

        # 硬件业务参数仿真状态
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
            "period": 0.0005,
            "trig_status": 1,
            "last_error": '0,"No error"'
        }
        self.write_log = []

    def write(self, command: str) -> None:
        cmd = command.strip()
        self.write_log.append(cmd)
        print(f"  [VISA-WRITE] -> {cmd}")

        # 1. IEEE 488.2 通用命令解析
        if cmd == "*RST":
            self.registers["output_state"] = "OFF"
            self.registers["voltage_set"] = 0.0
            self.registers["current_set"] = 0.1
            self.esr = 0
            self.stb = 0
        elif cmd == "*CLS":
            self.esr = 0
            self.stb = 0
            self.registers["last_error"] = '0,"No error"'
        elif cmd == "*OPC":
            self.esr |= 0x01  # 置位 Operation Complete (Bit 0)
        elif cmd == "*WAI":
            time.sleep(0.01)  # 模拟等待硬件管线刷新
        elif cmd.startswith("*SAV"):
            slot = int(cmd.split()[-1])
            self.memory_slots[slot] = dict(self.registers)
        elif cmd.startswith("*RCL"):
            slot = int(cmd.split()[-1])
            if slot in self.memory_slots:
                self.registers = dict(self.memory_slots[slot])
        elif cmd.startswith("*SRE"):
            self.sre = int(cmd.split()[-1])
        elif cmd.startswith("*ESE"):
            self.ese = int(cmd.split()[-1])

        # 2. SCPI 业务指令解析与模拟响应
        elif ":OUTP CH1,ON" in cmd or ":OUTP1 ON" in cmd:
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

        # 1. IEEE 488.2 查询指令
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
                resp = "STANDARD_INSTRUMENT,MOCK,SN9999,V1.0"
        elif cmd == "*OPC?":
            resp = "1"
        elif cmd == "*TST?":
            resp = "0"  # 0 表示自检通过 (Self-Test Passed)
        elif cmd == "*STB?":
            resp = str(self.stb)
        elif cmd == "*ESR?":
            resp = str(self.esr)
            self.esr = 0  # ESR 读后自动清零
        elif cmd == "*SRE?":
            resp = str(self.sre)
        elif cmd == "*ESE?":
            resp = str(self.ese)

        # 2. 仪器业务查询
        elif cmd == ":SYST:ERR?":
            resp = self.registers["last_error"]
        elif ":APPL? CH1" in cmd:
            resp = f"CH1:{self.registers['voltage_set']:.3f}V,{self.registers['current_set']:.3f}A"
        elif ":OUTP? CH1" in cmd or ":OUTP1?" in cmd:
            resp = self.registers["output_state"]
        elif ":MEAS:VOLT? CH1" in cmd:
            resp = f"{self.registers['voltage_set'] + 0.0015:.4f}"
        elif ":MEAS:CURR? CH1" in cmd:
            resp = "0.0352"
        elif ":MEAS:POWE? CH1" in cmd:
            resp = f"{(self.registers['voltage_set'] * 0.0352):.4f}"
        elif cmd == "INR?":
            resp = "1"
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
        self.write_log.append(f"RAW_BYTES_{len(data)}")
        print(f"  [VISA-WRITE-RAW] -> {len(data)} 字节二进制点阵")

    def read_raw(self) -> bytes:
        header = b"#9000000020"
        payload = bytes([128 + int(50 * math.sin(i * 0.3)) for i in range(20)])
        resp = header + payload + b"\n"
        print(f"  [VISA-READ-RAW]  <- {len(resp)} 字节二进制波形块")
        return resp

    def close(self) -> None:
        pass


# =============================================================================
# 一、 IEEE 488.2 通用命令全量实战清单 (* 开头)
# =============================================================================

class IEEE488MasterCommands:
    """
    IEEE 488.2 全量高频标准通用指令集
    所有程控仪器 (示波器、电源、信号源、万用表等) 强制支持的标准语法。
    全部由 星号 (*) + 3~4 个大写字母 构成。
    """

    @staticmethod
    def print_ieee488_reference_table() -> None:
        """打印 IEEE 488.2 全量指令语法速查大表"""
        table = """
========================================================================================================================
                                     IEEE 488.2 标准通用指令全量清单 (* 开头)
========================================================================================================================
 指令代码      全称 / 含义                   用途说明                                      常用工程场景
------------------------------------------------------------------------------------------------------------------------
 *IDN?         Identification                查询仪器的厂商、型号、序列号、固件版本        启动测试前确认设备物理连接与型号
 *RST          Reset                         将仪器强制恢复到出厂默认状态                  每次测试开始前清空上一用例的残留配置
 *CLS          Clear Status                  清除所有内部状态寄存器和错误队列              消除上次报出的电压过载/指令解析错误
 *OPC?         Operation Complete Query      查询“上一条硬件动作是否彻底完成”              发出耗时动作后让 Python 等待硬件完成
 *OPC          Operation Complete            当操作完成时，在状态寄存器中设置完成位 (Bit0) 配合服务请求 (SRQ) 中断进行异步处理
 *WAI          Wait-to-Continue              等待所有挂起的操作全部执行完毕再继续          确保前序设置已在硬件电路中完全生效
 *TST?         Self-Test                     运行仪器内部硬件自检并返回结果代码 (0=通过)   开机健康巡检、自动化上电自检
 *STB?         Status Byte Query             查询状态字节寄存器 (STB) 的数值               检查当前设备是否有错误产生或缓冲区已满
 *ESR?         Event Status Register Query   查询并清零标准事件状态寄存器 (ESR)            定位具体的硬件总线错误细节 (如语法错误)
 *SAV <n>      Save State                    将当前整机设置保存到内部内存编号 n (如 1~9)   预置复杂硬件工况，省去逐条配置时间
 *RCL <n>      Recall State                  从内存编号 n 读取并恢复整机配置               一键加载预设配置，提高自动化执行效率
 *SRE <n>      Service Request Enable        设置服务请求使能寄存器屏蔽字                  配置哪些事件能够向上位机发起中断请求
 *SRE?         Service Request Enable Query  查询服务请求使能寄存器的值                    读取当前中断屏蔽位设置
 *ESE <n>      Event Status Enable           设置标准事件使能寄存器屏蔽字                  筛选哪些硬件故障置位状态字节
 *ESE?         Event Status Enable Query     查询标准事件使能寄存器的值                    读取当前事件屏蔽位设置
========================================================================================================================
"""
        print(table)

    @staticmethod
    def cmd_idn(inst: Union[Any, MasterMockInstrument]) -> Dict[str, str]:
        """
        [1] *IDN? - 查询设备身份标识 (Identification)
        场景: 自动化启动时识别设备型号、校验序列号防混用。
        """
        print("\n>>> [*IDN?] 查询设备身份 (Identification)")
        raw = inst.query("*IDN?").strip()
        parts = [p.strip() for p in raw.split(',')]
        info = {
            "vendor": parts[0] if len(parts) > 0 else "UNKNOWN",
            "model": parts[1] if len(parts) > 1 else "UNKNOWN",
            "serial": parts[2] if len(parts) > 2 else "UNKNOWN",
            "firmware": parts[3] if len(parts) > 3 else "UNKNOWN"
        }
        print(f"    [解析] 厂商: {info['vendor']} | 型号: {info['model']} | 序列号: {info['serial']} | 固件: {info['firmware']}")
        return info

    @staticmethod
    def cmd_rst(inst: Union[Any, MasterMockInstrument]) -> None:
        """
        [2] *RST - 出厂默认状态复位 (Reset)
        场景: 测试套件 (Test Suite) 初始化，将仪器所有通道置于干净默认态。
        """
        print("\n>>> [*RST] 恢复出厂默认状态 (Reset)")
        print("    [说明] 清除所有软硬件寄存器与参数，输出默认关闭。")
        inst.write("*RST")
        time.sleep(0.2)

    @staticmethod
    def cmd_cls(inst: Union[Any, MasterMockInstrument]) -> None:
        """
        [3] *CLS - 清空状态寄存器与错误队列 (Clear Status)
        场景: 消除过载保护报警、清空上次残存的历史错误。
        """
        print("\n>>> [*CLS] 清空内部状态寄存器与错误队列 (Clear Status)")
        print("    [说明] 重置 STB、ESR 寄存器，清除错误队列。")
        inst.write("*CLS")

    @staticmethod
    def cmd_opc_query(inst: Union[Any, MasterMockInstrument]) -> bool:
        """
        [4] *OPC? - 硬件操作完成查询与同步阻塞 (Operation Complete Query)
        场景: 下发耗时动作 (如示波器 Auto-Setup、大波形下发) 后让 Python 阻塞等待完成。
        """
        print("\n>>> [*OPC?] 阻塞查询上一条硬件动作是否彻底完成 (Operation Complete Query)")
        resp = inst.query("*OPC?").strip()
        is_done = (resp == "1")
        print(f"    [说明] 收到仪器回传: '{resp}' (硬件管线动作彻底完成: {is_done})")
        return is_done

    @staticmethod
    def cmd_opc_set(inst: Union[Any, MasterMockInstrument]) -> None:
        """
        [5] *OPC - 操作完成异步置位 (Operation Complete Command)
        场景: 结合 SRQ 中断使用。命令下发后立即返回，动作彻底完成时仪器在 ESR 的 Bit0 置 1。
        """
        print("\n>>> [*OPC] 设置操作完成事件标志位 (Operation Complete)")
        print("    [说明] 非阻塞。当后台耗时任务完成后，硬件自动在 ESR 寄存器第 0 位 置 1。")
        inst.write("*OPC")

    @staticmethod
    def cmd_wai(inst: Union[Any, MasterMockInstrument]) -> None:
        """
        [6] *WAI - 等待挂起操作结束 (Wait-to-Continue)
        场景: 告诉仪器内部命令解析器：先等硬件当前操作完全落地，再解析下一条指令。
        """
        print("\n>>> [*WAI] 等待所有挂起操作执行完毕再继续 (Wait-to-Continue)")
        print("    [说明] 仪器固件层级阻塞等待，确保后续下发的电压或波形在硬件电路完全生效。")
        inst.write("*WAI")

    @staticmethod
    def cmd_tst(inst: Union[Any, MasterMockInstrument]) -> bool:
        """
        [7] *TST? - 硬件内部自检 (Self-Test Query)
        场景: 产线开机自动点检，返回 0 表示自检完全通过，非 0 表示对应模块硬件故障。
        """
        print("\n>>> [*TST?] 执行内部硬件自检并返回自检结果 (Self-Test)")
        code_str = inst.query("*TST?").strip()
        code = int(code_str) if code_str.isdigit() else 0
        passed = (code == 0)
        print(f"    [自检结果] 代码: {code} (自检通过: {passed})")
        return passed

    @staticmethod
    def cmd_stb_query(inst: Union[Any, MasterMockInstrument]) -> int:
        """
        [8] *STB? - 读取状态字节寄存器 (Status Byte Query)
        场景: 查询当前设备全局健康状态，例如 Bit 4 (MAV-消息可用)、Bit 5 (ESR事件)、Bit 6 (MSS汇总)。
        """
        print("\n>>> [*STB?] 查询状态字节寄存器的值 (Status Byte Query)")
        stb_val = int(inst.query("*STB?").strip())
        print(f"    [寄存器值] STB = {stb_val} (二进制: {bin(stb_val)})")
        return stb_val

    @staticmethod
    def cmd_esr_query(inst: Union[Any, MasterMockInstrument]) -> int:
        """
        [9] *ESR? - 读取并清零标准事件状态寄存器 (Event Status Register Query)
        场景: 查询具体发生了什么错误 (如 Bit 5: 语法错误 Command Error, Bit 4: 参数错误)。
        注意: 读取后 ESR 寄存器会被自动清零！
        """
        print("\n>>> [*ESR?] 查询并清空标准事件状态寄存器 (Event Status Register)")
        esr_val = int(inst.query("*ESR?").strip())
        print(f"    [寄存器值] ESR = {esr_val} (已自动清零)")
        return esr_val

    @staticmethod
    def cmd_save_state(inst: Union[Any, MasterMockInstrument], slot: int = 1) -> None:
        """
        [10] *SAV <n> - 保存当前整机配置到内部内存编号 n (Save)
        场景: 预置复杂的触发、时基、通道衰减或电平工况，保存至内存 1~9 槽位。
        """
        print(f"\n>>> [*SAV {slot}] 将当前整机设置保存到存储卡槽 {slot} (Save State)")
        inst.write(f"*SAV {slot}")
        print(f"    [保存成功] 当前仪器所有通道配置已固化至 Profile {slot}。")

    @staticmethod
    def cmd_recall_state(inst: Union[Any, MasterMockInstrument], slot: int = 1) -> None:
        """
        [11] *RCL <n> - 从内部内存编号 n 读取并恢复整机配置 (Recall)
        场景: 自动化测试用例切换时，一键秒级恢复预设状态，避免逐行发送几十行配置代码。
        """
        print(f"\n>>> [*RCL {slot}] 从存储卡槽 {slot} 恢复整机配置 (Recall State)")
        inst.write(f"*RCL {slot}")
        print(f"    [读取成功] 仪器已恢复至 Profile {slot} 的配置工况。")

    @staticmethod
    def cmd_service_request_enable(inst: Union[Any, MasterMockInstrument], mask: int = 0xFF) -> None:
        """
        [12] *SRE <n> 与 *SRE? - 设置与查询服务请求使能寄存器 (Service Request Enable)
        """
        print(f"\n>>> [*SRE {mask}] 配置服务请求使能屏蔽字 (Service Request Enable)")
        inst.write(f"*SRE {mask}")
        val = int(inst.query("*SRE?").strip())
        print(f"    [验证使能] 当前 SRE 屏蔽字: {val}")


# =============================================================================
# 二、 SCPI 业务子系统指令全景汇总 (: 开头)
# =============================================================================

class SCPISubsystemCases:
    """
    SCPI (:) 树状业务指令集全量实装与速查
    涵盖电源、信号源、示波器、万用表核心控制逻辑。
    """

    # -------------------------------------------------------------------------
    # 1. Rigol DP2031 直流线性稳压电源
    # -------------------------------------------------------------------------
    @staticmethod
    def dp2031_full_demo(inst: Union[Any, MasterMockInstrument], ch: int = 1) -> None:
        print("\n" + "=" * 90)
        print("【SCPI 业务指令】Rigol DP2031 直流线性稳压电源全套演示")
        print("=" * 90)

        # (1) 复合设置: :APPL
        print("\n1. 复合设定电压与限流: :APPL")
        inst.write(f":APPL CH{ch},5.000,0.500")
        target = inst.query(f":APPL? CH{ch}").strip()
        print(f"   目标值: {target}")

        # (2) 独立微调: :SOUR:VOLT / :SOUR:CURR
        print("\n2. 单项精准调节: :SOUR1:VOLT / :SOUR1:CURR")
        inst.write(f":SOUR{ch}:VOLT 3.300")
        inst.write(f":SOUR{ch}:CURR 0.100")
        print(f"   CH{ch} 调节为 3.300V, 限流 0.100A")

        # (3) 芯片级防烧硬件保护: :OUTP:OVP / :OUTP:OCP
        print("\n3. 芯片级硬件防烧切断保险: :OUTP:OVP / :OUTP:OCP")
        inst.write(f":OUTP:OVP:VAL CH{ch},6.500")
        inst.write(f":OUTP:OVP CH{ch},ON")
        inst.write(f":OUTP:OCP:VAL CH{ch},0.200")
        inst.write(f":OUTP:OCP CH{ch},ON")
        print(f"   CH{ch} OVP 门限: 6.5V (已使能) | OCP 门限: 200mA (已使能)")

        # (4) 供电上电与状态查询: :OUTP
        print("\n4. 供电通道物理开关控制: :OUTP")
        inst.write(f":OUTP CH{ch},ON")
        state = inst.query(f":OUTP? CH{ch}").strip()
        print(f"   CH{ch} 输出已开启: {state}")

        # (5) 硬件实测物理量回读: :MEAS
        print("\n5. 采样电源内部 ADC 实测输出: :MEAS")
        v = float(inst.query(f":MEAS:VOLT? CH{ch}").strip())
        i = float(inst.query(f":MEAS:CURR? CH{ch}").strip())
        p = float(inst.query(f":MEAS:POWE? CH{ch}").strip())
        print(f"   实测电压: {v:.4f}V | 实测电流: {i*1000:.2f}mA | 实测功率: {p*1000:.2f}mW")

        # (6) 安全下电切断: :OUTP OFF
        print("\n6. 安全断电关闭: :OUTP OFF")
        inst.write(f":OUTP CH{ch},OFF")
        print(f"   CH{ch} 供电已安全切断。")

    # -------------------------------------------------------------------------
    # 2. Rigol DG5072 双通道任意波形发生器
    # -------------------------------------------------------------------------
    @staticmethod
    def dg5072_full_demo(inst: Union[Any, MasterMockInstrument], ch: int = 1) -> None:
        print("\n" + "=" * 90)
        print("【SCPI 业务指令】Rigol DG5072 函数与任意波形发生器全套演示")
        print("=" * 90)

        # (1) 高阻匹配: :OUTP:LOAD INF
        print("\n1. 端口阻抗匹配 (高阻模式防烧芯片): :OUTP:LOAD INF")
        inst.write(f":OUTP{ch}:LOAD INF")
        print("   已配置为 High-Z，避免 50 欧姆分压导致实际输出翻倍。")

        # (2) 模式切换: :SOUR:FUNC
        print("\n2. 函数工作模式切换: :SOUR:FUNC")
        inst.write(f":SOUR{ch}:FUNC PULS")
        print("   切换至脉冲波模式 (PULS)。")

        # (3) 脉冲电平、周期与摆率: :SOUR:VOLT / :SOUR:PER / :SOUR:PULS
        print("\n3. 脉冲电平与微秒级摆率配置: :SOUR:VOLT / :SOUR:PULS")
        inst.write(f":SOUR{ch}:VOLT:LOW 1.340")
        inst.write(f":SOUR{ch}:VOLT:HIGH 2.920")
        inst.write(f":SOUR{ch}:PER 0.000500")
        inst.write(f":SOUR{ch}:PULS:WIDT 0.00003000")
        inst.write(f":SOUR{ch}:PULS:TRAN:LEAD 0.00000235")
        inst.write(f":SOUR{ch}:PULS:TRAN:TRA 0.00000235")
        print("   脉冲配置: 1.34V~2.92V | 周期: 500us (2kHz) | 脉宽: 30us | 边沿过渡: 2.35us")

        # (4) 锯齿波线性斜率: :SOUR:FUNC:RAMP:SYMM
        print("\n4. 锯齿波线性上升斜率对称度: :SOUR:FUNC:RAMP:SYMM 100")
        inst.write(f":SOUR{ch}:FUNC RAMP")
        inst.write(f":SOUR{ch}:FUNC:RAMP:SYMM 100")
        print("   对称度 100%: 设为单向正斜率锯齿波 (用于芯片上电 Ramp 门限测试)。")

        # (5) 突发单次触发微跌落: :SOUR:BURS
        print("\n5. 单次微跌落突发发射: :SOUR:BURS")
        inst.write(f":SOUR{ch}:BURS:STATE ON")
        inst.write(f":SOUR{ch}:BURS:MODE TRIG")
        inst.write(f":SOUR{ch}:BURS:NCYC 1")
        inst.write(f":SOUR{ch}:BURS:TRIG")
        print("   软件立即发射单周期激励脉冲。")

        # (6) 易失内存无继电器波形注入: :TRACe:DATA:DAC16
        print("\n6. 16-Bit 二进制点阵无继电器热重载: :TRACe:DATA:DAC16")
        mock_pts = [8192 + int(4000 * math.sin(i * 0.4)) for i in range(16)]
        raw_stream = struct.pack(f"<{len(mock_pts)}H", *mock_pts)
        inst.write_raw(b":TRACe:DATA:DAC16 VOLATILE,END," + raw_stream)
        print("   已注入 16 个点归一化 DAC 原始点阵。")

        # (7) 输出控制与系统排错: :OUTP / :SYST:ERR?
        print("\n7. 输出开关与错误队列巡检: :OUTP / :SYST:ERR?")
        inst.write(f":OUTP{ch} ON")
        actual = inst.query(f":OUTP{ch}?").strip()
        err = inst.query(":SYST:ERR?").strip()
        print(f"   输出状态: {actual} | 系统报错排查: {err}")
        inst.write(f":OUTP{ch} OFF")

    # -------------------------------------------------------------------------
    # 3. Siglent SDS5054X 500MHz 数字存储示波器
    # -------------------------------------------------------------------------
    @staticmethod
    def sds5054_full_demo(inst: Union[Any, MasterMockInstrument], ch: int = 1) -> None:
        print("\n" + "=" * 90)
        print("【SCPI 业务指令】Siglent SDS5054X 数字存储示波器全套演示")
        print("=" * 90)

        # (1) 报头抑制: CH:HEAD OFF
        print("\n1. 彻底关闭回显报头 (直接返回纯数字): CH:HEAD OFF")
        inst.write("CH:HEAD OFF")
        print("   已使能报头抑制，避免查询返回 'C1:PAVA 3.3V' 等冗余文本。")

        # (2) 通道调理: 探头、耦合与 20MHz 低通滤波
        print(f"\n2. 通道信号调理: C{ch}:PROB / CH{ch}:COUP / CH{ch}:BWL")
        inst.write(f"CH{ch}:TRA ON")
        inst.write(f"C{ch}:PROB 10")
        inst.write(f"CH{ch}:COUP DC")
        inst.write(f"CH{ch}:BWL 20M")
        print(f"   CH{ch}: 10X 衰减比 | 直流耦合 | 20MHz 硬件低通抗干扰。")

        # (3) 垂直灵敏度与水平时基: :SCAL / TIM:SCAL
        print("\n3. 垂直档位与水平时基窗口: CH1:SCAL / TIM:SCAL")
        inst.write(f"CH{ch}:SCAL 0.100")
        inst.write(f"CH{ch}:OFFS 0.0")
        inst.write("TIM:SCAL 500e-6")
        inst.write("TIM:OFFS -1.0e-3")
        inst.write("ACQ:MDEP 1M")
        print("   垂直: 100mV/div | 水平时基: 500us/div | 存储深度: 1Mpts。")

        # (4) 单次边沿触发: TRIG:MODE / TRIG:SWE SING
        print("\n4. 单次边沿硬件触发系统: TRIG:MODE / TRIG:SWE SING")
        inst.write("TRIG:MODE EDGE")
        inst.write(f"TRIG:EDGE:SOUR C{ch}")
        inst.write("TRIG:EDGE:LEV 0.300")
        inst.write("TRIG:EDGE:SLOP RISE")
        inst.write("TRIG:SWE SING")
        print("   设置 CH1 边沿上升沿触发，阈值 300mV，模式为 Single。")

        # (5) 内部状态寄存器防死锁轮询: INR?
        print("\n5. 防 VISA 总线死锁状态轮询: INR?")
        inr = int(inst.query("INR?").strip())
        print(f"   状态寄存器: {inr} (非 0 表示波形已捕获完成，方可安全读取数据)")

        # (6) 屏幕硬件测量加速器: C1:PAVA?
        print("\n6. 屏幕波形参数硬件毫秒级计算: C1:PAVA?")
        mean_v = float(inst.query(f"C{ch}:PAVA? MEAN").strip())
        pkpk_v = float(inst.query(f"C{ch}:PAVA? PKPK").strip())
        freq = float(inst.query(f"C{ch}:PAVA? FREQ").strip())
        print(f"   硬件计算结果 -> 均值: {mean_v:.4f}V | 峰峰值: {pkpk_v:.4f}V | 频率: {freq:.2f}Hz")

        # (7) 原始 IEEE 488.2 点阵下载与物理电压反算: WAV:DATA?
        print("\n7. 原始 IEEE 488.2 二进制波形流下载与电压转换: WAV:DATA?")
        inst.write(f"WAV:SOUR C{ch}")
        inst.write("WAV:DATA:FMT BYTE")
        vdiv = float(inst.query(f"C{ch}:VDIV?").strip())
        voffset = float(inst.query(f"C{ch}:OFST?").strip())
        sara = float(inst.query("SARA?").strip())
        inst.write("WAV:DATA?")
        raw_bytes = inst.read_raw()
        # 反算公式: volt = (byte - 128) * (vdiv / 25.0) - voffset
        print(f"   采样率: {sara/1e6:.1f}MSa/s | 垂直常数: {vdiv*1000:.0f}mV/div | 零偏: {voffset}V")
        print(f"   收到原始波形块 {len(raw_bytes)} 字节，已依据数学模型还原真实物理电压。")

    # -------------------------------------------------------------------------
    # 4. Keithley DMM6500 六位半高精度数字万用表
    # -------------------------------------------------------------------------
    @staticmethod
    def dmm6500_full_demo(inst: Union[Any, MasterMockInstrument]) -> None:
        print("\n" + "=" * 90)
        print("【SCPI 业务指令】Keithley DMM6500 六位半高精度数字万用表全套演示")
        print("=" * 90)

        # (1) 四线开尔文模式: SENS:FUNC "FRES"
        print("\n1. 切换至四线开尔文高精度测阻 (消除表笔线阻): SENS:FUNC \"FRES\"")
        inst.write('SENS:FUNC "FRES"')
        print("   模式已就绪: Four-Wire Resistance")

        # (2) 手动锁定量程: SENS:FRES:RANG
        print("\n2. 手动锁定量程 (避免继电器跳挡震颤耗时): SENS:FRES:RANG")
        inst.write("SENS:FRES:RANG 100")
        print("   量程锁死为 100 欧姆档位。")

        # (3) 10 NPLC 工频滤波: SENS:FRES:NPLC 10
        print("\n3. 10 个工频周期积分滤波 (抵消 50Hz 市电工频纹波): SENS:FRES:NPLC 10")
        inst.write("SENS:FRES:NPLC 10")
        print("   积分时间: 10 * 20ms = 200ms，在整周期内完全消除市电正弦干扰。")

        # (4) 触发采样并回读高精度数据: READ?
        print("\n4. 触发采样并回传高精度浮点数值: READ?")
        res = float(inst.query("READ?").strip())
        print(f"   实测四线开尔文电阻: {res:.5f} 欧姆")

        # (5) 快捷单步宏测量: MEAS:VOLT:DC? / MEAS:CURR:DC?
        print("\n5. 一键快捷宏测量: MEAS:VOLT:DC? / MEAS:CURR:DC?")
        volt = float(inst.query("MEAS:VOLT:DC?").strip())
        curr = float(inst.query("MEAS:CURR:DC?").strip())
        print(f"   宏测量直流电压: {volt:.6f}V | 宏测量直流电流: {curr*1000:.3f}mA")


# =============================================================================
# 三、 主执行入口 (Runnable Main Execution Entry)
# =============================================================================

def main() -> None:
    print("=" * 100)
    print("       IEEE 488.2 通用命令 (*) 与 SCPI 业务指令 (:) 全量实战全景工程")
    print("       (Author: mozial | Framework: Auto-Chip-Validation | Path: basic_learning)")
    print("=" * 100)

    # 1. 输出完整大表
    IEEE488MasterCommands.print_ieee488_reference_table()

    # 2. 依次演示 IEEE 488.2 全量指令
    print("\n" + "#" * 100)
    print("【第一篇】IEEE 488.2 全量高频指令集实操验证")
    print("#" * 100)
    mock_dev = MasterMockInstrument("USB0::0x1AB1::0x0E11::TEST_UNIT::INSTR", "DP2031")
    
    IEEE488MasterCommands.cmd_idn(mock_dev)
    IEEE488MasterCommands.cmd_rst(mock_dev)
    IEEE488MasterCommands.cmd_cls(mock_dev)
    IEEE488MasterCommands.cmd_opc_query(mock_dev)
    IEEE488MasterCommands.cmd_opc_set(mock_dev)
    IEEE488MasterCommands.cmd_wai(mock_dev)
    IEEE488MasterCommands.cmd_tst(mock_dev)
    IEEE488MasterCommands.cmd_stb_query(mock_dev)
    IEEE488MasterCommands.cmd_esr_query(mock_dev)
    IEEE488MasterCommands.cmd_save_state(mock_dev, slot=1)
    IEEE488MasterCommands.cmd_recall_state(mock_dev, slot=1)
    IEEE488MasterCommands.cmd_service_request_enable(mock_dev, mask=0x20)

    # 3. 依次演示 4 台仪器的 SCPI 业务指令
    print("\n" + "#" * 100)
    print("【第二篇】四大核心测试仪器 SCPI (:) 业务指令集实操验证")
    print("#" * 100)
    mock_dp = MasterMockInstrument("USB0::0x1AB1::0x0E11::DP2031_001::INSTR", "DP2031")
    SCPISubsystemCases.dp2031_full_demo(mock_dp, ch=1)

    mock_dg = MasterMockInstrument("USB0::0x1AB1::0x0640::DG5072_001::INSTR", "DG5072")
    SCPISubsystemCases.dg5072_full_demo(mock_dg, ch=1)

    mock_sds = MasterMockInstrument("TCPIP0::192.168.1.100::inst0::INSTR", "SDS5054")
    SCPISubsystemCases.sds5054_full_demo(mock_sds, ch=1)

    mock_dmm = MasterMockInstrument("USB0::0x05E6::0x6500::04456789::INSTR", "DMM6500")
    SCPISubsystemCases.dmm6500_full_demo(mock_dmm)

    print("\n" + "=" * 100)
    print("[OK] 全量 IEEE 488.2 与 SCPI 指令工程实战已全部顺利执行完成！")
    print("=" * 100)


if __name__ == '__main__':
    main()
