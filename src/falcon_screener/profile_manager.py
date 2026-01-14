#!/usr/bin/env python3
"""
Screener Profile Manager

Manages screener profiles in the database with CRUD operations.
Supports SQLite and PostgreSQL through the db_manager abstraction.
"""

import json
import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import logging
import sys
import os

# Import from falcon-core package
from falcon_core import DatabaseManager, get_db_manager

logger = logging.getLogger(__name__)


@dataclass
class ScreenerProfile:
    """Dataclass representing a screener profile"""
    name: str
    theme: str  # 'momentum', 'earnings', 'seasonal'
    description: str = ""
    finviz_url: str = ""
    finviz_filters: Dict[str, Any] = field(default_factory=dict)
    sector_focus: List[str] = field(default_factory=list)
    schedule: Dict[str, bool] = field(default_factory=lambda: {
        "morning": True,
        "midday": False,
        "evening": False
    })
    enabled: bool = True
    weights: Dict[str, float] = field(default_factory=dict)
    performance_score: float = 0.5
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'theme': self.theme,
            'finviz_url': self.finviz_url,
            'finviz_filters': self.finviz_filters,
            'sector_focus': self.sector_focus,
            'schedule': self.schedule,
            'enabled': self.enabled,
            'weights': self.weights,
            'performance_score': self.performance_score,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScreenerProfile':
        """Create from dictionary"""
        return cls(
            id=data.get('id'),
            name=data['name'],
            description=data.get('description', ''),
            theme=data['theme'],
            finviz_url=data.get('finviz_url', ''),
            finviz_filters=data.get('finviz_filters', {}),
            sector_focus=data.get('sector_focus', []),
            schedule=data.get('schedule', {"morning": True, "midday": False, "evening": False}),
            enabled=data.get('enabled', True),
            weights=data.get('weights', {}),
            performance_score=data.get('performance_score', 0.5),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
        )

    def build_finviz_url(self) -> str:
        """Build Finviz URL from filters if not explicitly set"""
        if self.finviz_url:
            return self.finviz_url

        # Build URL from finviz_filters
        base_url = "https://finviz.com/screener.ashx"
        filters = []
        for key, value in self.finviz_filters.items():
            if value is True:
                filters.append(key)
            elif isinstance(value, str):
                filters.append(f"{key}_{value}")

        filter_str = ",".join(filters) if filters else ""
        return f"{base_url}?v=111&f={filter_str}" if filter_str else f"{base_url}?v=111"


