import pyvisa
import numpy as np
import time
import matplotlib

matplotlib.use('Agg')  # 强制使用Agg无头后端，绕开GUI渲染，解决绘图卡顿问题
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter
import csv
import os
import gc
import sys

# [新增] 全局字体配置 Times New Roman, 14号
plt.rcParams['font.family'] = 'Times New Roman'
plt.rcParams['font.size'] = 14

# =============================================================================
# V1.0: Fixed Empty Bit Time / Drift / Duty Cycle
# 1. Logic Fix: Now counts SHORT pulses (~4us) * 2 as valid bits.
#    (Previous versions ignored pulses < 6us, causing empty results).
# 2. Algo: Classifies edges into 'Short' (3.5-5.5us) and 'Long' (6-11us).
# 3. Result: Robust 125k calculation regardless of data pattern (000 vs 010).
# =============================================================================

# --- Global Configuration ---
R_SHUNT = 10.03
TOTAL_SCAN_TIME_MS = 2.0  # [新增] 示波器总捕获窗口长度(ms)
# [警告/修改] 电流波形上的Sync脉冲仅是极窄的充电尖峰，5.0太宽会导致严重漏判！强制改为1.5！
SYNC_WIDTH_MIN = 7
SYNC_WIDTH_MAX = 30.0  # Max Sync Duration (us)
SENSOR_SEARCH_WINDOW = 400.0  # [修改] Search for sensors within 400us after Sync

# [新增] 数据采集通道使能配置（目前设置 CH1 TRUE, CH2 False）
ENABLE_CH1 = True
ENABLE_CH2 = False

# [新增/修改] 全局基线求取分位数配置
GLOBAL_TOP_CUTOFF_FACTOR = 0.95
GLOBAL_BOT_CUTOFF_FACTOR = 0.60

# [新增/修改] 局部上下界均值计算的排除比例配置
LOCAL_TOP_CUTOFF_FACTOR = 0.95
LOCAL_BOT_CUTOFF_FACTOR = 0.05

# [新增] 物理层阈值判定门限因子
LVL_20_FACTOR = 0.2
LVL_50_FACTOR = 0.5
LVL_80_FACTOR = 0.8
THRESHOLD_2_FACTOR = 0.2  # Detection Threshold = Base + 0.2 * Amp

# [新增] 传感器有效波形的最小持续时间(us)，过滤误判的短毛刺
SENSOR_BURST_MIN_WIDTH_US = 50.0


