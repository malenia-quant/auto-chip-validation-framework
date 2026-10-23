"""Time-series data cleaning, edge detection, and PSI5 protocol decoding module.

Features:
- Schmitt trigger with noise filtering
- Linear interpolation for accurate crossing times
- Manchester clock recovery and bit extraction
- Slot timing, pulse width, and slew rate measurements
- Outlier detection and baseline correction using Pandas / NumPy

Author: mozial
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.signal import medfilt, savgol_filter


class SignalCleaner:
    """Utility class for filtering and cleaning raw analog waveforms."""

    def __init__(self, sample_rate: float):
        self.sample_rate = sample_rate
        self.logger = logging.getLogger("Analysis.Cleaner")

    def remove_glitches(self, signal: np.ndarray, filter_window_us: float = 0.8) -> np.ndarray:
        """Apply median filter to remove narrow-band glitch spikes."""
        kernel_pts = int(filter_window_us * 1e-6 * self.sample_rate)
        if kernel_pts % 2 == 0:
            kernel_pts += 1
        if kernel_pts < 3:
            kernel_pts = 3
        return medfilt(signal, kernel_size=kernel_pts)

    def smooth_edges(self, signal: np.ndarray, window_us: float = 1.0, poly_order: int = 3) -> np.ndarray:
        """Apply Savitzky-Golay filter to smooth transition edges without distorting peaks."""
        window_pts = int(window_us * 1e-6 * self.sample_rate)
        if window_pts % 2 == 0:
            window_pts += 1
        if window_pts <= poly_order:
            window_pts = poly_order + 2
            if window_pts % 2 == 0:
                window_pts += 1
        if len(signal) <= window_pts:
            return signal
        return savgol_filter(signal, window_pts, poly_order)

    @staticmethod
    def compute_histogram_levels(
        signal: np.ndarray, bins: int = 100
    ) -> Tuple[float, float, float]:
        """Compute signal baseline, high level and peak amplitude via histogram mode detection."""
        sig_min, sig_max = float(np.min(signal)), float(np.max(signal))
        mid = (sig_min + sig_max) / 2.0

        hist, bin_edges = np.histogram(signal, bins=bins, range=(sig_min, sig_max))
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0

        base_mask = bin_centers < mid
        val_base = (
            float(bin_centers[base_mask][np.argmax(hist[base_mask])])
            if np.any(base_mask)
            else sig_min
        )

        top_mask = bin_centers > mid
        val_top = (
            float(bin_centers[top_mask][np.argmax(hist[top_mask])])
            if np.any(top_mask)
            else sig_max
        )

        amp = val_top - val_base
        return val_base, val_top, amp


class PSI5Decoder:
    """Software-based Manchester decoder for PSI5 (Peripheral Sensor Interface 5) protocol."""

    def __init__(self, sample_rate: float, nominal_bitrate: float = 125000.0):
        self.sample_rate = sample_rate
        self.nominal_bitrate = nominal_bitrate
        self.nominal_tbit_s = 1.0 / nominal_bitrate
        self.logger = logging.getLogger("Analysis.PSI5Decoder")

    @staticmethod
    def linear_interpolate_crossings(
        t: np.ndarray, y: np.ndarray, threshold: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Find timestamps and slope directions where y crosses threshold."""
        cross_mask = (y > threshold).astype(int)
        diffs = np.diff(cross_mask)
        idxs = np.where(diffs != 0)[0]

        t_crossings = []
        slopes = []
        for i in idxs:
            if i + 1 < len(y):
                y0, y1 = y[i], y[i + 1]
                t0, t1 = t[i], t[i + 1]
                if y1 != y0:
                    t_interp = t0 + (threshold - y0) * (t1 - t0) / (y1 - y0)
                    t_crossings.append(t_interp)
                    slopes.append(diffs[i])
        return np.array(t_crossings), np.array(slopes)

    def decode_sensor_frame(
        self, t: np.ndarray, current_ma: np.ndarray, base_ma: float, amp_ma: float
    ) -> Dict[str, Any]:
        """Extract Manchester bits and timing characteristics from a sensor transmission slot."""
        lvl_50 = base_ma + 0.5 * amp_ma
        lvl_20 = base_ma + 0.2 * amp_ma
        lvl_80 = base_ma + 0.8 * amp_ma

        cross_t, slopes = self.linear_interpolate_crossings(t, current_ma, lvl_50)
        if len(cross_t) < 2:
            return {"success": False, "reason": "Insufficient transitions"}

        # Manchester PLL window tracking
        first_rise_idx = -1
        for i in range(min(5, len(cross_t))):
            if slopes[i] == 1:
                first_rise_idx = i
                break

        if first_rise_idx == -1:
            return {"success": False, "reason": "No initial rising edge"}

        mid_edges = [cross_t[first_rise_idx]]
        decoded_bits = [0]
        expected_t = mid_edges[-1] + self.nominal_tbit_s

        for _ in range(19):  # Support up to 20 bits
            best_idx = -1
            min_err = 9999.0
            for i in range(first_rise_idx + 1, len(cross_t)):
                err = abs(cross_t[i] - expected_t)
                if err < 0.35 * self.nominal_tbit_s and err < min_err:
                    min_err = err
                    best_idx = i

            if best_idx != -1:
                actual_time = cross_t[best_idx]
                slope = slopes[best_idx]
                mid_edges.append(actual_time)
                decoded_bits.append(0 if slope == 1 else 1)
                t_bit = actual_time - mid_edges[-2]
                expected_t = actual_time + t_bit
                first_rise_idx = best_idx
            else:
                break

        bit_durations_us = np.diff(mid_edges) * 1e6 if len(mid_edges) > 1 else np.array([])
        tbit_avg_us = float(np.mean(bit_durations_us)) if len(bit_durations_us) > 0 else 0.0

        # Calculate Rise and Fall times
        rise_times_ns = []
        fall_times_ns = []
        for i, edge_t in enumerate(cross_t):
            direction = slopes[i]
            mask = (t > edge_t - 2e-6) & (t < edge_t + 2e-6)
            if not np.any(mask):
                continue
            sub_t, sub_y = t[mask], current_ma[mask]
            t20, _ = self.linear_interpolate_crossings(sub_t, sub_y, lvl_20)
            t80, _ = self.linear_interpolate_crossings(sub_t, sub_y, lvl_80)
            if direction == 1 and len(t20) > 0 and len(t80) > 0:
                t20_valid = t20[t20 < edge_t]
                t80_valid = t80[t80 > edge_t]
                if len(t20_valid) > 0 and len(t80_valid) > 0:
                    rise_times_ns.append(float((t80_valid[0] - t20_valid[-1]) * 1e9))
            elif direction == -1 and len(t20) > 0 and len(t80) > 0:
                t80_valid = t80[t80 < edge_t]
                t20_valid = t20[t20 > edge_t]
                if len(t80_valid) > 0 and len(t20_valid) > 0:
                    fall_times_ns.append(float((t20_valid[0] - t80_valid[-1]) * 1e9))

        return {
            "success": True,
            "decoded_bits": decoded_bits,
            "bit_count": len(decoded_bits),
            "tbit_avg_us": tbit_avg_us,
            "estimated_freq_khz": (1000.0 / tbit_avg_us) if tbit_avg_us > 0 else 0.0,
            "rise_time_avg_ns": float(np.mean(rise_times_ns)) if rise_times_ns else 0.0,
            "fall_time_avg_ns": float(np.mean(fall_times_ns)) if fall_times_ns else 0.0,
        }
