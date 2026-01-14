"""
Falcon Screener - Multi-Profile Stock Screening Service

Multi-profile screener system with database-driven configuration,
YAML import/export, and auto-adjusting weights based on performance.
"""

from falcon_screener.profile_manager import ProfileManager, ScreenerProfile
from falcon_screener.yaml_serializer import ProfileYAMLSerializer
from falcon_screener.multi_screener import MultiScreener
from falcon_screener.feedback_loop import WeightFeedbackLoop

__version__ = "0.1.0"
__all__ = [
    'ProfileManager',
    'ScreenerProfile',
    'ProfileYAMLSerializer',
    'MultiScreener',
    'WeightFeedbackLoop',
]
