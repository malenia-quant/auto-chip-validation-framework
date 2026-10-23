import pyvisa
import numpy as np
import time
import math

# ==============================================================================
# 区域一：全局参数与测试边界配置区 (Global & Specification Config Area)
# ==============================================================================
# 1: 手动单次测试模式 (读取区域一的 MANUAL_ 参数)
# 2: 18种标准状态矩阵模式 (终端输入 1-18 动态选择，调用下方变量组合)
EXECUTION_MODE = 2 

# 全局调试模式默认状态 (可在终端交互中输入 'd' 动态切换)
# True: 无限循环输出(方便示波器抓取) | False: 执行真实的 4 秒硬实时注入
DEBUG_CONTINUOUS = True 

# --- 通用基础电压配置 ---
V_BASE = 0.45             # 正常通信基准电压 (V) (根据当前测试需求可修改)
V_SYNC_HIGH = 2.7         # 同步脉冲高电平电压 (V)

# ------------------------------------------------------------------------------
# 依据 PSI5 Spec 图谱定义的物理边界变量 (提取自 Vdd_Reset=4V, t_reset=4ms)
# ------------------------------------------------------------------------------
# 1. 注入电压变量 (v_cut_low)
# 自研器件配置
# V_ABOVE_RESET = -1
# V_BELOW_RESET = -4

# 竞品配置
V_ABOVE_RESET = -1.2      # 跌落电压高于 4V (处于图谱上半部分: 白色/黄色/右侧红色上方)
V_BELOW_RESET = -4        # 跌落电压低于 4V (处于图谱下半部分: 白色/中间红色/右侧红色下方)

# 2. 注入持续时间变量 (ucut_duration_us)
DUR_WHITE_ZONE = 6.5      # 白色区域时间: < 33 us (规范要求 10-33us, 取中间值)
DUR_MID_ZONE = 2000.0     # 中间区域时间: > 33 us 且 < 4 ms (取 2ms)
DUR_RED_RIGHT = 5000.0    # 右侧红色时间: > 4 ms (触发 Timer POR, 取 5ms)

# 3. 注入时序位置变量 (ucut_start_us)
POS_IDLE = 300.0          # 位置1: 空闲阶段
POS_BEFORE_SYNC = 40.0    # 位置2: 数据响应前
POS_IN_DATA = 100.0       # 位置3: 数据响应中
POS_IN_SYNC = 15.0        # 位置4: 同步脉冲期间 (用于打断同步脉冲后再恢复)


# --- 手动模式(MODE=1)专属变量 ---
MANUAL_V_CUT_LOW = V_BELOW_RESET
MANUAL_UCUT_DURATION_US = DUR_WHITE_ZONE
MANUAL_UCUT_START_US = POS_IN_SYNC


