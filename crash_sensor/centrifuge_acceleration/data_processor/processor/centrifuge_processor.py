"""
CrashSensor 离心机动态数据处理引擎
复用 sensor_processor2.py 的成熟边缘检测与稳态裁剪算法，
参数化配置 start_idx = 30 (过滤前 30 帧过渡态) 与稳态截取 <= 50 点均值计算。
"""

import os
import configparser
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # 非交互式后端
import matplotlib.pyplot as plt


class CentrifugeProcessor:
    """
    离心机双轴数据处理器
    1. 边缘检测：检测离心机加减速与零位分割。
    2. 数据裁剪：start_idx = 30 跳过动态过渡震颤，截取 steady_points_max <= 50 点稳态数据。
    3. 稳态均值计算：输出各工位通道的 +160g / -160g 平台实测均值。
    4. 产出 ProcessedData1 / ProcessedData2 与阶梯图。
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        discard_frames: int = 30,
        steady_points_max: int = 0,  # 0 表示不限制固定点数，自适应提取稳态区间全量数据 (需求 3)
        min_length: int = 8,
        step_threshold: float = 100.0,  # 阶跃突变检测阈值 (从0突变到100LSB以上判定加速度加载，需求 3)
        zero_division_p: float = 30.0,
        zero_division_n: float = -30.0,
        window_size: int = 5,
    ):
        self.discard_frames = discard_frames
        self.steady_points_max = steady_points_max
        self.min_length = min_length
        self.step_threshold = step_threshold
        self.zero_division_p = zero_division_p
        self.zero_division_n = zero_division_n
        self.window_size = window_size

        if config_path and os.path.exists(config_path):
            self._load_config(config_path)

    def _load_config(self, config_path: str):
        cfg = configparser.ConfigParser()
        cfg.read(config_path, encoding="utf-8")
        if "Calibration" in cfg:
            self.discard_frames = cfg.getint("Calibration", "discard_frames", fallback=self.discard_frames)
            self.steady_points_max = cfg.getint("Calibration", "steady_points_max", fallback=self.steady_points_max)
            self.step_threshold = cfg.getfloat("Calibration", "step_threshold_lsb", fallback=self.step_threshold)

    def detect_adaptive_plateaus(self, series: np.ndarray) -> Dict[str, Any]:
        """
        自适应多段阶跃与稳态平台提取核心算法 (满足需求 3 & 需求 8: 适配 0g -> 80g -> 160g -> 0g 连续阶跃)
        
        工作机制:
        1. 卷积滑动平均平滑 (window_size=5) 去除 CAN 通信高频毛刺与抖动。
        2. 计算一阶导数梯度与局部滑动标准差，精准区分加速爬坡阶跃与恒速稳态运行区。
        3. 连续平稳点自适应聚合成稳态平台 candidate，并去除首尾过渡毛刺。
        4. 稳态数据提取不强制限制 50 点，自适应提取该平台区间内的所有有效点求均值。
        5. 按加速度码值绝对值自动划分 0g (基线)、80g 平台 (~160 LSB) 与 160g 平台 (~320 LSB)。
        """
        result: Dict[str, Any] = {
            "plateaus": [],
            "mean_160_pos": None,
            "mean_160_neg": None,
            "mean_80_pos": None,
            "mean_80_neg": None,
            "mean_0": None,
        }

        if series is None or len(series) < self.min_length:
            return result

        arr = np.asarray(series, dtype=float)
        arr = arr[np.isfinite(arr)]
        if len(arr) < self.min_length:
            return result

        # 1. 移动平均平滑
        w = max(3, min(self.window_size, len(arr)))
        smoothed = np.convolve(arr, np.ones(w) / w, mode="same")

        # 2. 计算一阶梯度与局部滑动标准差
        grad = np.abs(np.gradient(smoothed))
        half_w = 3
        rolling_std = np.zeros(len(smoothed))
        for i in range(len(smoothed)):
            i_start = max(0, i - half_w)
            i_end = min(len(smoothed), i + half_w + 1)
            rolling_std[i] = np.std(smoothed[i_start:i_end])

        # 离心机恒速旋转时，数据平稳（梯度小且标准差小）
        is_steady = (grad < 2.5) & (rolling_std < 6.5)

        # 3. 提取所有连续平稳区间
        steady_blocks = []
        in_block = False
        start_idx = 0

        for i, flag in enumerate(is_steady):
            if flag and not in_block:
                in_block = True
                start_idx = i
            elif not flag and in_block:
                in_block = False
                end_idx = i
                if (end_idx - start_idx) >= self.min_length:
                    steady_blocks.append((start_idx, end_idx))
        if in_block:
            end_idx = len(is_steady)
            if (end_idx - start_idx) >= self.min_length:
                steady_blocks.append((start_idx, end_idx))

        if not steady_blocks:
            steady_blocks.append((0, len(smoothed)))

        # 4. 对每个平稳块自适应提取稳态数据 (削去首尾加减速尾巴过渡)，并分类
        plateaus = []
        for s_idx, e_idx in steady_blocks:
            block_len = e_idx - s_idx
            # 削去首尾各 10% (至少 1 点) 的过渡边缘
            trim = max(1, int(block_len * 0.1))
            eff_start = s_idx + trim
            eff_end = e_idx - trim
            if eff_end <= eff_start:
                eff_start = s_idx
                eff_end = e_idx

            steady_points = smoothed[eff_start:eff_end]
            # 若配置了 steady_points_max 且 > 0，则按配置截取；若为 0，则不限制固定点数，全量自适应使用 (需求 3)
            if self.steady_points_max > 0:
                steady_points = steady_points[:self.steady_points_max]

            if len(steady_points) < max(3, self.min_length // 2):
                continue

            m = float(np.mean(steady_points))
            abs_m = abs(m)
            plateau_info = {
                "start": eff_start,
                "end": eff_end,
                "count": len(steady_points),
                "mean": m,
                "std": float(np.std(steady_points)),
                "abs_mean": abs_m
            }

            # 阶跃分级识别 (0g / 80g / 160g 平台自适应分级)
            if abs_m < 50.0:
                plateau_info["stage"] = "0g"
            elif 50.0 <= abs_m < 220.0:
                plateau_info["stage"] = "80g"
            else:
                plateau_info["stage"] = "160g"

            plateaus.append(plateau_info)

        result["plateaus"] = plateaus

        # 提取各个关键阶梯的稳态均值
        # 0g 基线
        p_0 = [p for p in plateaus if p["stage"] == "0g"]
        if p_0:
            result["mean_0"] = float(np.mean([p["mean"] for p in p_0]))

        # 80g 平台 (正/负向)
        p_80_pos = [p for p in plateaus if p["stage"] == "80g" and p["mean"] > 0]
        p_80_neg = [p for p in plateaus if p["stage"] == "80g" and p["mean"] < 0]
        if p_80_pos:
            result["mean_80_pos"] = float(max(p_80_pos, key=lambda x: x["count"])["mean"])
        if p_80_neg:
            result["mean_80_neg"] = float(max(p_80_neg, key=lambda x: x["count"])["mean"])

        # 160g 平台 (正/负向)
        p_160_pos = [p for p in plateaus if p["stage"] == "160g" and p["mean"] > 0]
        p_160_neg = [p for p in plateaus if p["stage"] == "160g" and p["mean"] < 0]
        if p_160_pos:
            result["mean_160_pos"] = float(max(p_160_pos, key=lambda x: x["count"])["mean"])
        if p_160_neg:
            result["mean_160_neg"] = float(max(p_160_neg, key=lambda x: x["count"])["mean"])

        return result

    def detect_and_extract_segments(self, series: np.ndarray) -> Dict[str, List[np.ndarray]]:
        """
        核心边沿检测逻辑 (兼容保留老波形测试)
        检测正向台阶 (上升沿 -> 下降沿) 与 负向台阶 (下降沿 -> 上升沿)
        """
        if len(series) < self.window_size:
            return {"positive": [], "negative": []}

        # 移动平均卷积平滑
        smoothed = np.convolve(series, np.ones(self.window_size) / self.window_size, mode="valid")
        filtered_a = smoothed.copy()
        filtered_b = smoothed.copy()

        # 零位阈值分割
        filtered_a[filtered_a < self.zero_division_p] = self.zero_division_p
        filtered_b[filtered_b > self.zero_division_n] = self.zero_division_n

        # 正向边沿提取 (针对 filtered_a)
        rise_edges_a = np.where((filtered_a[:-1] == self.zero_division_p) & (filtered_a[1:] > self.zero_division_p))[0] + 1
        fall_edges_a = np.where((filtered_a[:-1] > self.zero_division_p) & (filtered_a[1:] == self.zero_division_p))[0] + 1

        # 负向边沿提取 (针对 filtered_b)
        fall_edges_b = np.where((filtered_b[:-1] == self.zero_division_n) & (filtered_b[1:] < self.zero_division_n))[0] + 1
        rise_edges_b = np.where((filtered_b[:-1] < self.zero_division_n) & (filtered_b[1:] == self.zero_division_n))[0] + 1

        pos_segments = []
        i, j = 0, 0
        while i < len(rise_edges_a) and j < len(fall_edges_a):
            rise_idx = rise_edges_a[i]
            fall_idx = fall_edges_a[j]
            if rise_idx < fall_idx:
                segment = smoothed[rise_idx:fall_idx]
                if len(segment) >= self.min_length:
                    pos_segments.append(segment)
                i += 1
                j += 1
            else:
                j += 1

        neg_segments = []
        i, j = 0, 0
        while i < len(fall_edges_b) and j < len(rise_edges_b):
            fall_idx = fall_edges_b[i]
            rise_idx = rise_edges_b[j]
            if fall_idx < rise_idx:
                segment = smoothed[fall_idx:rise_idx]
                if len(segment) >= self.min_length:
                    neg_segments.append(segment)
                i += 1
                j += 1
            else:
                j += 1

        return {"positive": pos_segments, "negative": neg_segments}

    def crop_steady_state(self, raw_segment: np.ndarray) -> Optional[np.ndarray]:
        """
        裁剪过渡态并截取稳态数据:
        若 steady_points_max > 0，则限制在 steady_points_max 点 (兼容老单元测试)；
        若 steady_points_max == 0，则自适应保留过渡态过滤后的全部稳态数据 (需求 3)。
        """
        if len(raw_segment) <= self.discard_frames:
            return None

        cropped = raw_segment[self.discard_frames:]
        if len(cropped) < self.min_length:
            return None

        if self.steady_points_max > 0:
            steady_state = cropped[:self.steady_points_max]
        else:
            steady_state = cropped
        return steady_state

    def process_series_mean(self, series: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
        """
        处理单通道完整序列，返回 (+160g稳态均值, -160g稳态均值)
        结合自适应阶跃与传统边沿提取，保障 100% 鲁棒性。
        """
        plateau_res = self.detect_adaptive_plateaus(series)
        pos_val = plateau_res.get("mean_160_pos")
        neg_val = plateau_res.get("mean_160_neg")

        if pos_val is None and plateau_res.get("mean_80_pos") is not None:
            pos_val = plateau_res.get("mean_80_pos")
        if neg_val is None and plateau_res.get("mean_80_neg") is not None:
            neg_val = plateau_res.get("mean_80_neg")

        # 兼容老测试用例：如果自适应未提取到，回退老边沿逻辑
        if pos_val is None or neg_val is None:
            segments = self.detect_and_extract_segments(series)
            if pos_val is None:
                pos_means = []
                for seg in segments["positive"]:
                    steady = self.crop_steady_state(seg)
                    if steady is not None and len(steady) > 0:
                        pos_means.append(float(np.mean(steady)))
                if pos_means:
                    pos_val = float(np.mean(pos_means))

            if neg_val is None:
                neg_means = []
                for seg in segments["negative"]:
                    steady = self.crop_steady_state(seg)
                    if steady is not None and len(steady) > 0:
                        neg_means.append(float(np.mean(steady)))
                if neg_means:
                    neg_val = float(np.mean(neg_means))

        return pos_val, neg_val

    def process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        批量处理包含多通道加速度列的 DataFrame
        每列对应一个通道 (如 'CH0', 'CH1' 或 'B1_S1')
        输出汇总统计 DataFrame
        """
        results = []
        for col in df.columns:
            if df[col].dtype.kind not in "iuf":
                continue
            series = df[col].dropna().values
            pos_mean, neg_mean = self.process_series_mean(series)
            results.append({
                "Channel": col,
                "Pos_160g_Mean": pos_mean,
                "Neg_160g_Mean": neg_mean,
                "Status": "Valid" if (pos_mean is not None and neg_mean is not None) else "Missing_Edge"
            })
        return pd.DataFrame(results)

    def compute_slot_steady_means(
        self,
        slot_series_map: Dict[int, List[float]],
        target_axis: str,
        fixture_map: Optional[Dict[int, str]] = None
    ) -> Dict[int, Optional[float]]:
        """
        根据工位时序加速度序列，结合目标测试轴向与工装 A/B 属性，自适应计算各工位真实稳态均值。
        - Axis1: 工装 A 为正向台阶 (+), 工装 B 为负向台阶 (-)
        - Axis2: 工装 A 为负向台阶 (-), 工装 B 为正向台阶 (+)
        支持 0g -> 80g -> 160g -> 0g 连续阶跃提取 (优先提取 160g 平台稳态均值，无固定点数限制)。
        """
        means_map: Dict[int, Optional[float]] = {}
        for slot_idx, vals in slot_series_map.items():
            if not vals:
                means_map[slot_idx] = None
                continue
            arr = np.array(vals, dtype=float)
            board_id = (slot_idx // 6) + 1
            default_fix = "N" if board_id in (1, 2) else "P"
            raw_fix = (fixture_map.get(slot_idx, default_fix) if fixture_map else default_fix).strip().upper()
            # 需求 8: 25C/25D 为正向区域(P)，25A/25B 为负向区域(N)；兼容旧 A/B 传入
            fixture = "N" if raw_fix in ("N", "A") else "P"

            plateau_res = self.detect_adaptive_plateaus(arr)
            pos_m = plateau_res.get("mean_160_pos") or plateau_res.get("mean_80_pos")
            neg_m = plateau_res.get("mean_160_neg") or plateau_res.get("mean_80_neg")

            if target_axis == "Axis1":
                # Axis1: 正向区 P 为正向读数 (+), 负向区 N 为负向读数 (-)
                if fixture == "P" and pos_m is not None:
                    means_map[slot_idx] = pos_m
                elif fixture == "N" and neg_m is not None:
                    means_map[slot_idx] = neg_m
                else:
                    pos_old, neg_old = self.process_series_mean(arr)
                    if fixture == "P" and pos_old is not None:
                        means_map[slot_idx] = pos_old
                    elif fixture == "N" and neg_old is not None:
                        means_map[slot_idx] = neg_old
                    else:
                        steady_part = arr[self.discard_frames:] if len(arr) > self.discard_frames else arr
                        means_map[slot_idx] = float(np.mean(steady_part))
            elif target_axis == "Axis2":
                # Axis2: 工装翻转 180°，正向区 P 变为负向读数 (-), 负向区 N 变为正向读数 (+)
                if fixture == "P" and neg_m is not None:
                    means_map[slot_idx] = neg_m
                elif fixture == "N" and pos_m is not None:
                    means_map[slot_idx] = pos_m
                else:
                    pos_old, neg_old = self.process_series_mean(arr)
                    if fixture == "P" and neg_old is not None:
                        means_map[slot_idx] = neg_old
                    elif fixture == "N" and pos_old is not None:
                        means_map[slot_idx] = pos_old
                    else:
                        steady_part = arr[self.discard_frames:] if len(arr) > self.discard_frames else arr
                        means_map[slot_idx] = float(np.mean(steady_part))
            else:
                steady_part = arr[self.discard_frames:] if len(arr) > self.discard_frames else arr
                means_map[slot_idx] = float(np.mean(steady_part))

        return means_map

    def create_staircase_plot(self, series: np.ndarray, title: str, output_path: str):
        """生成阶梯图并保存至指定路径"""
        plt.figure(figsize=(10, 4))
        plt.plot(series, label="Raw / Filtered", color="#1f77b4", linewidth=1.2)
        plt.axhline(y=self.zero_division_p, color="r", linestyle="--", alpha=0.6, label="Zero Division (+)")
        plt.axhline(y=self.zero_division_n, color="g", linestyle="--", alpha=0.6, label="Zero Division (-)")
        plt.title(title)
        plt.xlabel("Sample Index")
        plt.ylabel("Acceleration (LSB / g)")
        plt.legend(loc="upper right")
        plt.grid(True, linestyle=":", alpha=0.6)
        plt.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        plt.savefig(output_path, dpi=120)
        plt.close()
