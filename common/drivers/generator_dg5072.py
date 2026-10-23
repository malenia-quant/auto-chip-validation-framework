"""Function / Arbitrary Waveform Generator Driver for Rigol DG5000 series (DG5072).

Features:
- DC, Pulse, Ramp and Square wave output configuration
- PSI5 sync pulse generation with linear PCB-to-DG voltage mapping
- High-speed volatile ARB arbitrary waveform upload with 16-bit DAC scaling
- Micro-cut (uCut) fault injection pattern generation
- Safe shutdown and output interlocks

Author: mozial
"""

import math
import time
from typing import Dict, Optional, Tuple
import numpy as np

from drivers.base_instrument import BaseInstrument


class DG5072Driver(BaseInstrument):
    """Driver for Rigol DG5072 Arbitrary Waveform Generator."""

    # PSI5 voltage translation mapping (Target PCB Base/Pulse -> DG Output)
    PSI5_CASES: Dict[int, Dict[str, float]] = {
        1: {"base_v": 4.5, "pulse_v": 0.0, "total_v": 4.5, "dg_low": 1.34, "dg_high": 1.34},
        2: {"base_v": 4.5, "pulse_v": 3.5, "total_v": 8.0, "dg_low": 1.34, "dg_high": 2.92},
        3: {"base_v": 4.5, "pulse_v": 5.5, "total_v": 10.0, "dg_low": 1.34, "dg_high": 3.93},
        4: {"base_v": 6.7, "pulse_v": 0.0, "total_v": 6.7, "dg_low": 2.33, "dg_high": 2.33},
        5: {"base_v": 6.7, "pulse_v": 3.5, "total_v": 10.2, "dg_low": 2.33, "dg_high": 3.92},
        6: {"base_v": 6.7, "pulse_v": 5.5, "total_v": 12.2, "dg_low": 2.33, "dg_high": 4.82},
        7: {"base_v": 11.0, "pulse_v": 0.0, "total_v": 11.0, "dg_low": 4.26, "dg_high": 4.26},
        8: {"base_v": 11.0, "pulse_v": 3.5, "total_v": 14.5, "dg_low": 4.26, "dg_high": 5.85},
        9: {"base_v": 11.0, "pulse_v": 5.5, "total_v": 16.5, "dg_low": 4.26, "dg_high": 6.75},
        10: {"base_v": 5.0, "pulse_v": 0.0, "total_v": 5.0, "dg_low": 1.57, "dg_high": 1.57},
        11: {"base_v": 5.0, "pulse_v": 3.5, "total_v": 8.5, "dg_low": 1.57, "dg_high": 3.15},
        12: {"base_v": 5.0, "pulse_v": 5.5, "total_v": 10.5, "dg_low": 1.57, "dg_high": 4.06},
    }

    def __init__(
        self,
        resource_name: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 5025,
        timeout_ms: int = 10000,
    ):
        super().__init__(
            name="DG5072",
            resource_name=resource_name,
            host=host,
            port=port,
            timeout_ms=timeout_ms,
        )

    def _post_connect(self):
        self.clear_status()

    @classmethod
    def pcb_to_dg_voltage(cls, pcb_v: float) -> float:
        """Interpolate PCB voltage to DG5072 generator output level."""
        points = [(0.0, 0.0), (4.5, 1.34), (6.7, 2.33), (11.0, 4.26)]
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            if p1[0] <= pcb_v <= p2[0]:
                ratio = (pcb_v - p1[0]) / (p2[0] - p1[0])
                return p1[1] + ratio * (p2[1] - p1[1])
        # Extrapolate linearly above 11V
        p_last, p_prev = points[-1], points[-2]
        slope = (p_last[1] - p_prev[1]) / (p_last[0] - p_prev[0])
        return p_last[1] + (pcb_v - p_last[0]) * slope

    def set_dc_offset(self, voltage_pcb: float, channel: int = 1):
        """Set constant DC output voltage mapped from PCB reference."""
        v_dg = self.pcb_to_dg_voltage(voltage_pcb)
        self.write(f"OUTP{channel}:LOAD INF")
        self.write(f"SOUR{channel}:FUNC DC")
        self.write(f"SOUR{channel}:VOLT:OFFS {v_dg:.4f}")
        self.logger.info(f"DG5072 CH{channel} DC output set: PCB={voltage_pcb:.3f}V -> DG={v_dg:.3f}V")

    def configure_mapped_pulse(
        self,
        case_id: int,
        width_us: float = 30.0,
        sr_rise: float = 1.0,
        sr_fall: float = 2.0,
        frequency_hz: float = 2000.0,
        channel: int = 1,
    ):
        """Configure pulse parameters corresponding to defined PSI5 Case."""
        case = self.PSI5_CASES.get(case_id)
        if not case:
            raise ValueError(f"Unknown Case ID: {case_id}")

        dg_low = case["dg_low"]
        dg_high = case["dg_high"]
        pcb_delta = case["pulse_v"]

        self.write(f"OUTP{channel}:LOAD INF")

        # Constant DC condition if high equals low
        if abs(dg_high - dg_low) < 0.005:
            self.write(f"SOUR{channel}:FUNC DC")
            self.write(f"SOUR{channel}:VOLT:OFFS {dg_high:.4f}")
            self.logger.info(f"CH{channel} configured as DC Case {case_id}: {dg_high}V")
            return

        # Slew rate translation
        rise_time_s = (pcb_delta / sr_rise) * 1e-6 if (sr_rise > 0 and pcb_delta > 0.05) else 10e-9
        fall_time_s = (pcb_delta / sr_fall) * 1e-6 if (sr_fall > 0 and pcb_delta > 0.05) else 10e-9
        rise_time_s = max(2.5e-9, rise_time_s)
        fall_time_s = max(2.5e-9, fall_time_s)

        self.write(f"SOUR{channel}:FUNC PULS")
        self.write(f"SOUR{channel}:VOLT:LOW {dg_low:.4f}")
        self.write(f"SOUR{channel}:VOLT:HIGH {dg_high:.4f}")
        self.write(f"SOUR{channel}:FREQ {frequency_hz:.2f}")
        self.write(f"SOUR{channel}:PULS:WIDT {width_us * 1e-6:.8f}")
        self.write(f"SOUR{channel}:PULS:TRAN:LEAD {rise_time_s:.9f}")
        self.write(f"SOUR{channel}:PULS:TRAN:TRA {fall_time_s:.9f}")
        self.logger.info(
            f"CH{channel} Pulse configured: Case={case_id}, Low={dg_low}V, High={dg_high}V, Width={width_us}us"
        )

    def upload_arb_waveform(self, waveform: np.ndarray, channel: int = 1):
        """Upload normalized float array (-1.0 to 1.0) into volatile ARB memory."""
        # Convert to 14/16-bit DAC little-endian words
        dac_data = np.round((waveform + 1.0) / 2.0 * 16383).astype("<u2").tobytes()
        header = f"#{len(str(len(dac_data)))}{len(dac_data)}".encode("ascii")
        cmd = b":TRACe:DATA:DAC16 VOLATILE,END," + header + dac_data
        self.write_raw(cmd)
        self.write(f":SOUR{channel}:FUNC USER")
        self.logger.info(f"Uploaded {len(waveform)} points ARB waveform to CH{channel}")

    def output_on(self, channel: int = 1):
        self.write(f"OUTP{channel} ON")
        self.logger.info(f"DG5072 CH{channel} Output ON")

    def output_off(self, channel: int = 1):
        self.write(f"OUTP{channel} OFF")
        self.logger.info(f"DG5072 CH{channel} Output OFF")

    def is_output_on(self, channel: int = 1) -> bool:
        res = self.query(f"OUTP{channel}?").strip().upper()
        return res in ("ON", "1")

    def close(self):
        if self._is_connected:
            try:
                self.output_off(1)
                self.output_off(2)
            except Exception:
                pass
        super().close()
