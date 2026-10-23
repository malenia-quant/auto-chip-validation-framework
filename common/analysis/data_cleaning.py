"""Data quality analysis, outlier detection, and statistical reporting.

Author: mozial
"""

import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd


class DataConsolidator:
    """Consolidates measurement sweeps, detects anomalies and generates test summary metrics."""

    def __init__(self):
        self.logger = logging.getLogger("Analysis.Consolidator")

    @staticmethod
    def detect_outliers_iqr(series: pd.Series, factor: float = 1.5) -> pd.Series:
        """Identify outliers using the Interquartile Range (IQR) technique."""
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - factor * iqr
        upper_bound = q3 + factor * iqr
        return (series < lower_bound) | (series > upper_bound)

    @staticmethod
    def calculate_summary_stats(data: List[float]) -> Dict[str, float]:
        """Compute mean, std, min, max, span, and RMS for a given sample list."""
        arr = np.array(data, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) == 0:
            return {"count": 0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "rms": 0.0}

        return {
            "count": int(len(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "span": float(np.max(arr) - np.min(arr)),
            "rms": float(np.sqrt(np.mean(arr ** 2))),
        }
