#!/usr/bin/env python3
"""
Weight Feedback Loop

Auto-adjusts screener profile weights based on daily report attribution data.
Analyzes historical performance to optimize screening criteria.
"""

import os
import sys
import json
import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener.profile_manager import ProfileManager, ScreenerProfile
from db_manager import get_db_manager

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a profile"""
    profile_id: int
    profile_name: str
    days_analyzed: int
    total_recommended: int
    total_profitable: int
    win_rate: float
    avg_return: float
    best_category: str
    worst_category: str
    suggested_adjustments: Dict[str, float]


class WeightFeedbackLoop:
    """
    Auto-adjust profile weights based on daily report attribution data.

    Process:
    1. Load daily reports for tracked stocks
    2. Match recommendations to outcomes (gainers/losers)
    3. Analyze which attribution categories performed best
    4. Adjust profile weights to favor successful patterns
    """

    # Maximum weight adjustment per iteration (safety bound)
    MAX_ADJUSTMENT = 0.10

    # Minimum data points before making adjustments
    MIN_DATA_POINTS = 5

    # Attribution category to weight factor mapping
    ATTRIBUTION_TO_WEIGHT = {
        'technical_breakout': ['performance_5min', 'relative_volume'],
        'technical_breakdown': ['rsi_oversold'],
        'volume_spike': ['relative_volume'],
        'news': ['sector_match'],
        'earnings': ['earnings_proximity', 'historical_reaction'],
        'sector_rotation': ['sector_momentum', 'seasonal_alignment'],
        'meme_momentum': ['relative_volume', 'performance_5min'],
        'short_squeeze': ['relative_volume', 'performance_5min'],
    }

    def __init__(self, profile_manager: Optional[ProfileManager] = None,
                 reports_dir: Optional[str] = None):
        """
        Initialize WeightFeedbackLoop

        Args:
            profile_manager: ProfileManager instance
            reports_dir: Directory containing daily reports
        """
        self.profile_manager = profile_manager or ProfileManager()
        self.reports_dir = reports_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'reports'
        )

    def load_daily_report(self, date: str) -> Optional[Dict]:
        """
        Load a daily report for a specific date

        Args:
            date: Date string (YYYY-MM-DD)

        Returns:
            Report dict or None if not found
        """
        report_path = os.path.join(self.reports_dir, f'daily_report_{date}.json')

        if not os.path.exists(report_path):
            return None

        try:
            with open(report_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to load report for {date}: {e}")
            return None

    def load_reports_range(self, days: int = 30) -> List[Dict]:
        """
        Load daily reports for a date range

        Args:
            days: Number of days to look back

        Returns:
            List of report dicts
        """
        reports = []
        today = datetime.date.today()

        for i in range(days):
            date = (today - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
            report = self.load_daily_report(date)
            if report:
                reports.append(report)

        logger.info(f"[FEEDBACK] Loaded {len(reports)} reports from last {days} days")
        return reports

    def get_profile_recommendations(self, profile_id: int,
                                     days: int = 30) -> List[Dict]:
        """
        Get recommendations made by a profile

        Args:
            profile_id: Profile ID
            days: Number of days to look back

        Returns:
            List of recommendation records with tickers
        """
        runs = self.profile_manager.get_profile_runs(profile_id, days)

        recommendations = []
        for run in runs:
            run_data = run.get('run_data', {})
            recs = run_data.get('recommendations', [])
            for rec in recs:
                rec['_run_date'] = run.get('run_timestamp', '')[:10]
                recommendations.append(rec)

        return recommendations

    def match_recommendations_to_outcomes(self, recommendations: List[Dict],
                                          reports: List[Dict]) -> List[Dict]:
        """
        Match profile recommendations to actual market outcomes

        Args:
            recommendations: List of recommendations from profile
            reports: List of daily reports

        Returns:
            Recommendations with outcome data attached
        """
        # Build lookup: date -> {ticker -> performance data}
        outcome_lookup = {}
        for report in reports:
            date = report.get('date', '')
            gainers = {g['ticker']: g for g in report.get('top_gainers', [])}
            losers = {l['ticker']: l for l in report.get('top_losers', [])}

            outcome_lookup[date] = {
                'gainers': gainers,
                'losers': losers,
                'attribution': report.get('attribution_summary', {}),
            }

        # Match recommendations
        matched = []
        for rec in recommendations:
            ticker = rec.get('ticker', '')
            rec_date = rec.get('_run_date', '')

            if not ticker or not rec_date:
                continue

            # Check same day and next day outcomes
            for offset in [0, 1]:
                check_date = (
                    datetime.datetime.strptime(rec_date, '%Y-%m-%d') +
                    datetime.timedelta(days=offset)
                ).strftime('%Y-%m-%d')

                outcomes = outcome_lookup.get(check_date, {})
                gainers = outcomes.get('gainers', {})
                losers = outcomes.get('losers', {})

                if ticker in gainers:
                    rec['_outcome'] = 'winner'
                    rec['_return_pct'] = gainers[ticker].get('change_pct', 0)
                    rec['_attribution'] = gainers[ticker].get('attribution_category', '')
                    matched.append(rec)
                    break
                elif ticker in losers:
                    rec['_outcome'] = 'loser'
                    rec['_return_pct'] = losers[ticker].get('change_pct', 0)
                    rec['_attribution'] = losers[ticker].get('attribution_category', '')
                    matched.append(rec)
                    break

        logger.info(f"[FEEDBACK] Matched {len(matched)}/{len(recommendations)} recommendations")
        return matched

    def calculate_profile_performance(self, profile_id: int,
                                      days: int = 30) -> PerformanceMetrics:
        """
        Calculate performance metrics for a profile

        Args:
            profile_id: Profile ID
            days: Number of days to analyze

        Returns:
            PerformanceMetrics dataclass
        """
        profile = self.profile_manager.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile not found: {profile_id}")

        # Get recommendations and match to outcomes
        recommendations = self.get_profile_recommendations(profile_id, days)
        reports = self.load_reports_range(days)
        matched = self.match_recommendations_to_outcomes(recommendations, reports)

        if not matched:
            return PerformanceMetrics(
                profile_id=profile_id,
                profile_name=profile.name,
                days_analyzed=days,
                total_recommended=len(recommendations),
                total_profitable=0,
                win_rate=0.0,
                avg_return=0.0,
                best_category='unknown',
                worst_category='unknown',
                suggested_adjustments={},
            )

        # Calculate metrics
        winners = [m for m in matched if m.get('_outcome') == 'winner']
        total_return = sum(m.get('_return_pct', 0) for m in matched)

        # Attribution breakdown
        category_performance = {}
        for m in matched:
            category = m.get('_attribution', 'unknown')
            # Normalize category name
            category = category.lower().replace('changecategory.', '')

            if category not in category_performance:
                category_performance[category] = {'wins': 0, 'losses': 0, 'returns': []}

            if m.get('_outcome') == 'winner':
                category_performance[category]['wins'] += 1
            else:
                category_performance[category]['losses'] += 1
            category_performance[category]['returns'].append(m.get('_return_pct', 0))

        # Find best/worst categories
        category_win_rates = {}
        for cat, data in category_performance.items():
            total = data['wins'] + data['losses']
            if total > 0:
                category_win_rates[cat] = data['wins'] / total

        best_category = max(category_win_rates, key=category_win_rates.get) if category_win_rates else 'unknown'
        worst_category = min(category_win_rates, key=category_win_rates.get) if category_win_rates else 'unknown'

        # Generate adjustment suggestions
        adjustments = self._suggest_weight_adjustments(
            profile.weights, category_performance, matched
        )

        return PerformanceMetrics(
            profile_id=profile_id,
            profile_name=profile.name,
            days_analyzed=days,
            total_recommended=len(recommendations),
            total_profitable=len(winners),
            win_rate=(len(winners) / len(matched) * 100) if matched else 0.0,
            avg_return=(total_return / len(matched)) if matched else 0.0,
            best_category=best_category,
            worst_category=worst_category,
            suggested_adjustments=adjustments,
        )

    def _suggest_weight_adjustments(self, current_weights: Dict[str, float],
                                    category_performance: Dict,
                                    matched: List[Dict]) -> Dict[str, float]:
        """
        Suggest weight adjustments based on performance

        Args:
            current_weights: Current profile weights
            category_performance: Performance by attribution category
            matched: Matched recommendation data

        Returns:
            Suggested weight adjustments
        """
        if len(matched) < self.MIN_DATA_POINTS:
            logger.info(f"[FEEDBACK] Not enough data points ({len(matched)}) for adjustments")
            return {}

        adjustments = {}

        # Analyze which categories performed best
        for category, data in category_performance.items():
            total = data['wins'] + data['losses']
            if total < 2:
                continue

            win_rate = data['wins'] / total
            avg_return = sum(data['returns']) / len(data['returns']) if data['returns'] else 0

            # Get weight factors associated with this category
            weight_factors = self.ATTRIBUTION_TO_WEIGHT.get(category, [])

            for factor in weight_factors:
                if factor not in current_weights:
                    continue

                current = current_weights[factor]

                # Adjust based on win rate
                if win_rate > 0.6 and avg_return > 0:
                    # Increase weight for high-performing factors
                    adjustment = min(0.05, self.MAX_ADJUSTMENT)
                elif win_rate < 0.4 or avg_return < -5:
                    # Decrease weight for underperforming factors
                    adjustment = -min(0.05, self.MAX_ADJUSTMENT)
                else:
                    continue

                # Accumulate adjustments
                if factor in adjustments:
                    adjustments[factor] += adjustment
                else:
                    adjustments[factor] = adjustment

        # Apply bounds and normalize
        for factor in adjustments:
            # Bound individual adjustment
            adjustments[factor] = max(-self.MAX_ADJUSTMENT,
                                      min(self.MAX_ADJUSTMENT, adjustments[factor]))

            # Round to 2 decimal places
            adjustments[factor] = round(adjustments[factor], 2)

        return adjustments

    def apply_weight_adjustments(self, profile_id: int,
                                 adjustments: Dict[str, float],
                                 auto: bool = False) -> bool:
        """
        Apply weight adjustments to a profile

        Args:
            profile_id: Profile ID
            adjustments: Weight adjustments dict
            auto: If True, apply automatically; if False, just log

        Returns:
            True if adjustments were applied
        """
        profile = self.profile_manager.get_profile(profile_id)
        if not profile:
            return False

        if not adjustments:
            logger.info(f"[FEEDBACK] No adjustments to apply for {profile.name}")
            return False

        # Calculate new weights
        new_weights = dict(profile.weights)
        for factor, adjustment in adjustments.items():
            if factor in new_weights:
                new_value = new_weights[factor] + adjustment
                # Bound between 0.05 and 0.50
                new_weights[factor] = max(0.05, min(0.50, new_value))

        # Normalize weights to sum to 1.0
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: round(v / total, 3) for k, v in new_weights.items()}

        logger.info(f"[FEEDBACK] Suggested adjustments for {profile.name}:")
        for factor, adj in adjustments.items():
            old = profile.weights.get(factor, 0)
            new = new_weights.get(factor, 0)
            logger.info(f"  {factor}: {old:.3f} -> {new:.3f} ({adj:+.3f})")

        if auto:
            self.profile_manager.update_weights(profile_id, new_weights)
            logger.info(f"[FEEDBACK] Auto-applied adjustments to {profile.name}")

            # Log performance record
            today = datetime.date.today().strftime('%Y-%m-%d')
            self.profile_manager.log_profile_performance(
                profile_id=profile_id,
                date=today,
                stocks_recommended=0,
                stocks_profitable=0,
                avg_return=0,
                attribution={},
                weight_adjustments=adjustments,
            )

            return True
        else:
            logger.info(f"[FEEDBACK] Adjustments logged but not applied (auto=False)")
            return False

    def process_daily_report(self, report_date: Optional[str] = None) -> Dict[int, Dict]:
        """
        Process daily report and update profile performance

        Args:
            report_date: Date to process (default: today)

        Returns:
            Performance updates by profile ID
        """
        if report_date is None:
            report_date = datetime.date.today().strftime('%Y-%m-%d')

        report = self.load_daily_report(report_date)
        if not report:
            logger.warning(f"[FEEDBACK] No report found for {report_date}")
            return {}

        # Get all enabled profiles
        profiles = self.profile_manager.list_profiles(enabled_only=True)

        updates = {}
        for profile in profiles:
            # Get recommendations for this date
            runs = self.profile_manager.get_profile_runs(profile.id, days=1)

            if not runs:
                continue

            # Find matching outcomes
            recommendations = []
            for run in runs:
                run_data = run.get('run_data', {})
                recommendations.extend(run_data.get('recommendations', []))

            gainers = {g['ticker']: g for g in report.get('top_gainers', [])}
            losers = {l['ticker']: l for l in report.get('top_losers', [])}

            profitable = 0
            total_return = 0
            attribution_counts = {}

            for rec in recommendations:
                ticker = rec.get('ticker', '')

                if ticker in gainers:
                    profitable += 1
                    return_pct = gainers[ticker].get('change_pct', 0)
                    attr = gainers[ticker].get('attribution_category', 'unknown')
                elif ticker in losers:
                    return_pct = losers[ticker].get('change_pct', 0)
                    attr = losers[ticker].get('attribution_category', 'unknown')
                else:
                    continue

                total_return += return_pct
                attr_key = attr.lower().replace('changecategory.', '')
                attribution_counts[attr_key] = attribution_counts.get(attr_key, 0) + 1

            # Log performance
            if recommendations:
                avg_return = total_return / len(recommendations)

                self.profile_manager.log_profile_performance(
                    profile_id=profile.id,
                    date=report_date,
                    stocks_recommended=len(recommendations),
                    stocks_profitable=profitable,
                    avg_return=avg_return,
                    attribution=attribution_counts,
                    weight_adjustments={},
                )

                updates[profile.id] = {
                    'profile_name': profile.name,
                    'recommended': len(recommendations),
                    'profitable': profitable,
                    'avg_return': avg_return,
                }

                logger.info(f"[FEEDBACK] {profile.name}: {profitable}/{len(recommendations)} "
                           f"profitable, avg return {avg_return:.2f}%")

        return updates

    def run_weekly_optimization(self, auto_apply: bool = False) -> Dict[int, PerformanceMetrics]:
        """
        Run weekly optimization on all profiles

        Args:
            auto_apply: Automatically apply suggested adjustments

        Returns:
            Performance metrics by profile ID
        """
        logger.info("[FEEDBACK] Running weekly optimization...")

        profiles = self.profile_manager.list_profiles(enabled_only=True)
        results = {}

        for profile in profiles:
            try:
                metrics = self.calculate_profile_performance(profile.id, days=30)
                results[profile.id] = metrics

                logger.info(f"\n[FEEDBACK] {profile.name}:")
                logger.info(f"  Win rate: {metrics.win_rate:.1f}%")
                logger.info(f"  Avg return: {metrics.avg_return:.2f}%")
                logger.info(f"  Best category: {metrics.best_category}")
                logger.info(f"  Worst category: {metrics.worst_category}")

                if metrics.suggested_adjustments:
                    self.apply_weight_adjustments(
                        profile.id,
                        metrics.suggested_adjustments,
                        auto=auto_apply
                    )
            except Exception as e:
                logger.error(f"[FEEDBACK] Failed to optimize {profile.name}: {e}")

        return results


if __name__ == '__main__':
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Weight Feedback Loop')
    parser.add_argument('--daily', action='store_true', help='Process daily report')
    parser.add_argument('--weekly', action='store_true', help='Run weekly optimization')
    parser.add_argument('--auto', action='store_true', help='Auto-apply adjustments')
    parser.add_argument('--date', type=str, help='Specific date to process')
    parser.add_argument('--profile', type=int, help='Specific profile ID to analyze')

    args = parser.parse_args()

    # Initialize
    db = get_db_manager()
    profile_manager = ProfileManager(db)
    feedback = WeightFeedbackLoop(profile_manager)

    if args.daily:
        updates = feedback.process_daily_report(args.date)
        print(f"\nProcessed {len(updates)} profile updates")

    elif args.weekly:
        results = feedback.run_weekly_optimization(args.auto)
        print(f"\n{'='*60}")
        print("WEEKLY OPTIMIZATION RESULTS")
        print(f"{'='*60}")
        for profile_id, metrics in results.items():
            print(f"\n{metrics.profile_name}:")
            print(f"  Recommendations: {metrics.total_recommended}")
            print(f"  Win rate: {metrics.win_rate:.1f}%")
            print(f"  Avg return: {metrics.avg_return:.2f}%")
            if metrics.suggested_adjustments:
                print(f"  Suggested adjustments: {metrics.suggested_adjustments}")

    elif args.profile:
        metrics = feedback.calculate_profile_performance(args.profile)
        print(f"\nProfile: {metrics.profile_name}")
        print(f"Days analyzed: {metrics.days_analyzed}")
        print(f"Total recommended: {metrics.total_recommended}")
        print(f"Profitable: {metrics.total_profitable}")
        print(f"Win rate: {metrics.win_rate:.1f}%")
        print(f"Avg return: {metrics.avg_return:.2f}%")
        print(f"Best category: {metrics.best_category}")
        print(f"Worst category: {metrics.worst_category}")
        if metrics.suggested_adjustments:
            print(f"Suggested adjustments: {metrics.suggested_adjustments}")

    else:
        parser.print_help()
