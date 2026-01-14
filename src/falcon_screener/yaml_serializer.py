#!/usr/bin/env python3
"""
YAML Serializer for Screener Profiles

Provides import/export functionality for screener profiles in YAML format.
Enables version control and easy sharing of profile configurations.
"""

import yaml
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from screener.profile_manager import ScreenerProfile, ProfileManager


class ProfileYAMLSerializer:
    """
    Export/import screener profiles as YAML

    Provides human-readable serialization of profile configurations
    for version control, backup, and sharing.
    """

    # YAML header comment
    HEADER = """# Falcon Trading Platform - Screener Profiles
# Generated: {timestamp}
#
# This file contains screener profile configurations.
# You can edit this file and re-import to update profiles.
#
# Available themes: momentum, earnings, seasonal
# Schedule options: morning (4AM), midday (9AM-12PM), evening (7PM)

"""

    @staticmethod
    def export_profile(profile: ScreenerProfile) -> Dict[str, Any]:
        """
        Export a single profile to a dictionary suitable for YAML

        Args:
            profile: ScreenerProfile to export

        Returns:
            Dictionary representation of the profile
        """
        return {
            'name': profile.name,
            'description': profile.description,
            'theme': profile.theme,
            'finviz_url': profile.finviz_url if profile.finviz_url else None,
            'finviz_filters': profile.finviz_filters if profile.finviz_filters else None,
            'sector_focus': profile.sector_focus if profile.sector_focus else None,
            'schedule': profile.schedule,
            'weights': profile.weights if profile.weights else None,
            'enabled': profile.enabled,
            'performance_score': round(profile.performance_score, 4) if profile.performance_score else 0.5,
        }

    @staticmethod
    def export_profiles(profiles: List[ScreenerProfile]) -> str:
        """
        Export multiple profiles to YAML string

        Args:
            profiles: List of ScreenerProfiles to export

        Returns:
            YAML string representation
        """
        data = {
            'version': '1.0',
            'exported_at': datetime.now().isoformat(),
            'profiles': [
                ProfileYAMLSerializer.export_profile(p) for p in profiles
            ]
        }

        header = ProfileYAMLSerializer.HEADER.format(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )

        # Use safe_dump with nice formatting
        yaml_content = yaml.safe_dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

        return header + yaml_content

    @staticmethod
    def import_profile(profile_dict: Dict[str, Any]) -> ScreenerProfile:
        """
        Import a single profile from a dictionary

        Args:
            profile_dict: Dictionary representation of a profile

        Returns:
            ScreenerProfile instance
        """
        return ScreenerProfile(
            name=profile_dict['name'],
            description=profile_dict.get('description', ''),
            theme=profile_dict['theme'],
            finviz_url=profile_dict.get('finviz_url', ''),
            finviz_filters=profile_dict.get('finviz_filters') or {},
            sector_focus=profile_dict.get('sector_focus') or [],
            schedule=profile_dict.get('schedule', {
                'morning': True,
                'midday': False,
                'evening': False,
            }),
            weights=profile_dict.get('weights') or {},
            enabled=profile_dict.get('enabled', True),
            performance_score=profile_dict.get('performance_score', 0.5),
        )

    @staticmethod
    def import_profiles(yaml_content: str) -> List[ScreenerProfile]:
        """
        Import profiles from YAML string

        Args:
            yaml_content: YAML string content

        Returns:
            List of ScreenerProfile instances
        """
        data = yaml.safe_load(yaml_content)

        if not data or 'profiles' not in data:
            raise ValueError("Invalid YAML format: missing 'profiles' key")

        return [
            ProfileYAMLSerializer.import_profile(p)
            for p in data['profiles']
        ]

    @staticmethod
    def export_to_file(profiles: List[ScreenerProfile], filepath: str) -> None:
        """
        Export profiles to a YAML file

        Args:
            profiles: List of ScreenerProfiles to export
            filepath: Path to output file
        """
        yaml_content = ProfileYAMLSerializer.export_profiles(profiles)

        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)

        with open(filepath, 'w') as f:
            f.write(yaml_content)

        print(f"[YAML] Exported {len(profiles)} profiles to {filepath}")

    @staticmethod
    def import_from_file(filepath: str) -> List[ScreenerProfile]:
        """
        Import profiles from a YAML file

        Args:
            filepath: Path to input file

        Returns:
            List of ScreenerProfile instances
        """
        with open(filepath, 'r') as f:
            yaml_content = f.read()

        profiles = ProfileYAMLSerializer.import_profiles(yaml_content)
        print(f"[YAML] Imported {len(profiles)} profiles from {filepath}")

        return profiles

    @staticmethod
    def sync_to_database(profiles: List[ScreenerProfile],
                         manager: ProfileManager,
                         update_existing: bool = True) -> Dict[str, int]:
        """
        Sync imported profiles to database

        Args:
            profiles: List of profiles to sync
            manager: ProfileManager instance
            update_existing: If True, update existing profiles; if False, skip them

        Returns:
            Dict with counts: {'created': n, 'updated': n, 'skipped': n}
        """
        stats = {'created': 0, 'updated': 0, 'skipped': 0}

        for profile in profiles:
            existing = manager.get_profile_by_name(profile.name)

            if existing:
                if update_existing:
                    profile.id = existing.id
                    profile.created_at = existing.created_at
                    manager.update_profile(profile)
                    stats['updated'] += 1
                    print(f"[YAML] Updated profile: {profile.name}")
                else:
                    stats['skipped'] += 1
                    print(f"[YAML] Skipped existing profile: {profile.name}")
            else:
                manager.create_profile(profile)
                stats['created'] += 1
                print(f"[YAML] Created profile: {profile.name}")

        return stats

    @staticmethod
    def export_from_database(manager: ProfileManager,
                             filepath: str,
                             enabled_only: bool = False) -> int:
        """
        Export all profiles from database to YAML file

        Args:
            manager: ProfileManager instance
            filepath: Path to output file
            enabled_only: Only export enabled profiles

        Returns:
            Number of profiles exported
        """
        profiles = manager.list_profiles(enabled_only=enabled_only)
        ProfileYAMLSerializer.export_to_file(profiles, filepath)
        return len(profiles)


