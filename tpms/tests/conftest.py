"""
Pytest configuration for TPMS tests.
Ensures TPMS root directory is correctly resolved in sys.path.
Author: mozial
"""

import os
import sys

tpms_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if tpms_root not in sys.path:
    sys.path.insert(0, tpms_root)
