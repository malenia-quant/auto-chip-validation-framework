"""Integration test verifying driver encapsulation, mock operations and limits.

Author: mozial
"""

import pytest
from drivers.exceptions import InstrumentConnectionError
from drivers.power_supply_dp2031 import DP2031Driver


def test_driver_connection_guard():
    """Verify that writing to a closed instrument immediately raises InstrumentConnectionError."""
    drv = DP2031Driver(resource_name=None)
    with pytest.raises(InstrumentConnectionError):
        drv.write("*IDN?")


def test_test_profile_loading(test_config):
    """Verify test_profile.yaml is successfully loaded with required instruments and limits."""
    assert "instruments" in test_config
    assert "generator" in test_config["instruments"]
    assert "power_supply" in test_config["instruments"]
    assert "oscilloscope" in test_config["instruments"]
    assert "test_limits" in test_config
    assert "supply_voltage_vdd" in test_config["test_limits"]
    assert test_config["test_limits"]["supply_voltage_vdd"]["min"] == 4.0