# ==============================================================================
# 区域二：18种组合状态显式映射区 (18 Cases Matrix Area)
# ==============================================================================
# 结合 6个颜色区域 X 3种注入位置，严格调用上方 Spec 变量组合。
CASES_24_CONFIG = {
    # --------------------------------------------------------------------------
    # 区域 1：白色区域上方 (电压 > Vdd_Reset, 时间 < 指定 uCut 时间)
    # 使用变量: V_ABOVE_RESET (4.2V), DUR_WHITE_ZONE (20.0us)
    # 预期结果: u-Cut Condition, 无故障标志, 不复位
    # --------------------------------------------------------------------------
    1: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_IDLE},
    2: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_BEFORE_SYNC},
    3: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_IN_DATA},
    4: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_IN_SYNC},

    # --------------------------------------------------------------------------
    # 区域 2：白色区域下方 (电压 < Vdd_Reset, 时间 < 指定 uCut 时间)
    # 使用变量: V_BELOW_RESET (2.0V), DUR_WHITE_ZONE (20.0us)
    # 预期结果: u-Cut Condition, 无故障标志, 不复位
    # --------------------------------------------------------------------------
    5: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_IDLE},
    6: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_BEFORE_SYNC},
    7: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_IN_DATA},
    8: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_WHITE_ZONE, "start_us": POS_IN_SYNC},

    # --------------------------------------------------------------------------
    # 区域 3：中间黄色区域 (电压 > Vdd_Reset, 指定 uCut 时间 < 时间 < 4ms)
    # 使用变量: V_ABOVE_RESET (4.2V), DUR_MID_ZONE (2000.0us)
    # 预期结果: ASIC 在规范内 或 无通信
    # --------------------------------------------------------------------------
    9: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_IDLE},
    10: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_BEFORE_SYNC},
    11: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_IN_DATA},
    12: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_IN_SYNC},

    # --------------------------------------------------------------------------
    # 区域 4：中间红色区域 (电压 < Vdd_Reset, 指定 uCut 时间 < 时间 < 4ms)
    # 使用变量: V_BELOW_RESET (2.0V), DUR_MID_ZONE (2000.0us)
    # 预期结果: POR (VDDI 欠压复位)
    # --------------------------------------------------------------------------
    13: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_IDLE},
    14: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_BEFORE_SYNC},
    15: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_IN_DATA},
    16: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_MID_ZONE, "start_us": POS_IN_SYNC},

    # --------------------------------------------------------------------------
    # 区域 5：右侧红色区域上方 (电压 > Vdd_Reset, 时间 > 4ms)
    # 使用变量: V_ABOVE_RESET (4.2V), DUR_RED_RIGHT (5000.0us)
    # 预期结果: POR (被 Timer 触发)
    # --------------------------------------------------------------------------
    17: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_IDLE},
    18: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_BEFORE_SYNC},
    19: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_IN_DATA},
    20: {"v_cut_low": V_ABOVE_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_IN_SYNC},

    # --------------------------------------------------------------------------
    # 区域 6：右侧红色区域下方 (电压 < Vdd_Reset, 时间 > 4ms)
    # 使用变量: V_BELOW_RESET (2.0V), DUR_RED_RIGHT (5000.0us)
    # 预期结果: POR (被 Timer 触发)
    # --------------------------------------------------------------------------
    21: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_IDLE},
    22: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_BEFORE_SYNC},
    23: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_IN_DATA},
    24: {"v_cut_low": V_BELOW_RESET, "duration_us": DUR_RED_RIGHT, "start_us": POS_IN_SYNC},
}

