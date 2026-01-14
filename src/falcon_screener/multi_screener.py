#!/usr/bin/env python3
"""
Multi-Profile Screener

Runs multiple screener profiles and merges results.
Integrates with existing FinvizScraper and AIAgentManager.
"""

import os
import sys
import json
import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging

# Import from falcon-core and local modules
from falcon_core import get_db_manager, get_finviz_client
from falcon_screener.profile_manager import ProfileManager, ScreenerProfile

logger = logging.getLogger(__name__)


@dataclass
class ScreenResult:
    """Result from a single profile screening run"""
    profile_id: int
    profile_name: str
    theme: str
    run_type: str
    timestamp: str
    stocks_found: int
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    ai_agent_used: Optional[str] = None
    raw_stocks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'profile_id': self.profile_id,
            'profile_name': self.profile_name,
            'theme': self.theme,
            'run_type': self.run_type,
            'timestamp': self.timestamp,
            'stocks_found': self.stocks_found,
            'recommendations': self.recommendations,
            'ai_agent_used': self.ai_agent_used,
        }


class MultiScreener:
    """
    Multi-profile screener that runs multiple profiles concurrently
    and merges results with deduplication and priority handling.
    """

    def __init__(self, profile_manager: Optional[ProfileManager] = None,
                 api_key: Optional[str] = None):
        """
        Initialize MultiScreener

        Args:
            profile_manager: ProfileManager instance
            api_key: Polygon.io API key for data enrichment
        """
        self.profile_manager = profile_manager or ProfileManager()
        self.api_key = api_key or os.getenv('MASSIVE_API_KEY', '')

        # Import dependencies lazily to avoid circular imports
        self._finviz_client = None
        self._agent_manager = None

    def _get_finviz_client(self):
        """Get centralized FinvizClient with rate limiting"""
        if self._finviz_client is None:
            try:
                self._finviz_client = get_finviz_client()
                logger.info("[MULTI] Using centralized FinvizClient with rate limiting")
            except Exception as e:
                logger.warning(f"[MULTI] finviz_client not available: {e}")
                self._finviz_client = None
        return self._finviz_client

    def _get_finviz_scraper(self, url: str):
        """Get FinvizScraper instance (legacy wrapper for compatibility)"""
        try:
            from falcon_screener.ai_stock_screener import FinvizScraper
            return FinvizScraper(url)
        except ImportError:
            logger.warning("Could not import FinvizScraper, using basic scraper")
            from daily_report import FinvizScreener
            return FinvizScreener  # Fallback to basic scraper

    def _get_agent_manager(self):
        """Get AIAgentManager instance lazily"""
        if self._agent_manager is None:
            try:
                from ai_stock_screener import AIAgentManager
                self._agent_manager = AIAgentManager()
            except (ImportError, Exception) as e:
                logger.warning(f"Could not initialize AIAgentManager: {e}")
                self._agent_manager = None

        return self._agent_manager

    def run_profile(self, profile: ScreenerProfile, run_type: str,
                    use_ai: bool = True) -> ScreenResult:
        """
        Run a single screener profile

        Args:
            profile: ScreenerProfile to run
            run_type: 'morning', 'midday', or 'evening'
            use_ai: Whether to use AI for analysis (can be disabled for testing)

        Returns:
            ScreenResult with stocks and recommendations
        """
        import pytz
        est = pytz.timezone('US/Eastern')
        timestamp = datetime.datetime.now(est).isoformat()

        logger.info(f"[MULTI] Running profile: {profile.name} ({run_type})")

        # Extract filters from profile URL
        finviz_url = profile.finviz_url or profile.build_finviz_url()
        logger.info(f"[MULTI] Finviz URL: {finviz_url}")

        # Extract filters from URL
        import urllib.parse
        parsed = urllib.parse.urlparse(finviz_url)
        params = urllib.parse.parse_qs(parsed.query)
        filters = params.get('f', [''])[0]

        # Fetch stocks from Finviz using rate-limited client
        stocks = []
        try:
            client = self._get_finviz_client()

            # Try Elite API first if auth key is configured
            if client and client.auth_key:
                # Include earnings data for earnings-themed profiles
                include_earnings = (profile.theme == 'earnings')
                stocks = client.get_stocks(filters=filters, limit=30, include_earnings=include_earnings)
                logger.info(f"[MULTI] Found {len(stocks)} stocks (Elite API)")

            # Fallback to free Finviz web scraping if Elite unavailable or returned 0
            if not stocks:
                logger.info("[MULTI] Falling back to free Finviz web scraping")
                try:
                    from daily_report import FinvizScreener
                    # Use top gainers as a fallback (rate-limited)
                    stocks = FinvizScreener.get_top_gainers_today(30)
                    logger.info(f"[MULTI] Found {len(stocks)} stocks (free Finviz scraping)")
                except Exception as e:
                    logger.warning(f"[MULTI] Free Finviz scraping failed: {e}")
                    # Try legacy scraper as last resort
                    scraper = self._get_finviz_scraper(finviz_url)
                    if hasattr(scraper, 'get_stocks'):
                        stocks = scraper.get_stocks(limit=30)
                    elif hasattr(scraper, 'get_top_gainers_today'):
                        stocks = scraper.get_top_gainers_today(30)
                    logger.info(f"[MULTI] Found {len(stocks)} stocks (legacy scraper)")
        except Exception as e:
            logger.error(f"[MULTI] Failed to fetch stocks: {e}")
            stocks = []

        # Filter by sector focus if specified
        if profile.sector_focus:
            stocks = [
                s for s in stocks
                if s.get('sector', '') in profile.sector_focus
            ]
            logger.info(f"[MULTI] After sector filter: {len(stocks)} stocks")

        # Apply profile weights to score stocks
        weighted_stocks = self._apply_weights(stocks, profile.weights)

        # Sort by weighted score
        weighted_stocks.sort(key=lambda x: x.get('_weighted_score', 0), reverse=True)

        # AI Analysis (if enabled and agent manager available)
        recommendations = []
        ai_agent_used = None

        if use_ai and weighted_stocks:
            agent_manager = self._get_agent_manager()
            if agent_manager:
                try:
                    recommendations, ai_agent_used = self._analyze_with_ai(
                        weighted_stocks[:20],  # Top 20 for AI analysis
                        profile,
                        run_type
                    )
                except Exception as e:
                    logger.error(f"[MULTI] AI analysis failed: {e}")
            else:
                # Create basic recommendations without AI
                recommendations = self._create_basic_recommendations(
                    weighted_stocks[:10], profile
                )
        elif weighted_stocks:
            # AI disabled - create basic recommendations from weighted scores
            recommendations = self._create_basic_recommendations(
                weighted_stocks[:10], profile
            )

        # Create result
        result = ScreenResult(
            profile_id=profile.id or 0,
            profile_name=profile.name,
            theme=profile.theme,
            run_type=run_type,
            timestamp=timestamp,
            stocks_found=len(stocks),
            recommendations=recommendations,
            ai_agent_used=ai_agent_used,
            raw_stocks=weighted_stocks[:20],
        )

        # Log the run to database
        if profile.id:
            self.profile_manager.log_profile_run(
                profile_id=profile.id,
                run_type=run_type,
                stocks_found=len(stocks),
                recommendations=len(recommendations),
                ai_agent=ai_agent_used or 'none',
                run_data=result.to_dict()
            )

        return result

    def _apply_weights(self, stocks: List[Dict], weights: Dict[str, float]) -> List[Dict]:
        """
        Apply profile weights to score stocks

        Args:
            stocks: List of stock dictionaries
            weights: Weight dictionary (factor_name -> weight)

        Returns:
            Stocks with _weighted_score added
        """
        if not weights:
            # Default scoring by performance
            for stock in stocks:
                stock['_weighted_score'] = abs(stock.get('change_pct', stock.get('change', 0)))
            return stocks

        for stock in stocks:
            score = 0.0

            # Performance-based weights
            if 'performance_5min' in weights:
                perf_5min = stock.get('perf_5min', stock.get('performance_5min', 0))
                if isinstance(perf_5min, str):
                    try:
                        perf_5min = float(perf_5min.replace('%', ''))
                    except ValueError:
                        perf_5min = 0
                score += abs(perf_5min) * weights['performance_5min']

            # Volume-based weights
            if 'relative_volume' in weights:
                rvol = stock.get('relative_volume', stock.get('rvol', 1.0))
                if isinstance(rvol, str):
                    try:
                        rvol = float(rvol)
                    except ValueError:
                        rvol = 1.0
                score += min(rvol / 2, 5) * weights['relative_volume']  # Cap at 5

            # RSI weights (favor oversold for mean reversion)
            if 'rsi_oversold' in weights:
                rsi = stock.get('rsi', 50)
                if isinstance(rsi, str):
                    try:
                        rsi = float(rsi)
                    except ValueError:
                        rsi = 50
                if rsi < 40:
                    score += (40 - rsi) / 40 * weights['rsi_oversold']

            # Sector match
            if 'sector_match' in weights:
                score += weights['sector_match']  # Already filtered by sector

            # Change percentage
            change = stock.get('change_pct', stock.get('change', 0))
            if isinstance(change, str):
                try:
                    change = float(change.replace('%', ''))
                except ValueError:
                    change = 0
            score += abs(change) * 0.1  # Small bonus for movement

            stock['_weighted_score'] = round(score, 4)

        return stocks

    def _analyze_with_ai(self, stocks: List[Dict], profile: ScreenerProfile,
                         run_type: str) -> tuple:
        """
        Analyze stocks with AI agent

        Args:
            stocks: List of stocks to analyze
            profile: Profile configuration
            run_type: Type of run

        Returns:
            Tuple of (recommendations, agent_used)
        """
        agent_manager = self._get_agent_manager()
        if not agent_manager:
            return [], None

        # Build prompt based on profile theme
        prompt = self._build_analysis_prompt(stocks, profile, run_type)

        # Query AI
        response = agent_manager.query(prompt)

        if not response:
            return [], None

        # Parse response
        recommendations = self._parse_ai_response(response, profile)
        agent_used = 'claude'  # Default assumption

        return recommendations, agent_used

    def _build_analysis_prompt(self, stocks: List[Dict], profile: ScreenerProfile,
                               run_type: str) -> str:
        """Build AI analysis prompt based on profile theme"""

        stock_list = "\n".join([
            f"- {s.get('ticker', s.get('symbol', 'N/A'))}: "
            f"${s.get('price', 0):.2f}, "
            f"Change: {s.get('change_pct', s.get('change', 0))}%, "
            f"RVOL: {s.get('relative_volume', s.get('rvol', 'N/A'))}x, "
            f"Sector: {s.get('sector', 'N/A')}"
            for s in stocks[:15]
        ])

        theme_context = {
            'momentum': "Focus on breakout potential, volume confirmation, and momentum continuation.",
            'earnings': "Focus on earnings reaction potential, historical surprise patterns, and implied volatility.",
            'seasonal': "Focus on sector rotation patterns, seasonal trends, and institutional flow.",
        }

        time_context = {
            'morning': "Pre-market analysis for day trading opportunities.",
            'midday': "Intraday momentum evaluation for afternoon trades.",
            'evening': "End-of-day review for overnight/swing trade setups.",
        }

        return f"""
Analyze these stocks for {profile.name} ({profile.theme} theme):

{stock_list}

{theme_context.get(profile.theme, '')}
{time_context.get(run_type, '')}

For each promising stock, provide:
1. Ticker symbol
2. Entry price range
3. Target price
4. Stop loss
5. Brief reasoning (1-2 sentences)
6. Risk level (High/Medium/Low)
7. Confidence score (1-10)

Return top 5 recommendations in JSON format:
[{{"ticker": "...", "entry_price_range": "...", "target_price": "...", "stop_loss": "...", "reasoning": "...", "risk_level": "...", "confidence_score": N}}]
"""

    def _parse_ai_response(self, response: str,
                           profile: ScreenerProfile) -> List[Dict]:
        """Parse AI response into recommendations"""
        try:
            # Try to extract JSON from response
            import re

            # Look for JSON array
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                recommendations = json.loads(json_match.group())

                # Add profile source
                for rec in recommendations:
                    rec['profile_source'] = profile.name
                    rec['theme'] = profile.theme

                return recommendations
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[MULTI] Failed to parse AI response: {e}")

        return []

    def _create_basic_recommendations(self, stocks: List[Dict],
                                      profile: ScreenerProfile) -> List[Dict]:
        """Create basic recommendations without AI"""
        recommendations = []

        for stock in stocks[:5]:
            ticker = stock.get('ticker', stock.get('symbol', ''))
            price = stock.get('price', 0)

            if not ticker or not price:
                continue

            rec = {
                'ticker': ticker,
                'company': stock.get('company', ''),
                'sector': stock.get('sector', ''),
                'entry_price_range': f"{price*0.98:.2f}-{price*1.02:.2f}",
                'target_price': f"{price*1.08:.2f}",
                'stop_loss': f"{price*0.95:.2f}",
                'reasoning': f"High weighted score ({stock.get('_weighted_score', 0):.2f}) based on {profile.theme} criteria",
                'risk_level': 'High' if price < 5 else 'Medium',
                'confidence_score': 5,
                'profile_source': profile.name,
                'theme': profile.theme,
            }

            # Add earnings date for earnings-themed profiles
            if profile.theme == 'earnings' and stock.get('earnings_date'):
                rec['earnings_date'] = stock.get('earnings_date')
                rec['reasoning'] = f"Earnings: {stock.get('earnings_date')} | Score: {stock.get('_weighted_score', 0):.2f}"

            # Add target price if available
            if stock.get('target_price'):
                rec['analyst_target'] = stock.get('target_price')

            recommendations.append(rec)

        return recommendations

    def run_scheduled_profiles(self, run_type: str,
                               use_ai: bool = True) -> List[ScreenResult]:
        """
        Run all profiles scheduled for this time

        Args:
            run_type: 'morning', 'midday', or 'evening'
            use_ai: Whether to use AI analysis

        Returns:
            List of ScreenResults from all profiles
        """
        profiles = self.profile_manager.get_active_profiles_for_schedule(run_type)

        logger.info(f"[MULTI] Running {len(profiles)} profiles for {run_type} schedule")

        results = []
        for profile in profiles:
            try:
                result = self.run_profile(profile, run_type, use_ai)
                results.append(result)
            except Exception as e:
                logger.error(f"[MULTI] Failed to run profile {profile.name}: {e}")

        return results

    def merge_results(self, results: List[ScreenResult],
                      dedup: bool = True) -> List[Dict]:
        """
        Merge results from multiple profiles

        Args:
            results: List of ScreenResults
            dedup: Remove duplicate tickers (keep highest confidence)

        Returns:
            Merged and deduplicated recommendations
        """
        all_recommendations = []

        for result in results:
            for rec in result.recommendations:
                rec['_source_profile'] = result.profile_name
                rec['_source_theme'] = result.theme
                rec['_run_timestamp'] = result.timestamp
                all_recommendations.append(rec)

        if not dedup:
            return all_recommendations

        # Deduplicate by ticker, keeping highest confidence
        ticker_map = {}
        for rec in all_recommendations:
            ticker = rec.get('ticker', '')
            if not ticker:
                continue

            existing = ticker_map.get(ticker)
            if not existing:
                ticker_map[ticker] = rec
            else:
                # Keep higher confidence
                if rec.get('confidence_score', 0) > existing.get('confidence_score', 0):
                    ticker_map[ticker] = rec

        merged = list(ticker_map.values())

        # Sort by confidence
        merged.sort(key=lambda x: x.get('confidence_score', 0), reverse=True)

        logger.info(f"[MULTI] Merged {len(all_recommendations)} -> {len(merged)} recommendations")

        return merged

    def save_results(self, results: List[ScreenResult], merged: List[Dict],
                     output_file: str = 'screened_stocks.json') -> str:
        """
        Save screening results to JSON file

        Args:
            results: Individual profile results
            merged: Merged recommendations
            output_file: Output filename

        Returns:
            Path to saved file
        """
        import pytz
        est = pytz.timezone('US/Eastern')
        timestamp = datetime.datetime.now(est)

        # Build output structure matching existing format
        output = {
            'timestamp': timestamp.isoformat(),
            'screen_type': results[0].run_type if results else 'unknown',
            'total_stocks': sum(r.stocks_found for r in results),
            'profiles_run': [r.to_dict() for r in results],
            'recommendations': merged,
        }

        # Load existing data and append
        output_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            output_file
        )

        existing_data = []
        if os.path.exists(output_path):
            try:
                with open(output_path, 'r') as f:
                    existing_data = json.load(f)
                    if not isinstance(existing_data, list):
                        existing_data = [existing_data]
            except (json.JSONDecodeError, Exception):
                existing_data = []

        # Append new results
        existing_data.append(output)

        # Keep only last 30 days
        cutoff = (timestamp - datetime.timedelta(days=30)).isoformat()
        existing_data = [
            e for e in existing_data
            if e.get('timestamp', '') >= cutoff
        ]

        # Save
        with open(output_path, 'w') as f:
            json.dump(existing_data, f, indent=2)

        logger.info(f"[MULTI] Saved results to {output_path}")

        return output_path


