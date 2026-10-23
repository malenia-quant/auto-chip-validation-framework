"""Digital Multimeter Driver for Keithley DMM6500 / Standard SCPI DMMs.

Features:
- DC Voltage (DCV) and AC Voltage (ACV) measurement
- 2-Wire (RES) and 4-Wire (FRES) high-precision resistance measurement
- DC Current (DCI) and AC Current (ACI) measurement
- Integration time (NPLC) and auto-ranging configuration
- Context manager support

Author: mozial
"""

from typing import Optional
from drivers.base_instrument import BaseInstrument


class DMM6500Driver(BaseInstrument):
    """Driver for Keithley DMM6500 6.5-digit Multimeter."""

    def __init__(
        self,
        resource_name: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 5025,
        timeout_ms: int = 5000,
    ):
        super().__init__(
            name="DMM6500",
            resource_name=resource_name,
            host=host,
            port=port,
            timeout_ms=timeout_ms,
        )

    def _post_connect(self):
        self.clear_status()

    def setup_resistance(self, four_wire: bool = True, nplc: float = 10.0, auto_range: bool = True):
        """Configure multimeter for resistance measurement."""
        func = "FRES" if four_wire else "RES"
        self.write(f'SENS:FUNC "{func}"')
        if auto_range:
            self.write(f"SENS:{func}:RANG:AUTO ON")
        self.write(f"SENS:{func}:NPLC {nplc}")
        self.logger.info(f"DMM Resistance mode set: {func}, NPLC={nplc}, AutoRange={auto_range}")

    def setup_voltage_dc(self, nplc: float = 10.0, auto_range: bool = True):
        """Configure multimeter for DC voltage measurement."""
        self.write('SENS:FUNC "VOLT:DC"')
        if auto_range:
            self.write("SENS:VOLT:DC:RANG:AUTO ON")
        self.write(f"SENS:VOLT:DC:NPLC {nplc}")
        self.logger.info(f"DMM DC Voltage mode set: NPLC={nplc}, AutoRange={auto_range}")

    def setup_current_dc(self, nplc: float = 10.0, auto_range: bool = True):
        """Configure multimeter for DC current measurement."""
        self.write('SENS:FUNC "CURR:DC"')
        if auto_range:
            self.write("SENS:CURR:DC:RANG:AUTO ON")
        self.write(f"SENS:CURR:DC:NPLC {nplc}")
        self.logger.info(f"DMM DC Current mode set: NPLC={nplc}, AutoRange={auto_range}")

    def measure(self) -> float:
        """Trigger and read a single measurement."""
        val_str = self.query("READ?")
        return float(val_str)
