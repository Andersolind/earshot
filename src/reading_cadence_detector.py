"""
GNU-Larex :: Reading Cadence Detector Module (`reading_cadence_detector.py`)
============================================================================
Canonical import path for `SilentReadingDetector` used by `ThreeStateVADRouter`:

    from reading_cadence_detector import SilentReadingDetector
"""

from __future__ import annotations

try:
    from .larex_reading_piggyback import SilentReadingDetector
except ImportError:
    from larex_reading_piggyback import SilentReadingDetector

__all__ = ["SilentReadingDetector"]
