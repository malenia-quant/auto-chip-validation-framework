"""Pytest Fixtures and Hardware Session Management.

Provides session-scoped instrument connections with safety interlocks and teardown.
Author: mozial
"""

import logging
import os
import sys
import pytest

common_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if common_root not in sys.path:
    sys.path.insert(0, common_root)

from config.loader import load_profile
from drivers.dmm_keithley6500 import DMM6500Driver
from drivers.generator_dg5072 import DG5072Driver
from drivers.power_supply_dp2031 import DP2031Driver
from drivers.scope_sds5054 import SDS5054Driver

# Configure logging inside common/logs
log_dir = os.path.join(common_root, "logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "pytest_execution.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


@pytest.fixture(scope="session")
def test_config():
    """Load session test configuration profile."""
    return load_profile()


@pytest.fixture(scope="session")
def mock_mode(request):
    """Check if tests are running in mock/simulation mode."""
    return request.config.getoption("--mock", default=True)


def pytest_addoption(parser):
    """Add command line options to pytest."""
    parser.addoption(
        "--mock",
        action="store_true",
        default=True,
        help="Run tests in mock hardware mode (no physical instruments needed)",
    )
    parser.addoption(
        "--live",
        action="store_false",
        dest="mock",
        help="Run tests against live physical instruments",
    )


@pytest.fixture(scope="session")
def generator(test_config, mock_mode):
    """Provide session-scoped DG5072 waveform generator driver."""
    cfg = test_config["instruments"]["generator"]
    if mock_mode:
        logging.getLogger("Fixture.DG5072").info("Mock Mode: Providing mock DG5072 generator.")
        dg = DG5072Driver(resource_name=None, host="localhost", port=5025)
        # Mocking connection
        dg._is_connected = True
        yield dg
        dg._is_connected = False
    else:
        with DG5072Driver(resource_name=cfg.get("visa_resource"), host=cfg.get("tcp_host"), port=cfg.get("tcp_port")) as dg:
            yield dg


@pytest.fixture(scope="session")
def power_supply(test_config, mock_mode):
    """Provide session-scoped DP2031 DC power supply driver with safety shutdown."""
    cfg = test_config["instruments"]["power_supply"]
    if mock_mode:
        logging.getLogger("Fixture.DP2031").info("Mock Mode: Providing mock DP2031 power supply.")
        ps = DP2031Driver(resource_name=None, host="localhost", port=5555)
        ps._is_connected = True
        yield ps
        ps._is_connected = False
    else:
        with DP2031Driver(resource_name=cfg.get("visa_resource"), host=cfg.get("tcp_host"), port=cfg.get("tcp_port")) as ps:
            yield ps


@pytest.fixture(scope="session")
def oscilloscope(test_config, mock_mode):
    """Provide session-scoped SDS5054X oscilloscope driver."""
    cfg = test_config["instruments"]["oscilloscope"]
    if mock_mode:
        logging.getLogger("Fixture.SDS5054").info("Mock Mode: Providing mock SDS5054 oscilloscope.")
        scope = SDS5054Driver(resource_name=None, host="localhost", port=5025)
        scope._is_connected = True
        yield scope
        scope._is_connected = False
    else:
        with SDS5054Driver(resource_name=cfg.get("visa_resource"), host=cfg.get("tcp_host"), port=cfg.get("tcp_port")) as scope:
            yield scope


@pytest.fixture(scope="session")
def multimeter(test_config, mock_mode):
    """Provide session-scoped Keithley DMM6500 driver."""
    cfg = test_config["instruments"]["multimeter"]
    if mock_mode:
        logging.getLogger("Fixture.DMM6500").info("Mock Mode: Providing mock DMM6500 multimeter.")
        dmm = DMM6500Driver(resource_name=None, host="localhost", port=5025)
        dmm._is_connected = True
        yield dmm
        dmm._is_connected = False
    else:
        with DMM6500Driver(resource_name=cfg.get("visa_resource"), host=cfg.get("tcp_host"), port=cfg.get("tcp_port")) as dmm:
            yield dmm
