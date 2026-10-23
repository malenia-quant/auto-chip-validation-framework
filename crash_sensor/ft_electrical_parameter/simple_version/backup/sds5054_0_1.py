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
SYNC_WIDTH_MIN = 1.5
SYNC_WIDTH_MAX = 30.0  # Max Sync Duration (us)
SENSOR_SEARCH_WINDOW = 400.0  # [修改] Search for sensors within 400us after Sync

# [新增/修改] 全局基线求取分位数配置
GLOBAL_TOP_CUTOFF_FACTOR = 0.98
GLOBAL_BOT_CUTOFF_FACTOR = 0.60

# [新增/修改] 局部上下界均值计算的排除比例配置
LOCAL_TOP_CUTOFF_FACTOR = 0.98
LOCAL_BOT_CUTOFF_FACTOR = 0.02

# [新增] 物理层阈值判定门限因子，消除硬编码
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
            self.inst.write('CH1:TRA ON')
            self.inst.write('C1:PROB 10')
            self.inst.write('CH1:BWL 20M')
            self.inst.write('CH1:COUP DC')
            self.inst.write('CH1:SCAL 0.1')
            self.inst.write('CH1:OFFS 0')

            # 配置CH2采集VDDI
            self.inst.write('CH2:TRA ON')
            self.inst.write('C2:PROB 10')
            self.inst.write('CH2:BWL 20M')
            self.inst.write('CH2:COUP DC')
            self.inst.write('CH2:SCAL 1')
            self.inst.write('CH2:OFFS -2')

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

            # 读取 CH2 (VDDI)
            self.inst.write('WAV:SOUR C2')
            vdiv2 = self._parse_float(self.inst.query("C2:VDIV?"))
            voffset2 = self._parse_float(self.inst.query("C2:OFST?"))

            print(f"   [Transfer] Downloading C2 data...", end='', flush=True)
            self.inst.write("WAV:DATA?")
            raw2 = self.inst.read_raw()
            print(" Done.")

            if len(raw1) < 100: return None, None, None, 1e9

            # 解析 CH1
            header_len = 0
            if raw1[0:1] == b'#':
                len_of_len = int(chr(raw1[1]))
                header_len = 2 + len_of_len

            raw_data1 = raw1[header_len:-1]
            data_int1 = np.frombuffer(raw_data1, dtype=np.int8)
            v1 = data_int1 * (vdiv1 / 25.0) - voffset1

            # 解析 CH2
            header_len2 = 0
            if raw2[0:1] == b'#':
                len_of_len2 = int(chr(raw2[1]))
                header_len2 = 2 + len_of_len2

            raw_data2 = raw2[header_len2:-1]
            data_int2 = np.frombuffer(raw_data2, dtype=np.int8)
            v2 = data_int2 * (vdiv2 / 25.0) - voffset2

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
        """Time Slot Logic."""
        if 20.0 < delay_us < 180.0: return 1
        if 180.0 <= delay_us < 320.0: return 2
        if 320.0 <= delay_us < 500.0: return 3
        if 500.0 <= delay_us < 700.0: return 4  # 容错菊花链延迟
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
        vddi_mean = np.mean(v2)

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

            l_top_pct = min(LOCAL_TOP_CUTOFF_FACTOR * 100, 100.0)
            l_bot_pct = max(LOCAL_BOT_CUTOFF_FACTOR * 100, 0.0)

            local_top = np.percentile(sens_i, l_top_pct)
            bottom_current = np.percentile(sens_i, l_bot_pct)
            local_amp = local_top - bottom_current

            # 使用全局定义的阈值因子计算局部门限
            local_lvl_20 = bottom_current + LVL_20_FACTOR * local_amp
            local_lvl_80 = bottom_current + LVL_80_FACTOR * local_amp
            local_threshold = bottom_current + LVL_50_FACTOR * local_amp

            # ====================================================================
            # [终极重构] 锁孔匹配法：解耦 50% 精准时序 与 20%-80% Schmitt 强验证
            # ====================================================================

            # 1. 提取全量 50% 锚点（包含真实边沿和游走噪声的交叉点）
            t50_all, slopes_all = self._linear_interp_val(sens_t, sens_i, local_threshold)

            # 2. 提取 Schmitt 触发点（绝对真实的物理翻转验证，彻底滤除门限内的游走噪声）
            dig = self._schmitt_trigger(sens_i, local_lvl_20, local_lvl_80)
            edges = np.diff(dig)
            valid_idxs = np.where(edges != 0)[0]

            # 3. 锁孔匹配：将精准的 50% 时间点与 Schmitt 的抗噪验证绑定
            t50_list_raw, slopes_raw = [], []

            for idx in valid_idxs:
                t_trigger = sens_t[idx]
                direction = edges[idx]  # 1: 上升 (突破80%), -1: 下降 (跌破20%)

                # 从触发点向历史回溯，寻找最近的、同方向的 50% 交叉点
                valid_t50 = None
                for k in range(len(t50_all) - 1, -1, -1):
                    # 50% 交叉必然发生在突破 80% 或跌破 20% 之前，且斜率方向一致
                    if t50_all[k] <= t_trigger and slopes_all[k] == direction:
                        # 安全余量：50%点到80%/20%触发点的时间差放宽到 4us，完美兼容极慢边沿
                        if (t_trigger - t50_all[k]) < 4.0e-6:
                            valid_t50 = t50_all[k]
                            break

                if valid_t50 is not None:
                    t50_list_raw.append(valid_t50)
                    slopes_raw.append(direction)

            # [保留逻辑] 精准 1.8us 毛刺过滤，抵御极端高频穿透性干扰
            filtered_t50, filtered_slopes = [], []
            idx = 0
            while idx < len(t50_list_raw):
                if idx + 1 < len(t50_list_raw):
                    delta = t50_list_raw[idx + 1] - t50_list_raw[idx]
                    if delta < 1.8e-6:
                        idx += 2
                        continue
                filtered_t50.append(t50_list_raw[idx])
                filtered_slopes.append(slopes_raw[idx])
                idx += 1

            # [保留逻辑] 确保严格交替
            clean_t50, clean_slopes = [], []
            for t_val, s_val in zip(filtered_t50, filtered_slopes):
                if len(clean_slopes) == 0 or s_val != clean_slopes[-1]:
                    clean_t50.append(t_val)
                    clean_slopes.append(s_val)
                else:
                    clean_t50[-1] = t_val

            clean_t50 = np.array(clean_t50)
            clean_slopes = np.array(clean_slopes)
            rise_anchors = clean_t50[clean_slopes == 1]
            fall_anchors = clean_t50[clean_slopes == -1]

            # Rise / Fall Calc
            rise_durs = []
            for r_t in rise_anchors:
                mask = (sens_t > r_t - 2e-6) & (sens_t < r_t + 2e-6)
                t_sub, i_sub = sens_t[mask], sens_i[mask]
                t20_l, _ = self._linear_interp_val(t_sub, i_sub, local_lvl_20)
                t80_l, _ = self._linear_interp_val(t_sub, i_sub, local_lvl_80)
                prev_20 = t20_l[t20_l < r_t]
                next_80 = t80_l[t80_l > r_t]
                if len(prev_20) > 0 and len(next_80) > 0:
                    rise_durs.append((next_80[0] - prev_20[-1]) * 1e9)

            fall_durs = []
            for f_t in fall_anchors:
                mask = (sens_t > f_t - 2e-6) & (sens_t < f_t + 2e-6)
                t_sub, i_sub = sens_t[mask], sens_i[mask]
                t80_l, _ = self._linear_interp_val(t_sub, i_sub, local_lvl_80)
                t20_l, _ = self._linear_interp_val(t_sub, i_sub, local_lvl_20)
                prev_80 = t80_l[t80_l < f_t]
                next_20 = t20_l[t20_l > f_t]
                if len(prev_80) > 0 and len(next_20) > 0:
                    fall_durs.append((next_20[0] - prev_80[-1]) * 1e9)

            # --- MANCHESTER DECODING & BIT-BY-BIT ANALYSIS (重构) ---
            mid_edges = []
            decoded_bits = []
            bit_duty_cycles = []  # 存储每个bit的占空比

            if len(clean_t50) >= 2:
                # 寻找第一个上升沿作为 Start Bit (0) 的中心点
                first_rise_idx = -1
                for i in range(min(5, len(clean_t50))):
                    if clean_slopes[i] == 1:
                        first_rise_idx = i
                        break

                if first_rise_idx != -1:
                    idx = first_rise_idx
                    mid_edges.append(clean_t50[idx])
                    decoded_bits.append(0)

                    idx += 1
                    while idx < len(clean_t50):
                        delta_t = clean_t50[idx] - mid_edges[-1]

                        found_next_mid = False
                        # [保留修改] 情况A：找到了下一个比特的中心跳变点。下限保持5.5us
                        if 5.5e-6 < delta_t < 11.5e-6:
                            current_mid = clean_t50[idx]
                            current_bit = 0 if clean_slopes[idx] == 1 else 1

                            t_bit_window = current_mid - mid_edges[-1]
                            t_high = t_bit_window / 2.0  # 默认50%

                            # 寻找落在两个中心点之间的电平对齐沿计算占空比
                            for k_search in range(1, 4):
                                if idx - k_search >= 0:
                                    potential_edge = clean_t50[idx - k_search]
                                    if mid_edges[-1] < potential_edge < current_mid:
                                        if current_bit == 0:
                                            t_high = current_mid - potential_edge
                                        else:
                                            t_high = potential_edge - mid_edges[-1]
                                        break

                            bit_duty_cycles.append((t_high / t_bit_window) * 100.0)
                            mid_edges.append(current_mid)
                            decoded_bits.append(current_bit)
                            idx += 1
                            found_next_mid = True

                        # [保留修改] 情况B：遇到了电平对齐沿。下限严格收紧到 3.0us，防止被噪声骗
                        elif 3.0e-6 < delta_t <= 5.5e-6:
                            if idx + 1 < len(clean_t50):
                                current_mid = clean_t50[idx + 1]
                                current_bit = 0 if clean_slopes[idx + 1] == 1 else 1

                                t_bit_window = current_mid - mid_edges[-1]
                                # 对齐沿就是 clean_t50[idx]
                                if current_bit == 0:
                                    t_high = current_mid - clean_t50[idx]
                                else:
                                    t_high = clean_t50[idx] - mid_edges[-1]

                                bit_duty_cycles.append((t_high / t_bit_window) * 100.0)
                                mid_edges.append(current_mid)
                                decoded_bits.append(current_bit)
                                idx += 2
                                found_next_mid = True

                        if not found_next_mid:
                            # 只有 <3.0us 的间距才被认定为高频噪声跳过，其余跳变被视为帧结束断点
                            if delta_t <= 3.0e-6:
                                idx += 1
                            else:
                                break

            estimated_bits = []
            if len(mid_edges) > 1:
                estimated_bits = list(np.diff(mid_edges) * 1e6)

            tbit_avg = np.mean(estimated_bits) if len(estimated_bits) > 0 else 0.0

            # 调用强校验16进制转换
            hex_raw, hex_payload, decimal_val = self._convert_psi5_13bit_to_hex(decoded_bits)

            # --- Duty Cycle ---
            duty_cycle = 0.0
            if len(clean_t50) > 1 and tbit_avg > 0:
                diffs_all = np.diff(clean_t50)
                shorts_all = diffs_all[(diffs_all > 3.0e-6) & (diffs_all < 5.5e-6)]
                if len(shorts_all) > 0:
                    duty_cycle = (np.mean(shorts_all) / (tbit_avg * 1e-6)) * 100.0

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

            # Max Clock Drift Rate: During Dataframe
            if len(estimated_bits) > 1:
                diffs = np.abs(np.diff(estimated_bits))
                drift_time_val = np.max(diffs / estimated_bits[:-1]) * 100.0

            rpt = {
                "id": s_id,
                "local_amp": local_amp,
                "rise_list": rise_durs,
                "fall_list": fall_durs,
                "bit_list": estimated_bits,
                "drift_frame": drift_frame,
                "drift_time": drift_time_val,
                "duty_cycle_list": bit_duty_cycles,
                "duty_cycle": np.mean(bit_duty_cycles) if bit_duty_cycles else 0.0,
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
                "s_lvl80": local_lvl_80
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
        print(f"[*] VDDI Average (CH2): {vddi_avg:.3f} V")

        for r in reports:
            d_time_str = f"{r['drift_time']:.4f} % (During Frame)" if r['drift_time'] is not None else "-"

            # [修改] 使用原生的列表推导式强转字符串格式，杜绝 Numpy 的抽风行为
            str_rise = "[" + ", ".join([f"{v:.1f}" for v in r['rise_list']]) + "]" if r['rise_list'] else "[]"
            str_fall = "[" + ", ".join([f"{v:.1f}" for v in r['fall_list']]) + "]" if r['fall_list'] else "[]"
            str_bit = "[" + ", ".join([f"{v:.3f}" for v in r['bit_list']]) + "]" if r['bit_list'] else "[]"

            print(f"\n[ SENSOR {r['id']} ]")
            print("--- PART 1: PHYSICAL LAYER ---")
            print(f"0. Sink Current: {r['local_amp']:.1f} mA")
            print(f"1. Sink Rise Mean: {np.mean(r['rise_list']) if r['rise_list'] else 0:.1f} ns")
            print(f"1.1 Sink Rise Details: {str_rise}")
            print(f"2. Sink Fall Mean: {np.mean(r['fall_list']) if r['fall_list'] else 0:.1f} ns")
            print(f"2.1 Sink Fall Details: {str_fall}")
            print(f"3. Bit Time Avg (125k): {r['tbit_avg']:.3f} us")
            print(f"3.1 Bit Time (Per Bit): {str_bit}")
            print(f"4. Bit Time (189k): N/A")
            print(f"5. Max Clock Drift Ratio: {r['drift_frame']:.3f} %")
            print(f"6. Max Clock Drift Rate: {d_time_str}")

            if r['duty_cycle_list']:
                dc_str = ", ".join([f"{val:.1f}%" for val in r['duty_cycle_list']])
                print(f"7.1 Duty Cycle (Per Bit): [{dc_str}]")  # [修改] 编号改为7.1
            print(f"7. Duty Cycle (Mean): {r['duty_cycle']:.1f} %")

            print("--- PART 2: PROTOCOL LAYER ---")
            print(f"8. Start Time (tDelay): {r['start_us']:.1f} us")
            print(f"9. End Time: {r['end_us']:.1f} us")
            print(f"10. Frame Time (tFrame): {r['t_frame']:.1f} us")
            print(f"11. Cycle Time (tCycle): {r['t_cycle']:.1f} us")

            print("--- PART 3: DATA PAYLOAD ---")
            # [新增] 对残缺帧直接报红灯
            if not r['is_valid_frame']:
                print(
                    f"12. Decoded Bits (13-bit): {r['decoded_bits']}  <-- [ERROR] Invalid Length: {len(r['decoded_bits'])} / 13")
            else:
                print(f"12. Decoded Bits (13-bit): {r['decoded_bits']}")
            print(f"13. HEX (Raw Waveform):    {r.get('hex_raw', 'N/A')}")
            print(f"14. HEX (Sensor Payload):  {r.get('hex_payload', 'N/A')}")
            print(f"15. Decimal Value (10b):   {r.get('decimal_val', 'N/A')}")
            print("-" * 40)

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

            ax_zoom.axhline(base, color='b', ls=':', lw=2.5, alpha=0.9, label='Global Base')

            for idx, r in enumerate(reports):
                start_rel_us = (r['abs_t_start'] - t_offset) * 1e6
                end_rel_us = (r['abs_t_end'] - t_offset) * 1e6
                label_top = 'Local Top' if idx == 0 else ""
                label_bot = 'Local Base' if idx == 0 else ""
                ax_zoom.hlines(r['s_top'], start_rel_us, end_rel_us, color='g', linestyles='--', lw=2.5,
                               label=label_top)
                ax_zoom.hlines(r['s_bot'], start_rel_us, end_rel_us, color='orange', linestyles='--', lw=2.5,
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
        plt.savefig(f"PSI5_FT_Elec_Para_{sn}.jpg", dpi=120, format='jpeg', bbox_inches='tight')
        plt.close('all')
        import gc
        gc.collect()
        print(f"Report Generated: PSI5_FT_Elec_Para_{sn}.jpg")

    def save_to_csv(self, dut_name, reports, vddi):
        """
        [修改] 全量同步打印数据，按顺序保存入库
        """
        filename = "psi5_results.csv"
        file_exists = os.path.isfile(filename)

        with open(filename, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "DUT", "Sensor_ID", "VDDI_Avg (V)", "Sink Current (mA)",
                    "Sink Rise Mean (ns)", "Sink Rise Details (ns)",
                    "Sink Fall Mean (ns)", "Sink Fall Details (ns)",
                    "Bit Time Avg 125k (us)", "Bit Time Details (us)",
                    "Max Clock Drift Ratio (%)", "Max Clock Drift Rate (%/frame)",
                    "Duty Cycle Per Bit (%)", "Duty Cycle Mean (%)",
                    "Start Time tDelay (us)", "End Time (us)",
                    "Frame Time tFrame (us)", "Cycle Time tCycle (us)",
                    "Decoded Bits", "Valid Frame", "HEX (Raw)", "HEX (Payload)", "Decimal Value"
                ])

            for r in reports:
                drift_time_str = f"{r['drift_time']:.4f}" if r['drift_time'] is not None else "N/A"
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
                    f"{vddi:.3f}",
                    f"{r['local_amp']:.2f}",
                    rise_mean,
                    str_rise,
                    fall_mean,
                    str_fall,
                    f"{r['tbit_avg']:.3f}",
                    str_bit,
                    f"{r['drift_frame']:.3f}",
                    drift_time_str,
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
                    r.get('decimal_val', 'N/A')
                ])
        print(f"   [CSV] Full Details appended to {filename} for DUT: {dut_name}")

    def run(self, dut_name):
        t, v1, v2, s = self.fetch_waveform()
        if t is not None and v2 is not None:
            success, reports, vddi = self.analyze(t, v1, v2, s, dut_name)
            if success:
                self.save_to_csv(dut_name, reports, vddi)


if __name__ == "__main__":
    task = SDS_Frame_Validator()
    if task.connect():
        task.setup()

        while True:
            print("-" * 60)
            sys.stdout.flush()
            dut_in = input("\n请输入待测器件号(直接按 Enter 默认 DUT_Test，输入 q 退出): ").strip()

            if dut_in.lower() == 'q':
                print("Exit Testing.")
                break

            if not dut_in:
                task.scan_counter += 1
                dut_in = f"DUT_Scan_{task.scan_counter}"

            task.run(dut_in)

    if task.inst: task.inst.close()