"""DC Power Supply Driver for Rigol DP2000 series (e.g. DP2031).

Features:
- Voltage and current setpoints per channel
- Over-Voltage Protection (OVP) and Over-Current Protection (OCP)
- Independent output control per channel
- Output voltage and current measurement queries
- Context manager support with safety shutdown on exit

Author: mozial
"""

from typing import Optional
from drivers.base_instrument import BaseInstrument


class DP2031Driver(BaseInstrument):
    """Driver for Rigol DP2031 Programmable Linear DC Power Supply."""

    def __init__(
        self,
        resource_name: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 5555,
        timeout_ms: int = 5000,
    ):
        super().__init__(
            name="DP2031",
            resource_name=resource_name,
            host=host,
            port=port,
            timeout_ms=timeout_ms,
        )

    def set_voltage_current(self, voltage: float, current_limit: float, channel: int = 1):
        """Set output voltage and current limit on specified channel."""
        self.write(f":APPL CH{channel},{voltage:.4f},{current_limit:.4f}")
        self.logger.info(f"CH{channel} set to {voltage:.3f}V, limit={current_limit:.3f}A")

    def set_protections(self, ovp_val: float, ocp_val: float, channel: int = 1):
        """Set Over-Voltage (OVP) and Over-Current (OCP) trip points."""
        self.write(f":OUTP:OVP:VAL CH{channel},{ovp_val:.3f}")
        self.write(f":OUTP:OVP CH{channel},ON")
        self.write(f":OUTP:OCP:VAL CH{channel},{ocp_val:.3f}")
        self.write(f":OUTP:OCP CH{channel},ON")
        self.logger.info(f"CH{channel} protections armed: OVP={ovp_val}V, OCP={ocp_val}A")

    def output_on(self, channel: int = 1):
        """Enable channel output."""
        self.write(f":OUTP CH{channel},ON")
        self.logger.info(f"CH{channel} output ENABLED")

    def output_off(self, channel: int = 1):
        """Disable channel output."""
        self.write(f":OUTP CH{channel},OFF")
        self.logger.info(f"CH{channel} output DISABLED")

    def is_output_on(self, channel: int = 1) -> bool:
        """Query if specified channel output is currently enabled."""
        res = self.query(f":OUTP? CH{channel}").upper()
        return "ON" in res or res == "1"

    def measure_voltage(self, channel: int = 1) -> float:
        """Measure actual output voltage on channel."""
        return float(self.query(f":MEAS:VOLT? CH{channel}"))

    def measure_current(self, channel: int = 1) -> float:
        """Measure actual output current on channel."""
        return float(self.query(f":MEAS:CURR? CH{channel}"))

    def close(self):
        """Turn off active outputs before closing session for safety."""
        if self._is_connected:
            try:
                for ch in (1, 2, 3):
                    try:
                        self.output_off(ch)
                    except Exception:
                        pass
            except Exception:
                pass
        super().close()
