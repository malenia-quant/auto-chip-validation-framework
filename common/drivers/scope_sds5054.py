"""Oscilloscope Driver Layer for Siglent SDS5000X series (e.g. SDS5054X).

Features:
- Timebase, vertical scale, trigger mode, and probe ratio configuration
- Protocol capture and dynamic acquisition with auto setup
- Fast waveform download (BYTE format with descriptor parsing)
- Mean/RMS and statistic extraction
- Context manager support and safe resource release

Author: mozial
"""

import time
from typing import Dict, Optional, Tuple
import numpy as np

from drivers.base_instrument import BaseInstrument


class SDS5054Driver(BaseInstrument):
    """Driver for Siglent SDS5054X / SDS5000X Digital Storage Oscilloscope."""

    def __init__(
        self,
        resource_name: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 5025,
        r_shunt: float = 10.03,
        timeout_ms: int = 60000,
    ):
        super().__init__(
            name="SDS5054",
            resource_name=resource_name,
            host=host,
            port=port,
            timeout_ms=timeout_ms,
        )
        self.r_shunt = r_shunt

    def _post_connect(self):
        """Configure default instrument environment."""
        self.clear_status()
        self.write("CH:HEAD OFF")

    def auto_setup(self, wait_sec: float = 6.0):
        """Execute Auto Setup (ASET) and wait for waveform to settle."""
        self.logger.info("Sending ASET (Auto Setup)...")
        self.write("ASET")
        time.sleep(wait_sec)

    def setup_channel(
        self,
        channel: int = 1,
        enabled: bool = True,
        scale_v: float = 0.1,
        offset_v: float = 0.0,
        probe_ratio: int = 10,
        coupling: str = "DC",
        bandwidth_limit: str = "20M",
    ):
        """Configure vertical channel parameters."""
        state = "ON" if enabled else "OFF"
        self.write(f"CH{channel}:TRA {state}")
        if not enabled:
            return

        self.write(f"C{channel}:PROB {probe_ratio}")
        self.write(f"CH{channel}:COUP {coupling}")
        self.write(f"CH{channel}:BWL {bandwidth_limit}")
        self.write(f"CH{channel}:SCAL {scale_v}")
        self.write(f"CH{channel}:OFFS {offset_v}")
        self.logger.info(
            f"CH{channel} configured: scale={scale_v}V/div, ofst={offset_v}V, probe={probe_ratio}X, coup={coupling}"
        )

    def setup_timebase(self, timebase_s: float = 500e-6, offset_s: float = 0.0, sample_depth: str = "10M"):
        """Configure horizontal timebase scale, offset and acquisition memory depth."""
        self.write(f"TIM:SCAL {timebase_s}")
        if offset_s != 0.0:
            self.write(f"TIM:OFFS {offset_s}")
        if sample_depth:
            self.write(f"ACQ:MDEP {sample_depth}")
        self.logger.info(f"Timebase set to {timebase_s} s/div, depth={sample_depth}")

    def setup_trigger(
        self,
        source_ch: int = 1,
        level_v: float = 0.15,
        slope: str = "RISE",
        mode: str = "AUTO",
    ):
        """Configure edge trigger parameters."""
        self.write("TRIG:MODE EDGE")
        self.write(f"TRIG:EDGE:SOUR C{source_ch}")
        self.write(f"TRIG:EDGE:LEV {level_v:.3f}")
        self.write(f"TRIG:EDGE:SLOP {slope}")
        self.write(f"TRIG:SWE {mode}")
        self.logger.info(f"Trigger configured: C{source_ch}, Level={level_v}V, Slope={slope}, Mode={mode}")

    def start_acquisition(self) -> bool:
        """Arm single acquisition trigger (non-blocking)."""
        try:
            self.write("TRIG:SWE SING")
            time.sleep(0.1)
            return True
        except Exception as e:
            self.logger.error(f"Failed to arm acquisition: {e}")
            return False

    def retrieve_waveform(self, channel: int = 1, timeout_sec: float = 5.0) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], float]:
        """Poll for trigger completion and download waveform bytes."""
        poll_start = time.time()
        triggered = False
        while time.time() - poll_start < timeout_sec:
            try:
                state = self.query("INR?").strip()
                if state != "0":
                    triggered = True
                    break
            except Exception:
                pass
            time.sleep(0.1)

        if not triggered:
            self.logger.warning("Acquisition timeout; stopping trigger.")
            self.write("STOP")
            return None, None, 1.0

        # Setup waveform format
        self.write(f"WAV:SOUR C{channel}")
        self.write("WAV:DATA:FMT BYTE")
        self.write("WAV:POIN:MODE MAX")

        vdiv = float(self.query(f"C{channel}:VDIV?").replace("V", "").strip())
        voffset = float(self.query(f"C{channel}:OFST?").replace("V", "").strip())
        sara = float(self.query("SARA?").replace("Sa/s", "").strip())

        self.write("WAV:DATA?")
        raw = self.read_raw()
        if len(raw) < 100:
            self.logger.error(f"Invalid raw waveform received: len={len(raw)}")
            return None, None, sara

        # Parse IEEE 488.2 binary header
        header_len = 0
        if raw[0:1] == b"#":
            len_of_len = int(chr(raw[1]))
            header_len = 2 + len_of_len

        raw_data = raw[header_len:-1]
        data_int = np.frombuffer(raw_data, dtype=np.int8)
        voltage = data_int * (vdiv / 25.0) - voffset

        num_points = len(voltage)
        if sara <= 0:
            sara = 1.0
        time_axis = np.linspace(0, num_points / sara, num_points)

        return time_axis, voltage, sara

    def fetch_waveform(self, channel: int = 1) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], float]:
        """Convenience method: arm trigger and fetch waveform synchronously."""
        if self.start_acquisition():
            return self.retrieve_waveform(channel)
        return None, None, 1.0

    def measure_mean(self, channel: int = 1) -> float:
        """Measure average voltage on specified channel."""
        try:
            res = self.query(f"C{channel}:PAVA? MEAN")
            # Result format like 'C1:PAVA MEAN,1.234V'
            val_str = res.split(",")[-1].replace("V", "").strip()
            return float(val_str)
        except Exception as e:
            self.logger.warning(f"PAVA MEAN failed: {e}. Falling back to waveform calculation.")
            _, v, _ = self.fetch_waveform(channel)
            return float(np.mean(v)) if v is not None and len(v) > 0 else 0.0
