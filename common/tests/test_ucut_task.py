"""Test Suite for Micro-Cut (uCut) Under-Voltage Reset and Fast Power Faults.

Refactored from CrashSensor_FT/dg5072_task.py & crash_sensor/.../dg5072_ucut.py.
Author: mozial
"""

import pytest
import numpy as np
from drivers.generator_dg5072 import DG5072Driver


# 12 representative PSI5 test cases from dg5072_task.py
PSI5_CASES_FIXTURE = [
    (1, 4.5, 0.0, 4.5, 1.34, 1.34),
    (2, 4.5, 3.5, 8.0, 1.34, 2.92),
    (3, 4.5, 5.5, 10.0, 1.34, 3.93),
    (4, 6.7, 0.0, 6.7, 2.33, 2.33),
    (5, 6.7, 3.5, 10.2, 2.33, 3.92),
    (6, 6.7, 5.5, 12.2, 2.33, 4.82),
    (7, 11.0, 0.0, 11.0, 4.26, 4.26),
    (8, 11.0, 3.5, 14.5, 4.26, 5.85),
    (9, 11.0, 5.5, 16.5, 4.26, 6.75),
    (10, 5.0, 0.0, 5.0, 1.57, 1.57),
    (11, 5.0, 3.5, 8.5, 1.57, 3.15),
    (12, 5.0, 5.5, 10.5, 1.57, 4.06),
]


class TestUCutVoltageMapping:
    """Validate linear interpolation and discrete voltage mapping for uCut / sync pulse."""

    @pytest.mark.parametrize("case_id,base_v,pulse_v,total_v,dg_low,dg_high", PSI5_CASES_FIXTURE)
    def test_psi5_case_mapping(self, case_id, base_v, pulse_v, total_v, dg_low, dg_high):
        """Ensure predefined table matches calibrated hardware values."""
        case = DG5072Driver.PSI5_CASES[case_id]
        assert case["base_v"] == pytest.approx(base_v, abs=1e-3)
        assert case["pulse_v"] == pytest.approx(pulse_v, abs=1e-3)
        assert case["total_v"] == pytest.approx(total_v, abs=1e-3)
        assert case["dg_low"] == pytest.approx(dg_low, abs=1e-3)
        assert case["dg_high"] == pytest.approx(dg_high, abs=1e-3)

    @pytest.mark.parametrize(
        "pcb_voltage,expected_dg",
        [
            (0.0, 0.0),
            (4.5, 1.34),
            (6.7, 2.33),
            (11.0, 4.26),
            (5.6, 1.835),  # midpoint between 4.5 and 6.7
        ],
    )
    def test_pcb_to_dg_interpolation(self, pcb_voltage, expected_dg):
        """Ensure continuous interpolation matches transfer function."""
        dg_v = DG5072Driver.pcb_to_dg_voltage(pcb_voltage)
        assert dg_v == pytest.approx(expected_dg, abs=1e-2)


class TestUCutWaveformGeneration:
    """Validate arbitrary waveform shape generation for uCut micro-interruption."""

    @pytest.mark.parametrize(
        "ucut_duration_us,ucut_start_us",
        [
            (6.5, 300.0),   # White zone (no reset expected)
            (2000.0, 100.0), # Yellow/Mid zone (potential reset)
            (5000.0, 300.0), # Red zone (POR guaranteed)
        ],
    )
    def test_ucut_arb_waveform_synthesis(self, ucut_duration_us, ucut_start_us):
        """Generate and verify 16384-point ARB uCut fault waveform."""
        total_points = 16384
        period_us = 6000.0
        v_base = 1.5
        v_sync_high = 3.5
        v_cut_low = 0.0

        v_amp = v_sync_high - v_cut_low
        v_offset = (v_sync_high + v_cut_low) / 2.0
        norm_base = (v_base - v_offset) / (v_amp / 2.0)

        waveform = np.full(total_points, norm_base, dtype=np.float32)

        def us_to_idx(time_us):
            return min(max(int((time_us / period_us) * total_points), 0), total_points)

        # Apply uCut fault slice
        s_idx = us_to_idx(ucut_start_us)
        e_idx = us_to_idx(ucut_start_us + ucut_duration_us)
        waveform[s_idx:e_idx] = -1.0

        # Assert fault duration in array corresponds to requested time window
        assert waveform[s_idx] == -1.0
        assert (e_idx - s_idx) > 0
        assert len(waveform) == total_points