# Default YAML file path
DEFAULT_YAML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'screener_profiles.yaml'
)


if __name__ == '__main__':
    import sys

    print("YAML Serializer Test")
    print("=" * 50)

    # Test with sample profiles
    from screener.profile_templates import DEFAULT_PROFILES

    # Export to string
    yaml_str = ProfileYAMLSerializer.export_profiles(DEFAULT_PROFILES)
    print("\nExported YAML:")
    print("-" * 50)
    print(yaml_str[:1000] + "..." if len(yaml_str) > 1000 else yaml_str)

    # Import back
    imported = ProfileYAMLSerializer.import_profiles(yaml_str)
    print(f"\nImported {len(imported)} profiles:")
    for p in imported:
        print(f"  - {p.name} ({p.theme})")

    # Test file export/import
    test_file = '/tmp/test_screener_profiles.yaml'
    ProfileYAMLSerializer.export_to_file(DEFAULT_PROFILES, test_file)

    reimported = ProfileYAMLSerializer.import_from_file(test_file)
    print(f"\nReimported {len(reimported)} profiles from file")

    # Verify round-trip
    for orig, reimp in zip(DEFAULT_PROFILES, reimported):
        assert orig.name == reimp.name, f"Name mismatch: {orig.name} vs {reimp.name}"
        assert orig.theme == reimp.theme, f"Theme mismatch"
        print(f"  [OK] {orig.name}")

    # Cleanup
    os.remove(test_file)
    print("\n[SUCCESS] YAML serialization test passed!")