class DG5072Controller:
    # mozial: 加入严格的错误追踪机制与触发逻辑重构
    # mozial: 遵守规范 - 移除打印代码中的 emoji 符号，使用纯文本报错。
    
    def __init__(self, resource_name):
        rm = pyvisa.ResourceManager()
        self.inst = rm.open_resource(resource_name)
        self.inst.timeout = 10000 
        self.inst.write("*CLS") # 清除错误队列
        
    def _write_and_check(self, cmd, is_raw=False):
        """
        mozial: 核心改动！发送指令并立即查询错误队列。
        杜绝盲猜，精准定位报错的具体 SCPI 语句。
        mozial: 遵守规范 - 移除打印代码中的 emoji 符号，使用纯文本报错。
        """
        if is_raw:
            self.inst.write_raw(cmd)
            import time
            time.sleep(0.05)  # 等待大块数据写入
            log_cmd = cmd[:30].decode('ascii', errors='ignore') + " ... [BINARY DATA]"
        else:
            self.inst.write(cmd)
            log_cmd = cmd
            
        # [Fix] 增加通用微小延时，防止在子线程中高速并发时引发 USB INP_PROT_VIOL 冲撞
        import time
        time.sleep(0.1)
        
        # 强制查询系统错误
        try:
            error_resp = self.inst.query(":SYST:ERR?")
            if "No error" not in error_resp and "0" not in error_resp.split(',')[0]:
                print(f"[FATAL ERROR] 指令被拒绝: {log_cmd}")
                print(f"   DG5072 返回: {error_resp.strip()}")
        except pyvisa.VisaIOError:
            # 忽略查询错误队列时的超时或协议报错，防止在终端输出吓人的警告
            pass

    def generate_idle_phase_ucut_waveform(self, 
                                          period_us=1000.0, # mozial: 默认总周期 1ms，承载两组心跳
                                          sync_width_us=30.0, 
                                          ucut_start_us=300.0, 
                                          ucut_duration_us=13.0, # mozial: 默认 u-Cut 更新为 13us
                                          v_base=1.5,      # mozial: 传入真实电压计算偏置 (默认改为1.5V)
                                          v_sync_high=3.5, # mozial: 默认改为3.5V
                                          v_cut_low=0.0,
                                          has_ucut=True):  # mozial: 引入故障开关，用于生成纯净波和故障波
        """
        构造单周期内的 PSI5 注入波形 (仅数值计算，归一化到 -1.0 到 1.0)
        """
        # mozial: 改动点38 - 放宽约束，支持全时段注入测试
            
        # 强制 16384 硬件对齐
        total_points = 16384 
        
        # 动态计算归一化基准电平，彻底消灭硬编码
        v_amp = v_sync_high - v_cut_low
        v_offset = (v_sync_high + v_cut_low) / 2.0
        # 依据真实电压计算出数组中代表基准电平的精确浮点值
        norm_base = (v_base - v_offset) / (v_amp / 2.0) if v_amp != 0 else 0.0
        
        waveform = np.full(total_points, norm_base, dtype=np.float32) 
        
        def us_to_idx(time_us):
            # 防止索引越界
            idx = int((time_us / period_us) * total_points)
            return min(max(idx, 0), total_points)

        # mozial: 改动点38 (背景心跳覆写算法) - 应对 4ms/10ms 超长故障
        # 1. 首先在整个 period_us 周期内，每隔 500us 铺设一个正常的同步脉冲
        for pulse_start in np.arange(0, period_us, 500.0):
            waveform[us_to_idx(pulse_start) : us_to_idx(pulse_start + sync_width_us)] = 1.0 
        
        # 2. 如果存在故障，使用“橡皮擦”逻辑，直接覆写对应时间段的电平为 -1.0 (u-Cut)
        if has_ucut:
            waveform[us_to_idx(ucut_start_us) : us_to_idx(ucut_start_us + ucut_duration_us)] = -1.0 
        
        return waveform

    def load_and_execute_4sec_test(self, 
                                   v_base=1.5,       
                                   v_sync_high=3.5,  
                                   v_cut_low=0.0,
                                   ucut_duration_us=13.0,
                                   ucut_start_us=300.0,
                                   debug_continuous=False,
                                   serial_controller=None,
                                   phase2_start_event=None):
        """
        将波形写入 DG5072，全时段驻留 ARB 模式，通过 RAM 热覆写实现无缝故障注入
        """
        # mozial: 改动点39 - 动态周期推演
        # 为了容纳 4ms (4000us) 等长故障，动态计算安全的 ARB 波形总时长。
        # 规则：起始位置 + 故障时长 + 500us安全余量，并向上对齐到 500us 的整数倍，确保心跳完整。
        serial_controller = getattr(self, 'serial_controller', serial_controller)
        required_us = ucut_start_us + ucut_duration_us + 500.0
        # 恢复原始自适应周期，满足微秒级1ms注入，2ms故障3ms注入的间隔要求
        dynamic_period_us = max(1000.0, math.ceil(required_us / 500.0) * 500.0)
        # === 准备弹药：生成纯净波与故障波的双份二进制流 ===
        wave_clean = self.generate_idle_phase_ucut_waveform(
            period_us=dynamic_period_us, v_base=v_base, v_sync_high=v_sync_high, v_cut_low=v_cut_low, 
            ucut_start_us=ucut_start_us, ucut_duration_us=ucut_duration_us, has_ucut=False
        )
        wave_fault = self.generate_idle_phase_ucut_waveform(
            period_us=dynamic_period_us, v_base=v_base, v_sync_high=v_sync_high, v_cut_low=v_cut_low, 
            ucut_start_us=ucut_start_us, ucut_duration_us=ucut_duration_us, has_ucut=True
        )
        
        # mozial: 坚决回调至 '<u2' (小端序) 彻底解决 0V 钳位
        dac_clean = np.round((wave_clean + 1.0) / 2.0 * 16383).astype('<u2').tobytes()
        dac_fault = np.round((wave_fault + 1.0) / 2.0 * 16383).astype('<u2').tobytes()
        
        header_clean = f"#{len(str(len(dac_clean)))}{len(dac_clean)}".encode('ascii')
        header_fault = f"#{len(str(len(dac_fault)))}{len(dac_fault)}".encode('ascii')
        
        block_clean = header_clean + dac_clean
        block_fault = header_fault + dac_fault

        # === 物理层初始化 ===
        # self._write_and_check(":OUTP1 OFF") # 注释掉以防止中途断电复位
        self._write_and_check(":OUTP1:IMP INF")
        
        # 彻底抛弃 PULS，全时段锁定 ARB 模式，消灭继电器切换断电
        self._write_and_check(":SOUR1:FUNC USER")
        
        # 计算统一的电压满量程范围
        v_amp = v_sync_high - v_cut_low
        v_offset = (v_sync_high + v_cut_low) / 2.0
        self._write_and_check(f":SOUR1:VOLT {v_amp}")
        self._write_and_check(f":SOUR1:VOLT:OFFS {v_offset}")
        
        # 动态降频：保证 16384 点正确播满所需的总时间
        freq_hz = 1000000.0 / dynamic_period_us
        self._write_and_check(f":SOUR1:FREQ {freq_hz}") 
        
        # === 阶段 1：注入纯净波，执行 1秒 正常上电苏醒 ===
        self._write_and_check(b":TRACe:DATA:DAC16 VOLATILE,END," + block_clean, is_raw=True)
        self._write_and_check(":SOUR1:FUNC USER")
        self._write_and_check(":OUTP1 ON")
        
        # mozial: [新增时序] 此时 DG5072 开始输出纯净电压，需要立即发送进修调再退修调，打开 PCB 开关让供电进入
        if serial_controller is not None:
            serial_controller.open_power_switch()
        
        print(f"mozial: [阶段1] 纯净 ARB 模式已开启(自适应周期: {dynamic_period_us}us)，等待 ASIC 苏醒 (1秒)...")
        time.sleep(1.0)
        
        # mozial: 插入串行执行动作 - 发生在第一次正常上电与 ucut 注入之间
        if serial_controller is not None:
            if getattr(self, 'enable_trim', True):
                print("mozial: [串行执行] 开始发送 ucut 注入前的修调指令...")
                serial_controller.run_pre_injection_sequence()
                print("mozial: [串行执行] 修调指令发送完毕。")
            else:
                print("mozial: [串行执行] 注入前修调指令开关已关闭，仅开启电源。")
            
        # === 阶段 2：热覆写 RAM，无缝滑入 4秒 u-Cut 注入 ===
        # 此时 OUTPUT 保持 ON，直接覆写底层 VOLATILE，避免继电器咔哒断电
        if not debug_continuous:
            self._write_and_check(b":TRACe:DATA:DAC16 VOLATILE,END," + block_fault, is_raw=True)
            self._write_and_check(":SOUR1:FUNC USER")  # 强制使能最新波形
            print(f"mozial: [阶段2] 内存热覆写完成，无缝切入 4秒故障注入 (跌落至 {v_cut_low}V, 宽 {ucut_duration_us}us)...")
            
            # [核心修复] 必须在波形完全上传到 DG5072 并且物理注入真正开始后，才释放主线程！
            # 否则主线程会提前触发示波器，导致抓不到波形，状态机彻底混乱！
            if phase2_start_event is not None:
                phase2_start_event.set()
                
            # [修正时序] 延时精确的 4.0 秒覆盖测试周期
            time.sleep(4.0)
            
            # === 阶段 3：安全恢复，热覆写回纯净波 ===
            self._write_and_check(b":TRACe:DATA:DAC16 VOLATILE,END," + block_clean, is_raw=True)
            self._write_and_check(":SOUR1:FUNC USER")  # 强制使能最新波形
            print(f"mozial: [阶段3] 注入结束，已热切换回纯净心跳。")
        else:
            # 调试模式下直接注入故障波并无限循环
            self._write_and_check(b":TRACe:DATA:DAC16 VOLATILE,END," + block_fault, is_raw=True)
            self._write_and_check(":SOUR1:FUNC USER")  # 强制使能最新波形
            print(f"mozial: [主动测试模式] 故障波已无限循环输出，请抓取波形。")

    def close(self):
        if self.inst:
            self.inst.close()