def main():
    """CLI entry point for falcon-screener"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Multi-Profile Screener')
    parser.add_argument('--run-type', choices=['morning', 'midday', 'evening'],
                        default='morning', help='Schedule time to run')
    parser.add_argument('--no-ai', action='store_true', help='Disable AI analysis')
    parser.add_argument('--profile', type=str, help='Run specific profile by name')
    parser.add_argument('--init', action='store_true', help='Initialize default profiles')

    args = parser.parse_args()

    # Initialize
    db = get_db_manager()
    db.init_schema()

    profile_manager = ProfileManager(db)
    screener = MultiScreener(profile_manager)

    if args.init:
        from falcon_screener.profile_templates import initialize_default_profiles
        initialize_default_profiles(profile_manager)
        print("\nDefault profiles initialized.")
        sys.exit(0)

    if args.profile:
        # Run specific profile
        profile = profile_manager.get_profile_by_name(args.profile)
        if not profile:
            print(f"Profile not found: {args.profile}")
            sys.exit(1)

        result = screener.run_profile(profile, args.run_type, not args.no_ai)
        print(f"\nProfile: {result.profile_name}")
        print(f"Stocks found: {result.stocks_found}")
        print(f"Recommendations: {len(result.recommendations)}")

        for rec in result.recommendations:
            print(f"  - {rec['ticker']}: {rec.get('reasoning', '')[:50]}...")
    else:
        # Run scheduled profiles
        results = screener.run_scheduled_profiles(args.run_type, not args.no_ai)

        if results:
            merged = screener.merge_results(results)
            output_path = screener.save_results(results, merged)

            print(f"\n{'='*70}")
            print(f"MULTI-SCREENER RESULTS - {args.run_type.upper()}")
            print(f"{'='*70}")
            print(f"Profiles run: {len(results)}")
            print(f"Total recommendations: {len(merged)}")

            # Show earnings plays separately with dates
            earnings_recs = [r for r in merged if r.get('theme') == 'earnings']
            if earnings_recs:
                print(f"\n--- EARNINGS PLAYS ({len(earnings_recs)}) ---")
                for rec in earnings_recs:
                    earnings_dt = rec.get('earnings_date', 'N/A')
                    target = rec.get('analyst_target', '')
                    target_str = f" | Target: ${target:.2f}" if target else ""
                    print(f"  {rec['ticker']:6s} Earnings: {earnings_dt}{target_str}")

            print(f"\nOutput saved to: {output_path}")

            print(f"\nTop recommendations:")
            for rec in merged[:10]:
                print(f"  [{rec.get('_source_profile', 'unknown')}] "
                      f"{rec['ticker']}: {rec.get('reasoning', '')[:40]}...")
        else:
            print(f"No profiles scheduled for {args.run_type}")


if __name__ == '__main__':
    main()