class SDS_Frame_Validator:
    def __init__(self):
        """Initialize VISA resource manager and state variables."""
        self.rm = pyvisa.ResourceManager()
        self.inst = None
        self.scan_counter = 0

        # Drift Calculation Persistence
        self.prev_s1_freq = None
        self.prev_s1_time = None

        # mozial: [新增] 自动检测运行环境，锁定配置文件绝对路径
        # 解决打包后找不到配置文件或配置文件被写到临时目录的问题
        if getattr(sys, 'frozen', False):
            # 打包后的 EXE 模式：路径为可执行文件所在目录
            self.base_path = os.path.dirname(sys.executable)
        else:
            # 源码运行模式：路径为脚本所在目录
            self.base_path = os.path.dirname(os.path.abspath(__file__))

        # [新增] 创建测试数据归档目录
        self.output_dir = os.path.join(self.base_path, f"Test_Results_{time.strftime('%Y%m%d')}")
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        print(f"[*] Output Directory Created: {self.output_dir}")

        # mozial: [修改] 配置文件完整路径定位
        import json
        self.config_file = os.path.join(self.base_path, "zwd_config.json")
        self.app_config = self._load_config()

    def _load_config(self):
        """mozial: [修改] 加载持久化配置。若文件缺失，则在同级目录下自动生成默认配置文件。"""
        import json
        # 定义全局默认配置模板
        default_config = {
            "show_details": True,
            "generate_image": True
        }

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 鲁棒性检查：确保所有必要字段都存在，不存在则补齐
                    for k, v in default_config.items():
                        if k not in config:
                            config[k] = v
                    return config
            except Exception as e:
                print(f"[Warning] ZWD Config load failed, using defaults: {e}")
                return default_config
        else:
            # mozial: [核心逻辑] 如果找不到文件，立即物理创建一个，实现“免封装”部署
            print(f"[*] Config file missing. Auto-generating default: {self.config_file}")
            self.app_config = default_config
            self._save_config()
            return default_config

    def _save_config(self):
        """mozial: [新增] 将内存中的配置持久化到磁盘文件"""
        import json
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.app_config, f, indent=4)
        except Exception as e:
            print(f"[Error] Failed to save ZWD config to disk: {e}")



    def _parse_float(self, s):
        """Robust float parser."""
        if not s: return 1.0
        try:
            clean_s = s.replace('V', '').replace('Sa/s', '').replace('s', '')
            val_str = clean_s.split()[-1]
            return float(val_str)
        except:
            return 1.0

    def connect(self):
        """Connect to Siglent Scope."""
        try:
            resources = self.rm.list_resources()
            target = next((r for r in resources if 'SDS' in r or 'USB' in r), None)
            if target:
                self.inst = self.rm.open_resource(target)
                self.inst.encoding = 'latin-1'
                self.inst.timeout = 60000
                try:
                    self.inst.write('*CLS')
                    self.inst.clear()
                except:
                    pass
                print(f"[SDS] Connected: {self.inst.query('*IDN?').strip()}")
                return True
            return False
        except Exception as e:
            print(f"Connect Error: {e}")
            return False

    def setup(self):
        """Configure Scope."""
        if not self.inst: return
        try:
            print(f"[Setup] Configuring Scope for {TOTAL_SCAN_TIME_MS}ms Capture...")
            self.inst.write('CH:HEAD OFF')
            
            if ENABLE_CH1:
                self.inst.write('CH1:TRA ON')
                self.inst.write('C1:PROB 10')
                self.inst.write('CH1:BWL 20M')
                self.inst.write('CH1:COUP DC')
                self.inst.write('CH1:SCAL 0.1')
                self.inst.write('CH1:OFFS 0')
            else:
                self.inst.write('CH1:TRA OFF')

            # 配置CH2采集VDDI
            if ENABLE_CH2:
                self.inst.write('CH2:TRA ON')
                self.inst.write('C2:PROB 10')
                self.inst.write('CH2:BWL 20M')
                self.inst.write('CH2:COUP DC')
                self.inst.write('CH2:SCAL 1')
                self.inst.write('CH2:OFFS -2')
            else:
                self.inst.write('CH2:TRA OFF')

            # 动态计算示波器水平时基 (默认Siglent屏幕为10格)
            time_div = (TOTAL_SCAN_TIME_MS * 1e-3) / 10.0
            time_offset = -(TOTAL_SCAN_TIME_MS * 1e-3) * 0.4  # 将触发点置于屏幕左侧40%处
            self.inst.write(f'TIM:SCAL {time_div}')
            self.inst.write(f'TIM:OFFS {time_offset}')
            self.inst.write('ACQ:MDEP 10M')

            init_trig = 0.03 * R_SHUNT
            self.inst.write('TRIG:MODE EDGE')
            self.inst.write('TRIG:EDGE:SOUR C1')
            self.inst.write(f'TRIG:EDGE:LEV {init_trig:.2f}')
            self.inst.write('TRIG:EDGE:SLOP RISE')
            self.inst.write('TRIG:SWE AUTO')
            time.sleep(1.0)
        except Exception as e:
            print(f"Setup Error: {e}")

    def fetch_waveform(self):
        """Download Waveform."""
        try:
            self.inst.write('TRIG:SWE SING')
            print(f"\nWaiting for Trigger...", end='', flush=True)

            triggered = False
            for _ in range(50):
                state = self.inst.query("INR?").strip()
                if state != "0":
                    triggered = True
                    break
                time.sleep(0.1)

            if not triggered:
                print(" [No Trig] -> Force Stop")
                self.inst.write("STOP")
            else:
                print(" [Triggered]")

            # 读取 CH1
            if ENABLE_CH1:
                self.inst.write('WAV:SOUR C1')
                self.inst.write('WAV:DATA:FMT BYTE')
                self.inst.write('WAV:POIN:MODE MAX')

                vdiv1 = self._parse_float(self.inst.query("C1:VDIV?"))
                voffset1 = self._parse_float(self.inst.query("C1:OFST?"))
                sara = self._parse_float(self.inst.query("SARA?"))

                print(f"   [Transfer] Downloading C1 data...", end='', flush=True)
                self.inst.write("WAV:DATA?")
                raw1 = self.inst.read_raw()
                print(" Done.")
            else:
                print(f"   [Transfer] C1 download skipped (disabled in config).")
                raw1 = None
                vdiv1 = 0.1
                voffset1 = 0.0
                sara = self._parse_float(self.inst.query("SARA?")) if self.inst else 250e6

            # 读取 CH2 (VDDI)
            if ENABLE_CH2:
                self.inst.write('WAV:SOUR C2')
                vdiv2 = self._parse_float(self.inst.query("C2:VDIV?"))
                voffset2 = self._parse_float(self.inst.query("C2:OFST?"))

                print(f"   [Transfer] Downloading C2 data...", end='', flush=True)
                self.inst.write("WAV:DATA?")
                raw2 = self.inst.read_raw()
                print(" Done.")
            else:
                print(f"   [Transfer] C2 download skipped (disabled in config).")
                raw2 = None
                vdiv2 = 1.0
                voffset2 = -2.0

            # 解析 CH1
            if ENABLE_CH1 and raw1 is not None and len(raw1) >= 100:
                header_len = 0
                if raw1[0:1] == b'#':
                    len_of_len = int(chr(raw1[1]))
                    header_len = 2 + len_of_len
                raw_data1 = raw1[header_len:-1]
                data_int1 = np.frombuffer(raw_data1, dtype=np.int8)
                v1 = data_int1 * (vdiv1 / 25.0) - voffset1
            else:
                # Mock CH1 current data if disabled
                if ENABLE_CH2 and raw2 is not None and len(raw2) >= 100:
                    header_len2 = 0
                    if raw2[0:1] == b'#':
                        len_of_len2 = int(chr(raw2[1]))
                        header_len2 = 2 + len_of_len2
                    pts = len(raw2[header_len2:-1])
                else:
                    pts = 100000
                v1 = np.zeros(pts)

            # 解析 CH2
            if ENABLE_CH2 and raw2 is not None and len(raw2) >= 100:
                header_len2 = 0
                if raw2[0:1] == b'#':
                    len_of_len2 = int(chr(raw2[1]))
                    header_len2 = 2 + len_of_len2

                raw_data2 = raw2[header_len2:-1]
                data_int2 = np.frombuffer(raw_data2, dtype=np.int8)
                v2 = data_int2 * (vdiv2 / 25.0) - voffset2
            else:
                # 填充默认 5.0 V 的 mock 数据，保证下游计算与绘图不崩溃
                v2 = np.full_like(v1, 5.0)

            num_points = len(v1)
            if sara <= 0: sara = 1.0
            total_time = num_points / sara
            t = np.linspace(0, total_time, num_points)

            return t, v1, v2, sara
        except Exception as e:
            print(f"\nFetch Error: {e}")
            return None, None, None, 1e9

    def _schmitt_trigger(self, y, low_thresh, high_thresh):
        """Digitalize Signal."""
        clean_sig = np.zeros_like(y, dtype=int)
        state = 0
        if y[0] > high_thresh: state = 1
        for i in range(len(y)):
            val = y[i]
            if val > high_thresh:
                state = 1
            elif val < low_thresh:
                state = 0
            clean_sig[i] = state
        return clean_sig

    def _linear_interp_val(self, t, y, target_y):
        """Find Crossing Times."""
        cross_mask = (y > target_y).astype(int)
        diffs = np.diff(cross_mask)
        idxs = np.where(diffs != 0)[0]
        t_vals = []
        slope_dir = []
        for i in idxs:
            if i + 1 < len(y):
                y0, y1 = y[i], y[i + 1]
                t0, t1 = t[i], t[i + 1]
                if y1 != y0:
                    t_interp = t0 + (target_y - y0) * (t1 - t0) / (y1 - y0)
                    t_vals.append(t_interp)
                    slope_dir.append(diffs[i])
        return np.array(t_vals), np.array(slope_dir)

    def _identify_sensor_slot(self, delay_us):
        """Time Slot Logic.
        [修改] 根据用户实测反馈，Slot 2 可能提前到 175us 附近，
        将 S1/S2 判定边界从 180us 下调至 170us。
        """
        if 20.0 < delay_us < 170.0: return 1
        if 170.0 <= delay_us < 320.0: return 2
        if 320.0 <= delay_us < 500.0: return 3
        if 500.0 <= delay_us < 700.0: return 4
        if 700.0 <= delay_us < 900.0: return 5
        return 0

    def _convert_psi5_13bit_to_hex(self, decoded_bits):
        """
        [新增] 将提取的13位PSI5电平信号转换为4位16进制数 (0xXXXX) 及 10-bit 补码十进制值
        [修改] 强校验：如果不满 13 位，直接视为残缺帧报错，拒绝解析垃圾数据！
        """
        if len(decoded_bits) != 13:
            return "ERR", "ERR", "ERR"

        bits = decoded_bits[:13]

        # ==========================================
        # 方案1：波形直译模式 (Raw Bitstream - 高位补零)
        # ==========================================
        raw_val = 0
        for bit in bits:
            raw_val = (raw_val << 1) | bit
        hex_raw = f"0x{raw_val:04X}"

        # ==========================================
        # 方案2：协议解析模式 (Payload Extraction)
        # ==========================================
        start_bits = bits[0:2]  # 通常为 [0, 0]
        data_bits = bits[2:12]  # D0 到 D9 (遵循 Bosch 规范，D0先发，即LSB)
        parity_bit = bits[12]  # P

        # 还原10位真实数据 (LSB 优先拼装)
        actual_data_val = 0
        for i in range(10):
            actual_data_val |= (data_bits[i] << i)

        # 拼装：Parity位放在第10位 (Bit 10)，低10位 (Bit 0-9) 放数据
        payload_val = (parity_bit << 10) | actual_data_val
        hex_payload = f"0x{payload_val:04X}"

        # ==========================================
        # 方案3：十进制补码映射 (Two's Complement)
        # ==========================================
        decimal_val = actual_data_val
        if actual_data_val & 0x200:  # 0b10 0000 0000 (即第 10 位为 1)
            decimal_val -= 1024

        return hex_raw, hex_payload, decimal_val

    def analyze(self, t, v1, v2, sara, sn):
        """Main Analysis."""
        if t is None: return False, [], 0.0

        # 1. Downsample
        target_sara = 20e6
        step = int(sara / target_sara)
        if step < 1: step = 1
        t_proc = t[::step]
        i_proc = (v1[::step] / R_SHUNT) * 1000.0
        sara_proc = sara / step

        # 计算 VDDI (CH2) 的平均值
        vddi_mean = np.mean(v2) if ENABLE_CH2 else "N/A"

        # 2. Global Thresholds
        g_top_pct = min(GLOBAL_TOP_CUTOFF_FACTOR * 100, 100.0)
        g_bot_pct = max(GLOBAL_BOT_CUTOFF_FACTOR * 100, 0.0)

        val_top = np.percentile(i_proc, g_top_pct)
        val_base = np.percentile(i_proc, g_bot_pct)
        amp = val_top - val_base

        print(f"   [Levels] Global Base:{val_base:.2f} Top:{val_top:.2f} Amp:{amp:.2f}")

        if amp < 2.0:
            print("   [Fail] Amp too low.")
            return False, [], 0.0

        threshold_2 = val_base + THRESHOLD_2_FACTOR * amp

        # 3. Burst Detection
        binary = (i_proc > threshold_2).astype(int)

        # mozial: [核心改动] 物理层：双极性串扰尖峰滤波器 (Bipolar Noise Cancellation)
        # 响应逻辑："如果出现相对base上去再下来到base再下去的情况，过滤掉第一个上去"
        # 目的：阻断前端窄带毛刺与真实波形的桥接效应，防止 start 误判提前。
        diff_b = np.diff(np.concatenate(([0], binary, [0])))
        up_edges = np.where(diff_b == 1)[0]
        down_edges = np.where(diff_b == -1)[0]

        dip_search_pts = int(3.0e-6 * sara_proc)  # 高电平结束后向下探测 3us
        dip_threshold = val_base - 1.0  # 深度下穿阈值(比基线低1mA即视为"再下去")

        for u, d in zip(up_edges, down_edges):
            pulse_width_us = (d - u) / sara_proc * 1e6
            # 物理约束：真正的Sync或数据脉冲较宽，只有极窄的(<2.5us)才去核对双极性特征
            if pulse_width_us < 2.5:
                search_end = min(len(i_proc), d + dip_search_pts)
                # 检查是否命中特征："上去再瞬间深度下去"
                if d < search_end and np.min(i_proc[d:search_end]) < dip_threshold:
                    # 确认为双极性尖峰，抹除这个虚假的"第一个上去"
                    binary[u:d] = 0

        # 基于过滤后干净的 binary 重新提取索引
        high_indices = np.where(binary == 1)[0]

        if len(high_indices) < 10:
            self._plot_final(zoom_t=np.array([]), zoom_i=np.array([]),
                             peak=val_top, base=val_base, viz={}, sn=sn, success=False)
            return False, [], 0.0

        max_gap_pts = int(12e-6 * sara_proc)
        bursts = []
        current_burst = [high_indices[0]]
        for k in range(1, len(high_indices)):
            if high_indices[k] - high_indices[k - 1] < max_gap_pts:
                current_burst.append(high_indices[k])
            else:
                bursts.append(current_burst)
                current_burst = [high_indices[k]]
        bursts.append(current_burst)

        # 4. Sync Logic
        sync_bursts = []
        for i, burst in enumerate(bursts):
            dur_us = (burst[-1] - burst[0]) / sara_proc * 1e6
            if SYNC_WIDTH_MIN < dur_us < SYNC_WIDTH_MAX:
                sync_bursts.append((burst, i))

        if len(sync_bursts) < 1:
            print(f"   [Fail] No Sync found.")
            self._plot_final(zoom_t=np.array([]), zoom_i=np.array([]),
                             peak=val_top, base=val_base, viz={}, sn=sn, success=False)
            return False, [], 0.0

        sync1_burst, sync1_idx = sync_bursts[0]
        sync1_start = t_proc[sync1_burst[0]]
        sync1_end = t_proc[sync1_burst[-1]]

        sync2_start = None
        sync2_burst = None
        if len(sync_bursts) > 1:
            sync2_burst, _ = sync_bursts[1]
            sync2_start = t_proc[sync2_burst[0]]

        tCycle = (sync2_start - sync1_start) * 1e6 if sync2_start else 0.0

        # 5. Sensor Search
        win_end_idx = sync1_burst[-1] + int(SENSOR_SEARCH_WINDOW * 1e-6 * sara_proc)
        candidate_bursts = []
        for i in range(sync1_idx + 1, len(bursts)):
            b = bursts[i]
            if b[0] > win_end_idx: break
            if sync2_burst and b[0] >= sync2_burst[0]: break
            if ((b[-1] - b[0]) / sara_proc * 1e6) > SENSOR_BURST_MIN_WIDTH_US:
                candidate_bursts.append(b)

        # 6. Analyze Sensors
        sensor_reports = []
        boundaries = []
        boundaries.append(("Sync1", sync1_start, sync1_end))
        if sync2_burst: boundaries.append(("Sync2", sync2_start, t_proc[sync2_burst[-1]]))

        raw_zoom_s = sync1_burst[0] * step
        raw_zoom_e = sync2_burst[-1] * step if sync2_burst else raw_zoom_s + int(3e-3 * sara)

        margin = int(20e-6 * sara)
        s_g = max(0, raw_zoom_s - margin)
        e_g = min(len(v1), min(raw_zoom_e + margin, len(v1) - 1))
        zoom_t_global = t[s_g:e_g]
        zoom_i_global = (v1[s_g:e_g] / R_SHUNT) * 1000.0

        prev_sensor_end_us = 0
        viz_data = {"boundaries": boundaries, "vddi_avg": vddi_mean}

        for burst in candidate_bursts:
            raw_s = burst[0] * step
            raw_e = burst[-1] * step
            t_start, t_end = t[raw_s], t[raw_e]

            # Slot ID
            delay_us = (t_start - sync1_end) * 1e6
            s_id = self._identify_sensor_slot(delay_us)
            if s_id == 0: continue

            boundaries.append((f"S{s_id}", t_start, t_end))

            # High Res Extraction
            s_loc = max(0, raw_s - int(10e-6 * sara))
            e_loc = min(len(v1), raw_e + int(10e-6 * sara))
            sens_t = t[s_loc:e_loc]
            sens_i = (v1[s_loc:e_loc] / R_SHUNT) * 1000.0

            # ====================================================================
            # mozial: [核心重构] 物理边界界定法：引入抗脉冲噪声装甲 (Median Filter)
            # 采用 0.8us 的中值滤波窗口，铲平一切穿透阈值的窄带毛刺，为 50% 锚点搜索与门限计算提供无菌物理拓扑
            # ====================================================================
            from scipy.signal import medfilt
            kernel_pts = int(0.8e-6 * sara)
            if kernel_pts % 2 == 0: kernel_pts += 1
            if kernel_pts < 3: kernel_pts = 3

            # 仅用于时序锚点搜索和门限求取的净化波形，原波形(sens_i)保留用于后续的 Rise/Fall 上升下降沿斜率计算
            sens_i_clean = medfilt(sens_i, kernel_pts)

            l_top_pct = min(LOCAL_TOP_CUTOFF_FACTOR * 100, 100.0)
            l_bot_pct = max(LOCAL_BOT_CUTOFF_FACTOR * 100, 0.0)

            # [恢复局部计算并优化] 使用经过中值滤波的干净波形求取局部最高值与最低值
            # 既保证了局部波形贴合度（解决图2显示偏离问题），又防止了高频毛刺导致的数据异常
            bottom_current = np.percentile(sens_i_clean, l_bot_pct)
            local_top = np.percentile(sens_i_clean, l_top_pct)
            local_amp = local_top - bottom_current

            # 使用全局定义的阈值因子计算局部门限
            local_lvl_20 = bottom_current + LVL_20_FACTOR * local_amp
            local_lvl_80 = bottom_current + LVL_80_FACTOR * local_amp
            local_threshold = bottom_current + LVL_50_FACTOR * local_amp

            # 1. 提取基础 Schmitt 触发点 (0或1) - 使用净化后的波形
            raw_dig = self._schmitt_trigger(sens_i_clean, local_lvl_20, local_lvl_80)

            # 2. 状态机防抖：电平必须稳定维持至少 1.5us，确认这是一个真实的宏观边沿
            min_steady_pts = int(1.5e-6 * sara)
            debounced_dig = np.zeros_like(raw_dig)

            current_valid_state = raw_dig[0]
            candidate_state = raw_dig[0]
            steady_count = 0

            for i in range(len(raw_dig)):
                if raw_dig[i] == candidate_state:
                    steady_count += 1
                    if steady_count >= min_steady_pts:
                        current_valid_state = candidate_state
                else:
                    candidate_state = raw_dig[i]
                    steady_count = 1

                debounced_dig[i] = current_valid_state

            # 3. 提取防抖后干净的宏观边沿
            edges = np.diff(debounced_dig)
            raw_valid_idxs = np.where(edges != 0)[0]

            # mozial: 增添时域脉宽对消逻辑，剔除所有脉宽小于 2.5us 的非法深度毛刺干扰
            # 任何小于此宽度的电平翻转违背曼彻斯特底线，绝对是噪声
            min_valid_pulse_pts = int(2.5e-6 * sara)
            clean_valid_idxs = []
            skip_next = False

            for i in range(len(raw_valid_idxs)):
                if skip_next:
                    skip_next = False
                    continue

                if i < len(raw_valid_idxs) - 1:
                    pts_diff = raw_valid_idxs[i + 1] - raw_valid_idxs[i]
                    if pts_diff < min_valid_pulse_pts:
                        # 这是一个穿透阈值的非法短脉冲（毛刺），无视这对假边沿，让它们双双同归于尽
                        skip_next = True
                        continue

                clean_valid_idxs.append(raw_valid_idxs[i])

            valid_idxs = clean_valid_idxs

            clean_t50, clean_slopes = [], []

            # 4. 精准寻找 50% 锚点：只在确定的 20% ~ 80% 窗口内内插，无视全图毛刺
            # mozial: 修改开仓逻辑/解析逻辑，废除硬编码的魔法时间偏移，使用严格的电平遍历寻找绝对的物理 k_start 和 k_end
            # mozial: 增加寻找距离的超时死锁机制，限制最大查找宽度，防止被残存畸变波形拖拽
            # mozial: 全面切换至 sens_i_clean，防止搜索指针滑入未经处理的瞬态极窄尖峰坑洞中
            max_edge_search_pts = int(2.5e-6 * sara)

            for idx in valid_idxs:
                direction = edges[idx]  # 1: 上升, -1: 下降

                # 防抖确认点是在真实跳变发生后的 min_steady_pts 处
                # 所以我们从防抖确认点往回找真实跳变区间
                search_anchor = idx
                k_start = -1
                k_end = -1

                if direction == 1:  # 寻找上升沿区间
                    # 从确认点往回找，直到低于 20% 获得准确起点
                    curr_k = search_anchor
                    pts_searched = 0
                    while curr_k > 0 and sens_i_clean[curr_k] > local_lvl_20 and pts_searched < max_edge_search_pts:
                        curr_k -= 1
                        pts_searched += 1
                    k_start = curr_k

                    # 从 20% 确切起点往后找，直到高于 80% 获得确切终点
                    curr_k = k_start
                    pts_searched = 0
                    while curr_k < len(sens_i_clean) - 1 and sens_i_clean[
                        curr_k] < local_lvl_80 and pts_searched < max_edge_search_pts:
                        curr_k += 1
                        pts_searched += 1
                    k_end = curr_k

                else:  # 寻找下降沿区间
                    # 从确认点往回找，直到高于 80% 获得准确起点
                    curr_k = search_anchor
                    pts_searched = 0
                    while curr_k > 0 and sens_i_clean[curr_k] < local_lvl_80 and pts_searched < max_edge_search_pts:
                        curr_k -= 1
                        pts_searched += 1
                    k_start = curr_k

                    # 从 80% 确切起点往后找，直到低于 20% 获得确切终点
                    curr_k = k_start
                    pts_searched = 0
                    while curr_k < len(sens_i_clean) - 1 and sens_i_clean[
                        curr_k] > local_lvl_20 and pts_searched < max_edge_search_pts:
                        curr_k += 1
                        pts_searched += 1
                    k_end = curr_k

                # mozial: 安全校验，确保找到的区间有效，严格在这个干净的物理区间内求取 50%
                if k_start >= 0 and k_end < len(sens_i_clean) and k_start < k_end:
                    valid_t50 = None
                    for k in range(k_start, k_end):
                        if (sens_i_clean[k] <= local_threshold < sens_i_clean[k + 1]) or (
                                sens_i_clean[k] >= local_threshold > sens_i_clean[k + 1]):
                            t0, t1 = sens_t[k], sens_t[k + 1]
                            y0, y1 = sens_i_clean[k], sens_i_clean[k + 1]
                            if y1 != y0:
                                valid_t50 = t0 + (local_threshold - y0) * (t1 - t0) / (y1 - y0)
                            else:
                                valid_t50 = t0
                            break

                    if valid_t50 is not None:
                        # 确保物理极性严格交替
                        if len(clean_slopes) == 0 or direction != clean_slopes[-1]:
                            clean_t50.append(valid_t50)
                            clean_slopes.append(direction)

            clean_t50 = np.array(clean_t50)
            clean_slopes = np.array(clean_slopes)
            rise_anchors = clean_t50[clean_slopes == 1]
            fall_anchors = clean_t50[clean_slopes == -1]

            # Rise / Fall Calc - 依然使用含有高频细节的原生波形 sens_i 计算斜率
            sg_window = int(1.0e-6 * sara)
            if sg_window % 2 == 0: sg_window += 1
            if sg_window < 5: sg_window = 5

            rise_durs = []
            for r_t in rise_anchors:
                mask = (sens_t > r_t - 2e-6) & (sens_t < r_t + 2e-6)
                t_sub, i_sub = sens_t[mask], sens_i[mask]
                if len(i_sub) > sg_window:
                    i_sub_smooth = savgol_filter(i_sub, sg_window, 3)
                else:
                    i_sub_smooth = i_sub

                t20_l, _ = self._linear_interp_val(t_sub, i_sub_smooth, local_lvl_20)
                t80_l, _ = self._linear_interp_val(t_sub, i_sub_smooth, local_lvl_80)
                prev_20 = t20_l[t20_l < r_t]
                next_80 = t80_l[t80_l > r_t]
                if len(prev_20) > 0 and len(next_80) > 0:
                    rise_durs.append((next_80[0] - prev_20[-1]) * 1e9)

            fall_durs = []
            for f_t in fall_anchors:
                mask = (sens_t > f_t - 2e-6) & (sens_t < f_t + 2e-6)
                t_sub, i_sub = sens_t[mask], sens_i[mask]
                if len(i_sub) > sg_window:
                    i_sub_smooth = savgol_filter(i_sub, sg_window, 3)
                else:
                    i_sub_smooth = i_sub

                t80_l, _ = self._linear_interp_val(t_sub, i_sub_smooth, local_lvl_80)
                t20_l, _ = self._linear_interp_val(t_sub, i_sub_smooth, local_lvl_20)
                prev_80 = t80_l[t80_l < f_t]
                next_20 = t20_l[t20_l > f_t]
                if len(prev_80) > 0 and len(next_20) > 0:
                    fall_durs.append((next_20[0] - prev_80[-1]) * 1e9)

            # ====================================================================
            # 工业级 PLL 曼彻斯特解码：时间窗自适应追踪法
            # ====================================================================
            mid_edges = []
            decoded_bits = []

            if len(clean_t50) >= 2:
                # 1. 锁定 Start Bit (0) 的中心上升沿
                first_rise_idx = -1
                for i in range(min(5, len(clean_t50))):
                    if clean_slopes[i] == 1:
                        first_rise_idx = i
                        break

                if first_rise_idx != -1:
                    mid_edges.append(clean_t50[first_rise_idx])
                    decoded_bits.append(0)

                    T_est = 8.0e-6
                    current_expected = mid_edges[-1] + T_est

                    # 2. 追踪后续 12 个 Bit
                    for _ in range(12):
                        best_idx = -1
                        min_err = 9999.0

                        for i in range(first_rise_idx + 1, len(clean_t50)):
                            t_edge = clean_t50[i]
                            err = abs(t_edge - current_expected)

                            if err < 2.5e-6:
                                if err < min_err:
                                    min_err = err
                                    best_idx = i

                        if best_idx != -1:
                            actual_time = clean_t50[best_idx]
                            slope = clean_slopes[best_idx]

                            mid_edges.append(actual_time)
                            decoded_bits.append(0 if slope == 1 else 1)

                            T_est = actual_time - mid_edges[-2]
                            current_expected = actual_time + T_est
                            first_rise_idx = best_idx
                        else:
                            break

            estimated_bits = []
            if len(mid_edges) > 1:
                estimated_bits = list(np.diff(mid_edges) * 1e6)

            tbit_avg = np.mean(estimated_bits) if len(estimated_bits) > 0 else 0.0

            hex_raw, hex_payload, decimal_val = self._convert_psi5_13bit_to_hex(decoded_bits)

            # --- [核心重构] Duty Cycle (纯高电平脉宽统计法) ---
            duty_cycle = 0.0
            bit_duty_cycles = []
            if len(clean_t50) > 1 and tbit_avg > 0:
                for i in range(len(clean_t50) - 1):
                    # 严格限定：只计算从 上升沿(1) 到 下降沿(-1) 的高电平脉宽
                    if clean_slopes[i] == 1 and clean_slopes[i + 1] == -1:
                        t_high = clean_t50[i + 1] - clean_t50[i]
                        # 曼彻斯特编码的有效高电平半脉宽应在 2.5us ~ 5.5us 之间
                        if 2.5e-6 < t_high < 5.5e-6:
                            bit_duty_cycles.append((t_high / (tbit_avg * 1e-6)) * 100.0)

                if len(bit_duty_cycles) > 0:
                    duty_cycle = np.mean(bit_duty_cycles)

            # --- Calculations using fixed Bit Time ---
            t_start_rel = (t_start - sync1_end) * 1e6
            t_end_rel = (t_end - sync1_end) * 1e6
            t_frame = t_end_rel - t_start_rel
            t_gap = t_start_rel - prev_sensor_end_us if prev_sensor_end_us > 0 else 0
            prev_sensor_end_us = t_end_rel

            drift_frame = 0.0
            drift_time_val = None

            if len(estimated_bits) > 0 and tbit_avg > 0:
                bit_max = np.max(estimated_bits)
                bit_min = np.min(estimated_bits)
                max_abs_dev = max(abs(bit_max - tbit_avg), abs(bit_min - tbit_avg))
                drift_frame = (max_abs_dev / tbit_avg) * 100.0

            if s_id == 1 and tbit_avg > 0:
                ct = time.time()
                cf = 1.0 / (tbit_avg * 1e-6)
                if self.prev_s1_time is not None:
                    dt = ct - self.prev_s1_time
                    if dt > 0.05:
                        drift_time_val = abs((cf - self.prev_s1_freq) / self.prev_s1_freq * 100.0 / dt)
                self.prev_s1_time = ct
                self.prev_s1_freq = cf

            rpt = {
                "id": s_id,
                "local_amp": local_amp,
                "rise_list": rise_durs,
                "fall_list": fall_durs,
                "bit_list": estimated_bits,
                "drift_frame": drift_frame,
                "drift_time": drift_time_val,
                "duty_cycle_list": bit_duty_cycles,
                "duty_cycle": duty_cycle,
                "tbit_avg": tbit_avg,
                "start_us": t_start_rel,
                "end_us": t_end_rel,
                "t_frame": t_frame,
                "t_gap": t_gap,
                "t_cycle": tCycle,
                "mid_edges": mid_edges,
                "decoded_bits": decoded_bits,
                "is_valid_frame": (len(decoded_bits) == 13),
                "hex_raw": hex_raw,
                "hex_payload": hex_payload,
                "decimal_val": decimal_val,
                "abs_t_start": t_start,
                "abs_t_end": t_end,
                "sens_t": sens_t,
                "sens_i": sens_i,
                "s_top": local_top,
                "s_bot": bottom_current,
                "s_lvl20": local_lvl_20,
                "s_lvl80": local_lvl_80,
                "global_base": val_base
            }
            sensor_reports.append(rpt)

        sensor_reports.sort(key=lambda x: x['id'])
        viz_data["reports"] = sensor_reports

        self._plot_final(zoom_t=zoom_t_global, zoom_i=zoom_i_global,
                         peak=val_top, base=val_base, viz=viz_data, sn=sn, success=True)

        return True, sensor_reports, vddi_mean

    def _plot_final(self, zoom_t, zoom_i, peak, base, viz, sn, success):
        reports = viz.get("reports", [])
        boundaries = viz.get("boundaries", [])
        vddi_avg = viz.get("vddi_avg", 0.0)

        # 动态生成子图
        num_sensors = len(reports) if success else 0
        total_plots = num_sensors + 1 if num_sensors > 0 else 2

        fig, axes = plt.subplots(total_plots, 1, figsize=(16, 10 + 10 * num_sensors))
        if total_plots == 1:
            axes = [axes]
        elif not isinstance(axes, np.ndarray):
            axes = [axes]

        ax_zoom = axes[0]

        print("\n" + "=" * 60)
        print(f" PSI5 COMPLIANCE REPORT ({sn})")
        print("=" * 60)
        vddi_avg_str = f"{vddi_avg:.3f} V" if isinstance(vddi_avg, float) else str(vddi_avg)
        print(f"[*] VDDI Average (CH2): {vddi_avg_str}")

        # ANSI Colors
        G, R, S = "\033[92m", "\033[91m", "\033[0m"

        def check(val, low, high, decimals=1):
            return f"{G}PASS{S}" if low <= round(val, decimals) <= high else f"{R}FAIL{S}"

        def check_lt(val, high, decimals=3):
            return f"{G}PASS{S}" if round(val, decimals) < high else f"{R}FAIL{S}"

        for r in reports:
            # 数据预处理
            rise_mean = np.mean(r['rise_list']) if r['rise_list'] else 0.0
            fall_mean = np.mean(r['fall_list']) if r['fall_list'] else 0.0
            str_rise = "[" + ", ".join([f"{v:.1f}" for v in r['rise_list']]) + "]" if r['rise_list'] else "[]"
            str_fall = "[" + ", ".join([f"{v:.1f}" for v in r['fall_list']]) + "]" if r['fall_list'] else "[]"
            str_bit = "[" + ", ".join([f"{v:.3f}" for v in r['bit_list']]) + "]" if r['bit_list'] else "[]"

            # Slot Time Criteria mapping
            s_limits = {
                1: {"s_min": 44.1, "s_max": 55.9, "e_min": 143.7, "e_max": 165.1},
                2: {"s_min": 181.6, "s_max": 206.6, "e_min": 281.2, "e_max": 315.8},
                3: {"s_min": 329.7, "s_max": 369.0, "e_min": 429.3, "e_max": 478.1},
            }
            lim = s_limits.get(r['id'], {"s_min": 0, "s_max": 9999, "e_min": 0, "e_max": 9999})

            # --- [新增] 全局 PASS/FAIL 判定逻辑 ---
            is_pass = True
            if not (4.0 <= round(r['global_base'], 2) <= 12.0): is_pass = False
            if not (22.0 <= round(r['local_amp'], 2) <= 30.0): is_pass = False
            if not (350 <= round(rise_mean, 1) <= 600): is_pass = False
            if not (350 <= round(fall_mean, 1) <= 600): is_pass = False
            if not (7.6 <= round(r['tbit_avg'], 3) <= 8.4): is_pass = False
            if round(r['drift_frame'], 3) >= 1.0: is_pass = False
            if not (49.0 <= round(r['duty_cycle'], 1) <= 51.0): is_pass = False
            if not (lim['s_min'] <= round(r['start_us'], 1) <= lim['s_max']): is_pass = False
            if not (lim['e_min'] <= round(r['end_us'], 1) <= lim['e_max']): is_pass = False
            if not (495.0 <= round(r['t_cycle'], 1) <= 505.0): is_pass = False
            if not r['is_valid_frame']: is_pass = False
            
            decimal_val = r.get('decimal_val', -1)
            if isinstance(decimal_val, (int, float)) and decimal_val > 480:
                is_pass = False

            status_str = f"{G}PASS{S}" if is_pass else f"{R}FAIL{S}"

            print(f"\n[ SENSOR {r['id']} ] - OVERALL STATUS: {status_str}")
            print(f"{'TEST ITEM':<32} | {'ACTUAL':<12} | {'CRITERIA':<22} | {'RESULT'}")
            print("-" * 88)

            # --- PART 1: PHYSICAL LAYER ---
            print(
                f"{'0. Base Current (mA)':<32} | {r['global_base']:<12.2f} | {'4.0 ~ 12.0':<22} | {check(r['global_base'], 4.0, 12.0, 2)}")
            print(
                f"{'1. Sink Current (mA)':<32} | {r['local_amp']:<12.2f} | {'22.0 ~ 30.0':<22} | {check(r['local_amp'], 22.0, 30.0, 2)}")
            print(
                f"{'2. Sink Rise Mean (ns)':<32} | {rise_mean:<12.1f} | {'350 ~ 600':<22} | {check(rise_mean, 350, 600, 1)}")

            # mozial: 根据隐藏配置控制详情输出
            if self.app_config.get('show_details', True):
                print(f"   >> Detail: {str_rise}")

            print(
                f"{'3. Sink Fall Mean (ns)':<32} | {fall_mean:<12.1f} | {'350 ~ 600':<22} | {check(fall_mean, 350, 600, 1)}")

            # mozial: 根据隐藏配置控制详情输出
            if self.app_config.get('show_details', True):
                print(f"   >> Detail: {str_fall}")

            print(
                f"{'4. Bit Time Avg 125k (us)':<32} | {r['tbit_avg']:<12.3f} | {'7.600 ~ 8.400':<22} | {check(r['tbit_avg'], 7.6, 8.4, 3)}")

            # mozial: 根据隐藏配置控制详情输出
            if self.app_config.get('show_details', True):
                print(f"   >> Detail: {str_bit}")

            print(f"{'4.2 Bit Time 189k (us)':<32} | {'N/A':<12} | {'N/A':<22} | SKIP")
            print(
                f"{'5. Max Drift Rate (%/Frame)':<32} | {r['drift_frame']:<12.3f} | {'< 1.000':<22} | {check_lt(r['drift_frame'], 1.0, 3)}")
            print(
                f"{'6. Duty Cycle Mean (%)':<32} | {r['duty_cycle']:<12.1f} | {'49.0 ~ 51.0':<22} | {check(r['duty_cycle'], 49.0, 51.0, 1)}")

            if r['duty_cycle_list'] and self.app_config.get('show_details', True):
                dc_str = ", ".join([f"{val:.1f}%" for val in r['duty_cycle_list']])
                print(f"   >> Duty Cycle Details: [{dc_str}]")

            # --- PART 2: PROTOCOL LAYER ---
            s_crit = f"{lim['s_min']} ~ {lim['s_max']}"
            e_crit = f"{lim['e_min']} ~ {lim['e_max']}"
            print(
                f"{'7. Start Time tDelay (us)':<32} | {r['start_us']:<12.1f} | {s_crit:<22} | {check(r['start_us'], lim['s_min'], lim['s_max'], 1)}")
            print(
                f"{'8. End Time (us)':<32} | {r['end_us']:<12.1f} | {e_crit:<22} | {check(r['end_us'], lim['e_min'], lim['e_max'], 1)}")
            print(f"{'9. Frame Time tFrame (us)':<32} | {r['t_frame']:<12.1f} | {'N/A':<22} | SKIP")
            print(
                f"{'10. Cycle Time tCycle (us)':<32} | {r['t_cycle']:<12.1f} | {'495.0 ~ 505.0':<22} | {check(r['t_cycle'], 495.0, 505.0, 1)}")

            # --- PART 3: DATA PAYLOAD ---
            print("--- DATA PAYLOAD ---")
            if not r['is_valid_frame']:
                print(f"{R}[ERROR]{S} Decoded Bits (13-bit): {r['decoded_bits']} (Length {len(r['decoded_bits'])})")
            else:
                print(f"11. Decoded Bits (13-bit): {r['decoded_bits']}")
            print(f"12. HEX (Raw Waveform):    {r.get('hex_raw', 'N/A')}")
            print(f"13. HEX (Sensor Payload):  {r.get('hex_payload', 'N/A')}")
            dec_val = r.get('decimal_val', 'N/A')
            if isinstance(dec_val, (int, float)) and dec_val > 480:
                print(f"14. Decimal Value (10b):   {R}{dec_val} (FAIL > 480){S}")
            else:
                print(f"14. Decimal Value (10b):   {G}{dec_val}{S}")
            print("-" * 75)

        # Plot 1: Cycle Zoom Window
        if success and len(zoom_t) > 0:
            z_t_us = (zoom_t - zoom_t[0]) * 1e6
            ax_zoom.plot(z_t_us, zoom_i, color='#2244bb', lw=1.0)
            t_offset = zoom_t[0]

            for label, ts, te in boundaries:
                ts_rel = (ts - t_offset) * 1e6
                te_rel = (te - t_offset) * 1e6
                col = 'darkred' if "Sync" in label else 'blue'
                ax_zoom.axvline(ts_rel, color='k', ls='--', lw=1.5)
                ax_zoom.axvline(te_rel, color='k', ls=':', lw=1.0)
                mid = (ts_rel + te_rel) / 2
                ax_zoom.text(mid, peak + 2, label, ha='center', color=col, fontweight='bold')

            ax_zoom.axhline(base, color='orange', ls=':', lw=2.5, alpha=0.9, label='Global Base')

            for idx, r in enumerate(reports):
                start_rel_us = (r['abs_t_start'] - t_offset) * 1e6
                end_rel_us = (r['abs_t_end'] - t_offset) * 1e6
                label_top = 'Local Top' if idx == 0 else ""
                label_bot = 'Local Base' if idx == 0 else ""
                ax_zoom.hlines(r['s_top'], start_rel_us, end_rel_us, color='g', linestyles='--', lw=2.5,
                               label=label_top)
                ax_zoom.hlines(r['s_bot'], start_rel_us, end_rel_us, color='b', linestyles='--', lw=2.5,
                               label=label_bot)

            ax_zoom.set_title(f"Cycle Zoom (Sync 1 -> Sync 2)")
            ax_zoom.set_xlabel("Time (us)")
            ax_zoom.set_ylabel("Current (mA)")
            ax_zoom.legend(loc='upper right')
            ax_zoom.grid(True)
        else:
            ax_zoom.text(0.5, 0.5, "No Data", ha='center')

        # Plot N: Sensor Specific Bit Details
        if success and num_sensors > 0:
            for idx, r in enumerate(reports):
                ax_bit = axes[idx + 1]
                b_t_us = (r['sens_t'] - r['sens_t'][0]) * 1e6
                bit_i = r['sens_i']

                ax_bit.plot(b_t_us, bit_i, 'o', color='purple', markersize=2, alpha=0.4)
                ax_bit.plot(b_t_us, bit_i, '-', color='purple', lw=1.2, alpha=0.8)

                t_offset_bit = r['sens_t'][0]
                for edge, bit in zip(r.get("mid_edges", []), r.get("decoded_bits", [])):
                    edge_rel = (edge - t_offset_bit) * 1e6
                    if 0 <= edge_rel <= (r['sens_t'][-1] - r['sens_t'][0]) * 1e6:
                        ax_bit.axvline(edge_rel, color='m', ls='-.', lw=1.5, alpha=0.8)
                        ax_bit.text(edge_rel, r['s_top'] + 4, str(bit), color='m', ha='center', fontsize=14,
                                    fontweight='bold')

                ax_bit.axhline(r['s_top'], color='g', ls='--', lw=2.5, alpha=0.9,
                               label=f"Top Current ({r['s_top']:.1f}mA)")
                ax_bit.axhline(r['s_lvl80'], color='r', ls=':', lw=3.0, alpha=0.9,
                               label=f"80% Level ({r['s_lvl80']:.1f}mA)")
                ax_bit.axhline(r['s_lvl20'], color='orange', ls=':', lw=3.0, alpha=0.9,
                               label=f"20% Level ({r['s_lvl20']:.1f}mA)")
                ax_bit.axhline(r['s_bot'], color='b', ls='--', lw=2.5, alpha=0.9,
                               label=f"Bottom Current ({r['s_bot']:.1f}mA)")

                ax_bit.legend(loc='upper right')
                ax_bit.set_title(f"Full 13-bit Sensor Response Detail (Slot {r['id']})")
                ax_bit.set_xlabel("Time (us)")
                ax_bit.set_ylabel("Current (mA)")
                ax_bit.grid(True)
        elif not success:
            axes[1].text(0.5, 0.5, "Extraction Failed", ha='center')

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, f"PSI5_FT_Elec_Para_{sn}.jpg")

        # mozial: 根据隐藏配置决定是否生成并保存图片
        if self.app_config.get('generate_image', True):
            plt.savefig(filepath, dpi=120, format='jpeg', bbox_inches='tight')
            print(f"Report Generated: {filepath}")
        else:
            print(f"   [Config] Image generation skipped per configuration.")

        plt.close('all')
        import gc
        gc.collect()

    def save_to_csv(self, dut_name, reports, vddi):
        """
        [修改] 将生成的CSV文件保存到专门的目录下，以 psi5_results_器件号.csv 命名
        """
        filename = os.path.join(self.output_dir, f"psi5_results_{dut_name}.csv")
        file_exists = os.path.isfile(filename)

        with open(filename, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "DUT", "Sensor_ID", "VDDI_Avg (V)",
                    "Base Current (mA)", "Sink Current (mA)", # 新增 Base Current
                    "Sink Rise Mean (ns)", "Sink Rise Details (ns)",
                    "Sink Fall Mean (ns)", "Sink Fall Details (ns)",
                    "Bit Time Avg 125k (us)", "Bit Time Details (us)",
                    "Max Clock Drift Rate (During Frame %)", # 修改表头名
                    "Duty Cycle Per Bit (%)", "Duty Cycle Mean (%)",
                    "Start Time tDelay (us)", "End Time (us)",
                    "Frame Time tFrame (us)", "Cycle Time tCycle (us)",
                    "Decoded Bits", "Valid Frame", "HEX (Raw)", "HEX (Payload)", "Decimal Value",
                    "Zero_Bias_Range", "Zero_Bias_Span", "Zero_Bias_Mean"
                ])

            for r in reports:
                rise_mean = f"{np.mean(r['rise_list']):.1f}" if r['rise_list'] else "N/A"
                fall_mean = f"{np.mean(r['fall_list']):.1f}" if r['fall_list'] else "N/A"

                str_rise = "[" + ", ".join([f"{v:.1f}" for v in r['rise_list']]) + "]" if r['rise_list'] else "[]"
                str_fall = "[" + ", ".join([f"{v:.1f}" for v in r['fall_list']]) + "]" if r['fall_list'] else "[]"
                str_bit = "[" + ", ".join([f"{v:.3f}" for v in r['bit_list']]) + "]" if r['bit_list'] else "[]"
                str_dc = "[" + ", ".join([f"{v:.1f}" for v in r['duty_cycle_list']]) + "]" if r[
                    'duty_cycle_list'] else "[]"
                str_bits = "[" + ", ".join([str(b) for b in r['decoded_bits']]) + "]"

                writer.writerow([
                    dut_name,
                    str(r['id']),
                    f"{vddi:.3f}" if isinstance(vddi, float) else str(vddi),
                    f"{r['global_base']:.2f}",   # Base Current
                    f"{r['local_amp']:.2f}", # Sink Current
                    rise_mean,
                    str_rise,
                    fall_mean,
                    str_fall,
                    f"{r['tbit_avg']:.3f}",
                    str_bit,
                    f"{r['drift_frame']:.3f}", # 写入展示名对应的 drift_frame
                    str_dc,
                    f"{r['duty_cycle']:.1f}",
                    f"{r['start_us']:.1f}",
                    f"{r['end_us']:.1f}",
                    f"{r['t_frame']:.1f}",
                    f"{r['t_cycle']:.1f}",
                    str_bits,
                    "YES" if r['is_valid_frame'] else "NO",
                    r.get('hex_raw', 'N/A'),
                    r.get('hex_payload', 'N/A'),
                    r.get('decimal_val', 'N/A'),
                    "N/A",  # Zero_Bias_Range
                    "N/A",  # Zero_Bias_Span
                    "N/A"   # Zero_Bias_Mean
                ])
        print(f"   [CSV] Full Details appended to {filename} for DUT: {dut_name}")

    def run(self, dut_name):
        t, v1, v2, s = self.fetch_waveform()
        if t is not None and v2 is not None:
            success, reports, vddi = self.analyze(t, v1, v2, s, dut_name)
            if success:
                self.save_to_csv(dut_name, reports, vddi)


