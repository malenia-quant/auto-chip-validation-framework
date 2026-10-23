"""Test Suite for Signal Cleaning, Histogram Level Detection, and PSI5 Decoding.

Author: mozial
"""

import pytest
import numpy as np
from analysis.signal_processing import SignalCleaner, PSI5Decoder
from analysis.data_cleaning import DataConsolidator


class TestSignalProcessing:
    """Validate signal processing algorithms on synthetic noisy PSI5 data."""

    def test_histogram_level_detection(self):
        """Test bi-modal histogram extraction of base and peak current levels."""
        # Synthesize 1000 points of base current (26mA) and 300 points of pulsed current (52mA) with noise
        np.random.seed(42)
        base = np.random.normal(26.0, 0.5, 1000)
        pulse = np.random.normal(52.0, 0.5, 300)
        signal = np.concatenate([base, pulse])

        val_base, val_top, amp = SignalCleaner.compute_histogram_levels(signal, bins=80)
        assert val_base == pytest.approx(26.0, abs=1.0)
        assert val_top == pytest.approx(52.0, abs=1.0)
        assert amp == pytest.approx(26.0, abs=1.5)

    def test_glitch_removal(self):
        """Test narrow glitch filter."""
        cleaner = SignalCleaner(sample_rate=10e6)
        sig = np.ones(500) * 10.0
        # Inject narrow spike
        sig[100:102] = 50.0

        filtered = cleaner.remove_glitches(sig, filter_window_us=1.0)
        assert filtered[100] == pytest.approx(10.0, abs=0.5)

    def test_psi5_decoder_synthetic_manchester(self):
        """Test Manchester PLL bit decoding on a known synthetic PSI5 frame."""
        fs = 20e6
        decoder = PSI5Decoder(sample_rate=fs, nominal_bitrate=125000.0)
        bit_period_pts = int(fs / 125000.0)  # 160 points per bit

        # Construct Manchester encoded bits: [0, 0, 1, 0, 1]
        # '0' = Low then High; '1' = High then Low
        test_bits = [0, 0, 1, 0, 1]
        waveform_segments = []
        for bit in test_bits:
            half = bit_period_pts // 2
            if bit == 0:
                seg = np.concatenate([np.ones(half) * 26.0, np.ones(half) * 52.0])
            else:
                seg = np.concatenate([np.ones(half) * 52.0, np.ones(half) * 26.0])
            waveform_segments.append(seg)

        y = np.concatenate(waveform_segments)
        t = np.linspace(0, len(y) / fs, len(y))

        res = decoder.decode_sensor_frame(t, y, base_ma=26.0, amp_ma=26.0)
        assert res["success"] is True
        assert res["decoded_bits"][:len(test_bits)] == test_bits
        assert res["tbit_avg_us"] == pytest.approx(8.0, abs=0.5)


class TestDataCleaning:
    """Validate statistical consolidation and IQR outlier pruning."""

    def test_outlier_detection_iqr(self):
        import pandas as pd
        data = pd.Series([10.0, 10.2, 9.9, 10.1, 10.0, 100.0, -50.0])
        outliers = DataConsolidator.detect_outliers_iqr(data)
        assert bool(outliers.iloc[5]) is True
        assert bool(outliers.iloc[6]) is True
        assert bool(outliers.iloc[0]) is False

    def test_summary_stats(self):
        samples = [1.0, 2.0, 3.0, 4.0, 5.0]
        stats = DataConsolidator.calculate_summary_stats(samples)
        assert stats["count"] == 5
        assert stats["mean"] == 3.0
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["span"] == 4.0