class ProfileManager:
    """
    Manages screener profiles in the database

    Provides CRUD operations for screener profiles with support
    for both SQLite and PostgreSQL backends.
    """

    def __init__(self, db: Optional[DatabaseManager] = None):
        """
        Initialize ProfileManager

        Args:
            db: DatabaseManager instance. If None, creates one from environment.
        """
        self.db = db or get_db_manager()

    def _serialize_json(self, value: Any) -> str:
        """Serialize value to JSON string for SQLite"""
        if self.db.db_type == 'sqlite':
            return json.dumps(value) if value else '{}'
        return value  # PostgreSQL handles JSONB natively

    def _deserialize_json(self, value: Any) -> Any:
        """Deserialize JSON string from SQLite"""
        if self.db.db_type == 'sqlite' and isinstance(value, str):
            try:
                return json.loads(value) if value else {}
            except json.JSONDecodeError:
                return {}
        return value or {}

    def _row_to_profile(self, row: Any) -> ScreenerProfile:
        """Convert database row to ScreenerProfile"""
        if row is None:
            return None

        # Handle both dict-like (PostgreSQL) and tuple (SQLite) rows
        if hasattr(row, 'keys'):
            data = dict(row)
        else:
            # SQLite Row object - access by index or key
            data = {
                'id': row['id'],
                'name': row['name'],
                'description': row['description'],
                'theme': row['theme'],
                'finviz_url': row['finviz_url'],
                'finviz_filters': row['finviz_filters'],
                'sector_focus': row['sector_focus'],
                'schedule': row['schedule'],
                'enabled': row['enabled'],
                'weights': row['weights'],
                'performance_score': row['performance_score'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
            }

        # Deserialize JSON fields
        data['finviz_filters'] = self._deserialize_json(data.get('finviz_filters'))
        data['sector_focus'] = self._deserialize_json(data.get('sector_focus'))
        data['schedule'] = self._deserialize_json(data.get('schedule'))
        data['weights'] = self._deserialize_json(data.get('weights'))

        # Handle enabled as bool
        data['enabled'] = bool(data.get('enabled', True))

        return ScreenerProfile.from_dict(data)

    def create_profile(self, profile: ScreenerProfile) -> int:
        """
        Create a new screener profile

        Args:
            profile: ScreenerProfile to create

        Returns:
            ID of the created profile
        """
        now = datetime.datetime.now()
        timestamp = now.isoformat() if self.db.db_type == 'sqlite' else now

        sql = '''
            INSERT INTO screener_profiles
            (name, description, theme, finviz_url, finviz_filters, sector_focus,
             schedule, enabled, weights, performance_score, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''

        params = (
            profile.name,
            profile.description,
            profile.theme,
            profile.finviz_url or profile.build_finviz_url(),
            self._serialize_json(profile.finviz_filters),
            self._serialize_json(profile.sector_focus),
            self._serialize_json(profile.schedule),
            1 if profile.enabled else 0,
            self._serialize_json(profile.weights),
            profile.performance_score,
            timestamp,
            timestamp,
        )

        result = self.db.execute(sql, params)
        logger.info(f"Created profile: {profile.name} (id={result})")
        return result

    def get_profile(self, profile_id: int) -> Optional[ScreenerProfile]:
        """
        Get a profile by ID

        Args:
            profile_id: Profile ID

        Returns:
            ScreenerProfile or None if not found
        """
        sql = 'SELECT * FROM screener_profiles WHERE id = %s'
        row = self.db.execute(sql, (profile_id,), fetch='one')
        return self._row_to_profile(row)

    def get_profile_by_name(self, name: str) -> Optional[ScreenerProfile]:
        """
        Get a profile by name

        Args:
            name: Profile name

        Returns:
            ScreenerProfile or None if not found
        """
        sql = 'SELECT * FROM screener_profiles WHERE name = %s'
        row = self.db.execute(sql, (name,), fetch='one')
        return self._row_to_profile(row)

    def list_profiles(self, enabled_only: bool = False,
                      theme: Optional[str] = None) -> List[ScreenerProfile]:
        """
        List all profiles with optional filtering

        Args:
            enabled_only: Only return enabled profiles
            theme: Filter by theme ('momentum', 'earnings', 'seasonal')

        Returns:
            List of ScreenerProfiles
        """
        sql = 'SELECT * FROM screener_profiles WHERE 1=1'
        params = []

        if enabled_only:
            if self.db.db_type == 'sqlite':
                sql += ' AND enabled = %s'
                params.append(1)
            else:
                sql += ' AND enabled = %s'
                params.append(True)

        if theme:
            sql += ' AND theme = %s'
            params.append(theme)

        sql += ' ORDER BY name'

        rows = self.db.execute(sql, tuple(params) if params else None, fetch='all')
        return [self._row_to_profile(row) for row in rows] if rows else []

    def update_profile(self, profile: ScreenerProfile) -> bool:
        """
        Update an existing profile

        Args:
            profile: ScreenerProfile with updated values (must have id set)

        Returns:
            True if updated, False if not found
        """
        if not profile.id:
            raise ValueError("Profile must have an ID to update")

        now = datetime.datetime.now()
        timestamp = now.isoformat() if self.db.db_type == 'sqlite' else now

        sql = '''
            UPDATE screener_profiles
            SET name = %s, description = %s, theme = %s, finviz_url = %s,
                finviz_filters = %s, sector_focus = %s, schedule = %s,
                enabled = %s, weights = %s, performance_score = %s,
                updated_at = %s
            WHERE id = %s
        '''

        params = (
            profile.name,
            profile.description,
            profile.theme,
            profile.finviz_url or profile.build_finviz_url(),
            self._serialize_json(profile.finviz_filters),
            self._serialize_json(profile.sector_focus),
            self._serialize_json(profile.schedule),
            1 if profile.enabled else 0,
            self._serialize_json(profile.weights),
            profile.performance_score,
            timestamp,
            profile.id,
        )

        result = self.db.execute(sql, params)
        updated = result > 0 if isinstance(result, int) else True
        if updated:
            logger.info(f"Updated profile: {profile.name} (id={profile.id})")
        return updated

    def delete_profile(self, profile_id: int) -> bool:
        """
        Delete a profile by ID

        Args:
            profile_id: Profile ID to delete

        Returns:
            True if deleted, False if not found
        """
        sql = 'DELETE FROM screener_profiles WHERE id = %s'
        result = self.db.execute(sql, (profile_id,))
        deleted = result > 0 if isinstance(result, int) else True
        if deleted:
            logger.info(f"Deleted profile id={profile_id}")
        return deleted

    def get_active_profiles_for_schedule(self, run_type: str) -> List[ScreenerProfile]:
        """
        Get profiles that should run for a specific schedule time

        Args:
            run_type: 'morning', 'midday', or 'evening'

        Returns:
            List of active profiles for this schedule
        """
        all_profiles = self.list_profiles(enabled_only=True)
        return [
            p for p in all_profiles
            if p.schedule.get(run_type, False)
        ]

    def update_performance_score(self, profile_id: int, score: float) -> bool:
        """
        Update a profile's performance score

        Args:
            profile_id: Profile ID
            score: New performance score (0.0 to 1.0)

        Returns:
            True if updated
        """
        now = datetime.datetime.now()
        timestamp = now.isoformat() if self.db.db_type == 'sqlite' else now

        sql = '''
            UPDATE screener_profiles
            SET performance_score = %s, updated_at = %s
            WHERE id = %s
        '''
        result = self.db.execute(sql, (score, timestamp, profile_id))
        return result > 0 if isinstance(result, int) else True

    def update_weights(self, profile_id: int, weights: Dict[str, float]) -> bool:
        """
        Update a profile's weights

        Args:
            profile_id: Profile ID
            weights: New weights dictionary

        Returns:
            True if updated
        """
        now = datetime.datetime.now()
        timestamp = now.isoformat() if self.db.db_type == 'sqlite' else now

        sql = '''
            UPDATE screener_profiles
            SET weights = %s, updated_at = %s
            WHERE id = %s
        '''
        result = self.db.execute(sql, (self._serialize_json(weights), timestamp, profile_id))
        return result > 0 if isinstance(result, int) else True

    # Profile Run Methods

    def log_profile_run(self, profile_id: int, run_type: str,
                        stocks_found: int, recommendations: int,
                        ai_agent: str, run_data: Dict) -> int:
        """
        Log a profile screening run

        Args:
            profile_id: Profile ID that was run
            run_type: 'morning', 'midday', 'evening'
            stocks_found: Number of stocks found
            recommendations: Number of recommendations generated
            ai_agent: AI agent used ('claude', 'openai', 'perplexity')
            run_data: Full run data as dict

        Returns:
            Run ID
        """
        now = datetime.datetime.now()
        timestamp = now.isoformat() if self.db.db_type == 'sqlite' else now

        sql = '''
            INSERT INTO profile_runs
            (profile_id, run_type, stocks_found, recommendations_generated,
             run_timestamp, ai_agent_used, run_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        '''

        params = (
            profile_id,
            run_type,
            stocks_found,
            recommendations,
            timestamp,
            ai_agent,
            self._serialize_json(run_data),
        )

        return self.db.execute(sql, params)

    def get_profile_runs(self, profile_id: int, days: int = 30,
                         run_type: Optional[str] = None) -> List[Dict]:
        """
        Get recent runs for a profile

        Args:
            profile_id: Profile ID
            days: Number of days to look back
            run_type: Filter by run type

        Returns:
            List of run records
        """
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        cutoff_str = cutoff.isoformat() if self.db.db_type == 'sqlite' else cutoff

        sql = '''
            SELECT * FROM profile_runs
            WHERE profile_id = %s AND run_timestamp >= %s
        '''
        params = [profile_id, cutoff_str]

        if run_type:
            sql += ' AND run_type = %s'
            params.append(run_type)

        sql += ' ORDER BY run_timestamp DESC'

        rows = self.db.execute(sql, tuple(params), fetch='all')
        if not rows:
            return []

        results = []
        for row in rows:
            data = dict(row) if hasattr(row, 'keys') else {
                'id': row['id'],
                'profile_id': row['profile_id'],
                'run_type': row['run_type'],
                'stocks_found': row['stocks_found'],
                'recommendations_generated': row['recommendations_generated'],
                'run_timestamp': row['run_timestamp'],
                'ai_agent_used': row['ai_agent_used'],
                'run_data': row['run_data'],
            }
            data['run_data'] = self._deserialize_json(data.get('run_data'))
            results.append(data)

        return results

    # Performance Tracking Methods

    def log_profile_performance(self, profile_id: int, date: str,
                                stocks_recommended: int, stocks_profitable: int,
                                avg_return: float, attribution: Dict,
                                weight_adjustments: Dict) -> int:
        """
        Log daily performance for a profile

        Args:
            profile_id: Profile ID
            date: Date string (YYYY-MM-DD)
            stocks_recommended: Number of stocks recommended
            stocks_profitable: Number that were profitable
            avg_return: Average return percentage
            attribution: Attribution breakdown dict
            weight_adjustments: Suggested weight adjustments

        Returns:
            Performance record ID
        """
        now = datetime.datetime.now()
        timestamp = now.isoformat() if self.db.db_type == 'sqlite' else now

        # Upsert - update if exists, insert if not
        existing = self.db.execute(
            'SELECT id FROM profile_performance WHERE profile_id = %s AND date = %s',
            (profile_id, date), fetch='one'
        )

        if existing:
            sql = '''
                UPDATE profile_performance
                SET stocks_recommended = %s, stocks_profitable = %s,
                    avg_return_pct = %s, attribution_breakdown = %s,
                    weight_adjustments = %s, calculated_at = %s
                WHERE profile_id = %s AND date = %s
            '''
            params = (
                stocks_recommended, stocks_profitable, avg_return,
                self._serialize_json(attribution),
                self._serialize_json(weight_adjustments),
                timestamp, profile_id, date
            )
        else:
            sql = '''
                INSERT INTO profile_performance
                (profile_id, date, stocks_recommended, stocks_profitable,
                 avg_return_pct, attribution_breakdown, weight_adjustments, calculated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            '''
            params = (
                profile_id, date, stocks_recommended, stocks_profitable,
                avg_return, self._serialize_json(attribution),
                self._serialize_json(weight_adjustments), timestamp
            )

        return self.db.execute(sql, params)

    def get_profile_performance(self, profile_id: int,
                                 days: int = 30) -> List[Dict]:
        """
        Get performance history for a profile

        Args:
            profile_id: Profile ID
            days: Number of days to look back

        Returns:
            List of performance records
        """
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')

        sql = '''
            SELECT * FROM profile_performance
            WHERE profile_id = %s AND date >= %s
            ORDER BY date DESC
        '''

        rows = self.db.execute(sql, (profile_id, cutoff), fetch='all')
        if not rows:
            return []

        results = []
        for row in rows:
            data = dict(row) if hasattr(row, 'keys') else {
                'id': row['id'],
                'profile_id': row['profile_id'],
                'date': row['date'],
                'stocks_recommended': row['stocks_recommended'],
                'stocks_profitable': row['stocks_profitable'],
                'avg_return_pct': row['avg_return_pct'],
                'attribution_breakdown': row['attribution_breakdown'],
                'weight_adjustments': row['weight_adjustments'],
                'calculated_at': row['calculated_at'],
            }
            data['attribution_breakdown'] = self._deserialize_json(data.get('attribution_breakdown'))
            data['weight_adjustments'] = self._deserialize_json(data.get('weight_adjustments'))
            results.append(data)

        return results

    def get_aggregate_performance(self, profile_id: int, days: int = 30) -> Dict:
        """
        Get aggregate performance metrics for a profile

        Args:
            profile_id: Profile ID
            days: Number of days to analyze

        Returns:
            Aggregate metrics dict
        """
        perf_data = self.get_profile_performance(profile_id, days)

        if not perf_data:
            return {
                'total_recommended': 0,
                'total_profitable': 0,
                'win_rate': 0.0,
                'avg_return': 0.0,
                'days_analyzed': 0,
            }

        total_recommended = sum(p['stocks_recommended'] for p in perf_data)
        total_profitable = sum(p['stocks_profitable'] for p in perf_data)
        total_return = sum(p['avg_return_pct'] for p in perf_data)

        return {
            'total_recommended': total_recommended,
            'total_profitable': total_profitable,
            'win_rate': (total_profitable / total_recommended * 100) if total_recommended > 0 else 0.0,
            'avg_return': total_return / len(perf_data) if perf_data else 0.0,
            'days_analyzed': len(perf_data),
        }


if __name__ == '__main__':
    # Test script
    import sys

    logging.basicConfig(level=logging.INFO)

    print("Profile Manager Test")
    print("=" * 50)

    # Use local SQLite for testing
    db_config = {
        'db_type': 'sqlite',
        'db_path': os.path.join(os.path.dirname(__file__), '..', 'test_profiles.db')
    }

    db = get_db_manager(db_config)
    db.init_schema()

    manager = ProfileManager(db)

    # Create a test profile
    test_profile = ScreenerProfile(
        name="Test Momentum Profile",
        description="Test profile for momentum stocks",
        theme="momentum",
        finviz_filters={
            "sh_avgvol_o750": True,
            "sh_price_u20": True,
            "sh_relvol_o1.5": True,
        },
        sector_focus=["Technology", "Healthcare"],
        schedule={"morning": True, "midday": True, "evening": False},
        weights={
            "performance_5min": 0.35,
            "relative_volume": 0.30,
            "sector_match": 0.15,
            "rsi_oversold": 0.20,
        }
    )

    # Test create
    profile_id = manager.create_profile(test_profile)
    print(f"Created profile with ID: {profile_id}")

    # Test get
    retrieved = manager.get_profile(profile_id)
    print(f"Retrieved profile: {retrieved.name}")
    print(f"  Theme: {retrieved.theme}")
    print(f"  Weights: {retrieved.weights}")

    # Test list
    profiles = manager.list_profiles()
    print(f"Total profiles: {len(profiles)}")

    # Test update
    retrieved.description = "Updated description"
    manager.update_profile(retrieved)
    print("Updated profile description")

    # Test log run
    run_id = manager.log_profile_run(
        profile_id=profile_id,
        run_type="morning",
        stocks_found=25,
        recommendations=5,
        ai_agent="claude",
        run_data={"stocks": ["AAPL", "MSFT", "GOOG"]}
    )
    print(f"Logged run with ID: {run_id}")

    # Clean up
    manager.delete_profile(profile_id)
    print(f"Deleted profile {profile_id}")

    # Remove test database
    os.remove(db_config['db_path'])
    print("\nTest completed successfully!")