if __name__ == "__main__":
    VISA_RESOURCE = "USB0::0x1AB1::0x0640::DG5T264700198::INSTR" 
    
    controller = None
    try:
        controller = DG5072Controller(VISA_RESOURCE)
        
        # 终端主循环：在此可以自由切换用例和全局模式
        while True:
            print("\n=====================================================")
            print(" DG5072 u-Cut 任意波形注入控制脚本 (严格版)")
            print(" 支持模式：")
            print("   m : 手动模式 (使用代码内配置变量)")
            print("   1-24 : 执行特定的测试用例矩阵")
            print("   d : 切换无限循环 / 单次注入模式")
            print("   q : 退出")
            print("=====================================================\n")
            print("\n当前状态：")
            print(f"   Debug 持续输出模式: {'ON (用于示波器触发)' if DEBUG_CONTINUOUS else 'OFF (执行 4s 真实注入)'}")
            user_in = input("请输入指令 (m / 1-24 / d / q): ").strip().lower()
            
            if user_in == 'q':
                print("mozial: 测试序列已终止。")
                break
                
            elif user_in == 'd':
                DEBUG_CONTINUOUS = not DEBUG_CONTINUOUS
                print(f"mozial: Debug 模式已切换为 -> {DEBUG_CONTINUOUS}")
                continue
                
            elif user_in == 'm':
                print("\n---> 开始执行 [手动配置测试] <---")
                controller.load_and_execute_4sec_test(
                    v_base=V_BASE, 
                    v_sync_high=V_SYNC_HIGH, 
                    v_cut_low=MANUAL_V_CUT_LOW,
                    ucut_duration_us=MANUAL_UCUT_DURATION_US,
                    ucut_start_us=MANUAL_UCUT_START_US,
                    debug_continuous=DEBUG_CONTINUOUS
                )
                continue
            else:
                # 处理 1-24 的矩阵测试输入
                try:
                    case_id = int(user_in)
                    if case_id < 1 or case_id > 24:
                        print("输入错误: 用例编号必须在 1 到 24 之间。")
                        continue
                        
                    if EXECUTION_MODE != 2:
                        print("提示: 当前未处于矩阵模式，但仍为您执行所选 Case。")
                        
                    cfg = CASES_24_CONFIG[case_id]
                    
                    print(f"\n---> 开始执行 Case {case_id} <---")
                    print(f"提取参数: 跌落至 {cfg['v_cut_low']}V, 持续 {cfg['duration_us']}us, 注入位置 {cfg['start_us']}us")
                    
                    controller.load_and_execute_4sec_test(
                        v_base=V_BASE,
                        v_sync_high=V_SYNC_HIGH,
                        v_cut_low=cfg["v_cut_low"],
                        ucut_duration_us=cfg["duration_us"],
                        ucut_start_us=cfg["start_us"],
                        debug_continuous=DEBUG_CONTINUOUS
                    )
                    
                except ValueError:
                    print("输入错误: 无效的指令，请重新输入。")
            
    except pyvisa.VisaIOError as e:
        print(f"VISA 通信失败: {e}")
    except Exception as e:
        print(f"发生未知错误: {e}")
    finally:
        if controller is not None:
            controller.close()
            print("mozial: 仪器连接已安全释放。")