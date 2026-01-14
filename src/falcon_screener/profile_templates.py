#!/usr/bin/env python3
"""
Default Screener Profile Templates

Provides pre-configured screener profiles for common trading themes:
- Momentum/Breakouts: High-volume breakout candidates
- Earnings Plays: Stocks with upcoming/recent earnings
- Seasonal/Sector Rotation: Sector-based seasonal patterns
"""

from typing import List, Dict
from .profile_manager import ScreenerProfile, ProfileManager


# Momentum/Breakouts Profile
MOMENTUM_BREAKOUT_PROFILE = ScreenerProfile(
    name="Momentum Breakouts",
    description="High-volume breakout candidates with strong 5-minute momentum and volume confirmation",
    theme="momentum",
    finviz_url="",  # Will be built from filters
    finviz_filters={
        "sh_avgvol_o750": True,      # Average volume > 750K
        "sh_price_u20": True,         # Price under $20
        "sh_relvol_o1.5": True,       # Relative volume > 1.5x
        "ta_change_u": True,          # Change up
    },
    sector_focus=["Technology", "Consumer Cyclical", "Healthcare"],
    schedule={
        "morning": True,
        "midday": True,
        "evening": False,
    },
    weights={
        "performance_5min": 0.35,
        "relative_volume": 0.30,
        "sector_match": 0.15,
        "rsi_oversold": 0.20,
    },
    enabled=True,
)


# Earnings Plays Profile
EARNINGS_PLAYS_PROFILE = ScreenerProfile(
    name="Earnings Plays",
    description="Stocks with upcoming earnings or recent earnings surprises - focus on reaction setups",
    theme="earnings",
    finviz_url="",
    finviz_filters={
        "sh_avgvol_o500": True,       # Average volume > 500K
        "sh_price_u50": True,         # Price under $50
        "earningsdate_thisweek": True,  # Earnings this week (Finviz filter)
    },
    sector_focus=[],  # All sectors - earnings are cross-sector
    schedule={
        "morning": True,
        "midday": False,
        "evening": True,  # Review after-hours reactions
    },
    weights={
        "earnings_proximity": 0.40,
        "historical_reaction": 0.25,
        "analyst_surprise": 0.20,
        "volume_pattern": 0.15,
    },
    enabled=True,
)


# Seasonal/Sector Rotation Profile
SEASONAL_ROTATION_PROFILE = ScreenerProfile(
    name="Seasonal Sector Rotation",
    description="Sector-based plays following seasonal patterns - energy in winter, retail in Q4, etc.",
    theme="seasonal",
    finviz_url="",
    finviz_filters={
        "sh_avgvol_o1000": True,      # Average volume > 1M (more liquid)
        "cap_midover": True,          # Mid-cap and above
        "sh_price_u100": True,        # Price under $100
    },
    sector_focus=[],  # Dynamically adjusted based on season
    schedule={
        "morning": True,
        "midday": False,
        "evening": True,
    },
    weights={
        "sector_momentum": 0.35,
        "seasonal_alignment": 0.30,
        "relative_strength": 0.20,
        "fund_flow": 0.15,
    },
    enabled=True,
)


# All default profiles
DEFAULT_PROFILES = [
    MOMENTUM_BREAKOUT_PROFILE,
    EARNINGS_PLAYS_PROFILE,
    SEASONAL_ROTATION_PROFILE,
]


# Seasonal sector focus by month
SEASONAL_SECTOR_MAP = {
    1: ["Technology", "Healthcare"],           # January effect, new year tech optimism
    2: ["Consumer Cyclical", "Healthcare"],    # Valentine's, healthcare conferences
    3: ["Industrials", "Basic Materials"],     # Spring construction, infrastructure
    4: ["Technology", "Consumer Cyclical"],    # Earnings season, spring retail
    5: ["Energy", "Basic Materials"],          # Summer driving season begins
    6: ["Consumer Defensive", "Utilities"],    # Defensive rotation mid-year
    7: ["Technology", "Healthcare"],           # Mid-year tech, biotech conferences
    8: ["Consumer Cyclical", "Technology"],    # Back to school, tech releases
    9: ["Healthcare", "Technology"],           # Healthcare conferences, tech events
    10: ["Consumer Cyclical", "Technology"],   # Holiday preview, tech launches
    11: ["Consumer Cyclical", "Retail"],       # Black Friday, holiday shopping
    12: ["Consumer Cyclical", "Technology"],   # Holiday season, tax-loss harvesting end
}


def get_current_seasonal_sectors() -> List[str]:
    """Get recommended sectors based on current month"""
    import datetime
    current_month = datetime.datetime.now().month
    return SEASONAL_SECTOR_MAP.get(current_month, ["Technology", "Healthcare"])


def update_seasonal_profile_sectors(profile: ScreenerProfile) -> ScreenerProfile:
    """Update seasonal profile with current month's sectors"""
    if profile.theme == "seasonal":
        profile.sector_focus = get_current_seasonal_sectors()
    return profile


def initialize_default_profiles(manager: ProfileManager, force: bool = False) -> List[int]:
    """
    Initialize database with default profiles

    Args:
        manager: ProfileManager instance
        force: If True, recreate existing profiles

    Returns:
        List of created profile IDs
    """
    created_ids = []

    for profile in DEFAULT_PROFILES:
        existing = manager.get_profile_by_name(profile.name)

        if existing:
            if force:
                manager.delete_profile(existing.id)
                print(f"[PROFILES] Deleted existing profile: {profile.name}")
            else:
                print(f"[PROFILES] Profile already exists: {profile.name}")
                created_ids.append(existing.id)
                continue

        # Update seasonal sectors if applicable
        if profile.theme == "seasonal":
            profile = update_seasonal_profile_sectors(profile)

        profile_id = manager.create_profile(profile)
        created_ids.append(profile_id)
        print(f"[PROFILES] Created profile: {profile.name} (id={profile_id})")

    return created_ids


def get_profile_for_theme(theme: str) -> ScreenerProfile:
    """
    Get the default profile for a theme

    Args:
        theme: 'momentum', 'earnings', or 'seasonal'

    Returns:
        ScreenerProfile for the theme
    """
    theme_map = {
        'momentum': MOMENTUM_BREAKOUT_PROFILE,
        'earnings': EARNINGS_PLAYS_PROFILE,
        'seasonal': SEASONAL_ROTATION_PROFILE,
    }

    profile = theme_map.get(theme.lower())
    if not profile:
        raise ValueError(f"Unknown theme: {theme}. Valid: momentum, earnings, seasonal")

    # Update seasonal sectors if applicable
    if profile.theme == "seasonal":
        profile = update_seasonal_profile_sectors(profile)

    return profile


if __name__ == '__main__':
    import os
    import sys

    # Add parent to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db_manager import get_db_manager

    print("Profile Templates - Initialization")
    print("=" * 50)

    # Use production database
    db = get_db_manager()
    db.init_schema()

    manager = ProfileManager(db)

    # Initialize default profiles
    print("\nInitializing default profiles...")
    created = initialize_default_profiles(manager, force='--force' in sys.argv)

    print(f"\nCreated/found {len(created)} profiles")

    # List all profiles
    print("\nAll profiles:")
    for profile in manager.list_profiles():
        print(f"  - {profile.name} ({profile.theme})")
        print(f"    Enabled: {profile.enabled}")
        print(f"    Schedule: {profile.schedule}")
        if profile.sector_focus:
            print(f"    Sectors: {', '.join(profile.sector_focus)}")

    # Show current seasonal recommendation
    print(f"\nCurrent seasonal sectors: {get_current_seasonal_sectors()}")