# mozial: 优化 main 模块以支持 CLI 封装
# 遵循原则：以复用现有为荣，以寻求确认为荣。

if __name__ == "__main__":
    import argparse

    # 使用 argparse 增强 CLI 交互
    parser = argparse.ArgumentParser(description='PSI5 Decoder CLI Tool')
    parser.add_argument('--name', type=str, default='', help='DUT Name')
    parser.add_argument('--setup', action='store_true', help='Run scope setup')
    parser.add_argument('--outdir', type=str, default='', help='Override output directory')
    args = parser.parse_args()

    task = SDS_Frame_Validator()
    if args.outdir:
        # Override output directory if specified by the caller
        task.output_dir = os.path.abspath(args.outdir)
        if not os.path.exists(task.output_dir):
            os.makedirs(task.output_dir, exist_ok=True)
        print(f"[*] Output Directory Overridden: {task.output_dir}")
    if task.connect():
        if args.setup:
            task.setup()

        # 封装后支持直接从命令行参数获取 DUT 名，便于自动化机台调用
        if args.name:
            task.run(args.name)
        else:
            # 原有的交互模式保持不变，保留之前注释
            while True:
                print("-" * 60)
                sys.stdout.flush()
                # 保留所有之前注释
                dut_in = input("\n请输入待测器件号(直接按 Enter 默认 DUT_Test，输入 q 退出): ").strip()

                if dut_in.lower() == 'q':
                    print("Exit Testing.")
                    break

                # mozial: [新增] 隐藏配置模式入口
                if dut_in == 'zwd':
                    while True:
                        print("\n" + "=" * 40)
                        print(" [ZWD 隐藏配置模式] - mozial")
                        print("=" * 40)
                        print(f"1. 显示参数详情 (show_details):   {task.app_config.get('show_details', True)}")
                        print(f"2. 渲染导出图片 (generate_image): {task.app_config.get('generate_image', True)}")
                        print("-" * 40)
                        print("指令说明: ")
                        print(" -> 输入 '1 false' 关闭显示详情，'1 true' 开启。")
                        print(" -> 输入 '2 false' 关闭生成图片，'2 true' 开启。")
                        print(" -> 输入 'q' 保存并退出配置模式。")

                        cmd = input("\nZWD> ").strip().lower()
                        if cmd == 'q':
                            print("[ZWD] 配置已保存，返回主测试模式。")
                            break

                        parts = cmd.split()
                        if len(parts) == 2:
                            key_idx = parts[0]
                            val_str = parts[1]
                            val_bool = True if val_str == 'true' else (False if val_str == 'false' else None)

                            if val_bool is not None:
                                if key_idx == '1':
                                    task.app_config['show_details'] = val_bool
                                    task._save_config()
                                    print(" -> show_details 更新成功！")
                                elif key_idx == '2':
                                    task.app_config['generate_image'] = val_bool
                                    task._save_config()
                                    print(" -> generate_image 更新成功！")
                                else:
                                    print(" -> 未知项号，请输 1 或 2！")
                            else:
                                print(" -> 参数错误，值只能为 true 或 false。")
                        else:
                            print(" -> 指令格式错误，请使用如 '1 false' 的格式。")
                    continue

                if not dut_in:
                    task.scan_counter += 1
                    dut_in = f"DUT_Scan_{task.scan_counter}"

                task.run(dut_in)
    else:
        print("\n [!] Error: Failed to connect to Siglent Oscilloscope via VISA. Please verify USB connection.")
        sys.exit(1)

    if task.inst:
        task.inst.close()