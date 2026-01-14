#!/usr/bin/env python3
"""
Daily Trading Report Generator
Analyzes market data and generates reports on top gainers/losers with attribution.

Usage:
    python3 daily_report.py                    # Generate today's report
    python3 daily_report.py --date 2026-01-14  # Generate report for specific date
    python3 daily_report.py --live             # Generate live intraday report
"""

import os
import sys
import json
import datetime
import argparse
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import requests
import pytz

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class ChangeCategory(Enum):
    """Categories for price change attribution"""
    EARNINGS = "earnings"
    NEWS = "news"
    SECTOR_ROTATION = "sector_rotation"
    TECHNICAL_BREAKOUT = "technical_breakout"
    TECHNICAL_BREAKDOWN = "technical_breakdown"
    VOLUME_SPIKE = "volume_spike"
    MEME_MOMENTUM = "meme_momentum"
    FDA_CATALYST = "fda_catalyst"
    MERGER_ACQUISITION = "merger_acquisition"
    SHORT_SQUEEZE = "short_squeeze"
    PROFIT_TAKING = "profit_taking"
    UNKNOWN = "unknown"


@dataclass
class StockPerformance:
    """Stock performance data for the day"""
    ticker: str
    company: str
    sector: str
    open_price: float
    close_price: float
    high: float
    low: float
    volume: int
    avg_volume: int
    change_pct: float
    change_dollars: float
    relative_volume: float
    attribution: str
    attribution_category: ChangeCategory
    notes: str = ""


class FinvizScreener:
    """
    Fetch gainers/losers from Finviz with rate limiting.

    Uses exponential backoff to avoid throttling (429 errors).
    """

    # Class-level rate limiting state
    _last_request_time = None
    _consecutive_errors = 0
    _current_backoff = 2.0
    _lock = None

    # Rate limit configuration
    MIN_REQUEST_INTERVAL = 1.5  # Minimum seconds between requests
    MAX_BACKOFF = 60.0  # Maximum backoff seconds
    BACKOFF_MULTIPLIER = 2.0
    MAX_RETRIES = 5

    @classmethod
    def _get_lock(cls):
        """Get or create thread lock"""
        if cls._lock is None:
            import threading
            cls._lock = threading.Lock()
        return cls._lock

    @classmethod
    def _wait_for_rate_limit(cls):
        """Wait if needed to respect rate limits"""
        import time
        from datetime import datetime

        with cls._get_lock():
            if cls._last_request_time is None:
                return

            elapsed = (datetime.now() - cls._last_request_time).total_seconds()
            required_wait = cls.MIN_REQUEST_INTERVAL

            # Add extra wait if we've had recent errors
            if cls._consecutive_errors > 0:
                required_wait = min(cls._current_backoff, cls.MAX_BACKOFF)

            # Add jitter
            import random
            jitter = random.uniform(-0.25 * required_wait, 0.25 * required_wait)
            required_wait = max(0, required_wait + jitter)

            if elapsed < required_wait:
                sleep_time = required_wait - elapsed
                print(f"[FINVIZ] Rate limiting: waiting {sleep_time:.2f}s")
                time.sleep(sleep_time)

    @classmethod
    def _record_request(cls):
        """Record that a request was made"""
        from datetime import datetime
        with cls._get_lock():
            cls._last_request_time = datetime.now()

    @classmethod
    def _record_success(cls):
        """Record successful request"""
        with cls._get_lock():
            cls._consecutive_errors = 0
            cls._current_backoff = 2.0

    @classmethod
    def _record_error(cls, is_throttle: bool = False) -> float:
        """Record error and return current backoff"""
        with cls._get_lock():
            cls._consecutive_errors += 1
            if is_throttle:
                cls._current_backoff = min(
                    cls._current_backoff * cls.BACKOFF_MULTIPLIER,
                    cls.MAX_BACKOFF
                )
            return cls._current_backoff

    @staticmethod
    def get_gainers(limit: int = 20) -> List[Dict]:
        """Fetch top gainers from Finviz"""
        return FinvizScreener._fetch_screen('ta_perf_1wup', limit, sort_desc=True)

    @staticmethod
    def get_losers(limit: int = 20) -> List[Dict]:
        """Fetch top losers from Finviz"""
        return FinvizScreener._fetch_screen('ta_perf_1wdown', limit, sort_desc=False)

    @staticmethod
    def get_top_gainers_today(limit: int = 20) -> List[Dict]:
        """Fetch today's top gainers sorted by change%"""
        # Use signal for top gainers
        url = "https://finviz.com/screener.ashx"
        params = {
            'v': '111',
            's': 'ta_topgainers',
            'f': 'sh_avgvol_o200',  # Min 200K avg volume
            'o': '-change'  # Sort by change descending
        }
        return FinvizScreener._scrape_table(url, params, limit)

    @staticmethod
    def get_top_losers_today(limit: int = 20) -> List[Dict]:
        """Fetch today's top losers sorted by change%"""
        url = "https://finviz.com/screener.ashx"
        params = {
            'v': '111',
            's': 'ta_toplosers',
            'f': 'sh_avgvol_o200',  # Min 200K avg volume
            'o': 'change'  # Sort by change ascending (most negative first)
        }
        return FinvizScreener._scrape_table(url, params, limit)

    @staticmethod
    def _scrape_table(url: str, params: Dict, limit: int) -> List[Dict]:
        """Scrape Finviz screener table with rate limiting and retry"""
        from bs4 import BeautifulSoup
        import time

        retries = 0
        while retries < FinvizScreener.MAX_RETRIES:
            try:
                # Rate limit before request
                FinvizScreener._wait_for_rate_limit()

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }

                FinvizScreener._record_request()
                response = requests.get(url, params=params, headers=headers, timeout=15)

                # Handle rate limiting (429)
                if response.status_code == 429:
                    backoff = FinvizScreener._record_error(is_throttle=True)
                    print(f"[FINVIZ] Rate limited (429) - backing off {backoff:.1f}s")
                    time.sleep(backoff)
                    retries += 1
                    continue

                # Handle server errors
                if response.status_code >= 500:
                    backoff = FinvizScreener._record_error(is_throttle=False)
                    print(f"[FINVIZ] Server error ({response.status_code}) - retrying in {backoff:.1f}s")
                    time.sleep(backoff)
                    retries += 1
                    continue

                response.raise_for_status()
                FinvizScreener._record_success()

                soup = BeautifulSoup(response.text, 'html.parser')

                # Find the screener table (new Finviz layout uses 'screener_table' class)
                table = soup.find('table', class_='screener_table')
                if not table:
                    # Try alternate classes
                    table = soup.find('table', class_='styled-table-new')
                if not table:
                    # Legacy fallback
                    table = soup.find('table', {'class': 'table-light'})

                if not table:
                    print("[FINVIZ] Could not find screener table")
                    return []

                stocks = []
                rows = table.find_all('tr')[1:]  # Skip header

                # Column layout (v=111 overview):
                # 0: No., 1: Ticker, 2: Company, 3: Sector, 4: Industry,
                # 5: Country, 6: Market Cap, 7: P/E, 8: Price, 9: Change, 10: Volume
                for row in rows[:limit]:
                    cells = row.find_all('td')
                    if len(cells) >= 11:
                        try:
                            # Get ticker from text or link
                            ticker = cells[1].text.strip()

                            company = cells[2].text.strip()
                            sector = cells[3].text.strip()
                            industry = cells[4].text.strip()
                            market_cap = cells[6].text.strip()
                            price_str = cells[8].text.strip()
                            change_str = cells[9].text.strip()
                            volume_str = cells[10].text.strip()

                            # Parse values
                            price = float(price_str.replace(',', '')) if price_str and price_str != '-' else 0
                            change_pct = float(change_str.replace('%', '').replace(',', '')) if change_str and change_str != '-' else 0

                            # Parse volume (handles K, M, B suffixes and commas)
                            volume = FinvizScreener._parse_volume(volume_str)

                            stocks.append({
                                'ticker': ticker,
                                'company': company,
                                'sector': sector,
                                'industry': industry,
                                'market_cap': market_cap,
                                'price': price,
                                'change_pct': change_pct,
                                'volume': volume,
                                'source': 'finviz'
                            })
                        except (ValueError, IndexError) as e:
                            continue

                print(f"[FINVIZ] Fetched {len(stocks)} stocks")
                return stocks

            except requests.exceptions.Timeout:
                backoff = FinvizScreener._record_error(is_throttle=False)
                print(f"[FINVIZ] Request timeout - retrying in {backoff:.1f}s")
                time.sleep(backoff)
                retries += 1

            except requests.exceptions.ConnectionError:
                backoff = FinvizScreener._record_error(is_throttle=False)
                print(f"[FINVIZ] Connection error - retrying in {backoff:.1f}s")
                time.sleep(backoff)
                retries += 1

            except Exception as e:
                print(f"[FINVIZ] Error scraping: {e}")
                FinvizScreener._record_error(is_throttle=False)
                return []

        # Max retries exceeded
        print(f"[FINVIZ] Max retries ({FinvizScreener.MAX_RETRIES}) exceeded")
        return []

    @staticmethod
    def _parse_volume(vol_str: str) -> int:
        """Parse volume string with K/M/B suffixes"""
        if not vol_str or vol_str == '-':
            return 0
        vol_str = vol_str.replace(',', '').upper()
        multiplier = 1
        if vol_str.endswith('K'):
            multiplier = 1000
            vol_str = vol_str[:-1]
        elif vol_str.endswith('M'):
            multiplier = 1000000
            vol_str = vol_str[:-1]
        elif vol_str.endswith('B'):
            multiplier = 1000000000
            vol_str = vol_str[:-1]
        try:
            return int(float(vol_str) * multiplier)
        except ValueError:
            return 0

    @staticmethod
    def _fetch_screen(signal: str, limit: int, sort_desc: bool = True) -> List[Dict]:
        """Generic fetch with signal filter"""
        url = "https://finviz.com/screener.ashx"
        params = {
            'v': '111',
            's': signal,
            'f': 'sh_avgvol_o200',
        }
        return FinvizScreener._scrape_table(url, params, limit)


class DailyReportGenerator:
    """Generate daily trading reports with gainers/losers analysis"""

    def __init__(self, api_key: str, use_finviz: bool = True):
        self.api_key = api_key
        self.use_finviz = use_finviz
        self.est = pytz.timezone('US/Eastern')
        self.report_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(self.report_dir, exist_ok=True)

    def get_market_snapshot(self, tickers: List[str] = None) -> List[Dict]:
        """Get market snapshot for all or specified tickers"""
        try:
            if tickers:
                # Get specific tickers
                results = []
                for ticker in tickers:
                    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
                    params = {'apiKey': self.api_key}
                    response = requests.get(url, params=params, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('status') == 'OK' and 'ticker' in data:
                            results.append(data['ticker'])
                return results
            else:
                # Get all tickers snapshot (gainers/losers)
                url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
                params = {'apiKey': self.api_key}
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                return data.get('tickers', [])
        except Exception as e:
            print(f"[ERROR] Failed to get market snapshot: {e}")
            return []

    def get_gainers_losers(self, direction: str = "gainers", limit: int = 20) -> List[Dict]:
        """Get top gainers or losers"""
        try:
            url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/{direction}"
            params = {'apiKey': self.api_key}
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            tickers = data.get('tickers', [])
            return tickers[:limit]
        except Exception as e:
            print(f"[ERROR] Failed to get {direction}: {e}")
            return []

    def calculate_relative_volume(self, current_volume: int, avg_volume: int) -> float:
        """Calculate relative volume (rvol)"""
        if avg_volume and avg_volume > 0:
            return round(current_volume / avg_volume, 2)
        return 0.0

    def attribute_change(self, ticker_data: Dict, change_pct: float) -> Tuple[str, ChangeCategory]:
        """
        Attribute the price change to a likely cause.
        This is a heuristic-based attribution - can be enhanced with news API.
        """
        rvol = self.calculate_relative_volume(
            ticker_data.get('day', {}).get('v', 0),
            ticker_data.get('prevDay', {}).get('v', 1)
        )

        # Volume-based attribution
        if rvol > 5:
            if change_pct > 20:
                return "Massive volume spike with breakout - likely news catalyst or squeeze", ChangeCategory.VOLUME_SPIKE
            elif change_pct < -20:
                return "Massive volume on breakdown - likely news or earnings miss", ChangeCategory.NEWS

        # Technical patterns
        day_data = ticker_data.get('day', {})
        prev_data = ticker_data.get('prevDay', {})

        if day_data and prev_data:
            day_range = day_data.get('h', 0) - day_data.get('l', 0)
            prev_close = prev_data.get('c', 0)

            # Gap analysis
            if prev_close > 0:
                gap_pct = ((day_data.get('o', 0) - prev_close) / prev_close) * 100

                if gap_pct > 5:
                    return f"Gapped up {gap_pct:.1f}% - pre-market catalyst", ChangeCategory.NEWS
                elif gap_pct < -5:
                    return f"Gapped down {gap_pct:.1f}% - negative pre-market news", ChangeCategory.NEWS

        # Momentum-based attribution
        if change_pct > 10 and rvol > 2:
            return "Strong momentum with volume confirmation", ChangeCategory.TECHNICAL_BREAKOUT
        elif change_pct < -10 and rvol > 2:
            return "Heavy selling with volume confirmation", ChangeCategory.TECHNICAL_BREAKDOWN
        elif change_pct > 5:
            return "Moderate upward momentum", ChangeCategory.TECHNICAL_BREAKOUT
        elif change_pct < -5:
            return "Moderate selling pressure", ChangeCategory.PROFIT_TAKING
        else:
            return "Normal trading range", ChangeCategory.UNKNOWN

    def process_ticker_data(self, ticker_data: Dict) -> Optional[StockPerformance]:
        """Process raw ticker data into StockPerformance object"""
        try:
            ticker = ticker_data.get('ticker', '')
            day = ticker_data.get('day', {})
            prev = ticker_data.get('prevDay', {})

            if not day or not prev:
                return None

            open_price = day.get('o', 0)
            close_price = day.get('c', 0)
            prev_close = prev.get('c', 0)

            if prev_close == 0:
                return None

            change_pct = ((close_price - prev_close) / prev_close) * 100
            change_dollars = close_price - prev_close

            volume = day.get('v', 0)
            avg_volume = prev.get('v', 0)  # Using prev day as proxy for avg
            rvol = self.calculate_relative_volume(volume, avg_volume)

            attribution, category = self.attribute_change(ticker_data, change_pct)

            return StockPerformance(
                ticker=ticker,
                company=ticker,  # Would need separate API call for company name
                sector="",  # Would need separate API call for sector
                open_price=round(open_price, 2),
                close_price=round(close_price, 2),
                high=round(day.get('h', 0), 2),
                low=round(day.get('l', 0), 2),
                volume=volume,
                avg_volume=avg_volume,
                change_pct=round(change_pct, 2),
                change_dollars=round(change_dollars, 2),
                relative_volume=rvol,
                attribution=attribution,
                attribution_category=category
            )
        except Exception as e:
            print(f"[ERROR] Failed to process ticker: {e}")
            return None

    def process_finviz_data(self, finviz_data: Dict) -> Optional[StockPerformance]:
        """Process Finviz data into StockPerformance object"""
        try:
            ticker = finviz_data.get('ticker', '')
            price = finviz_data.get('price', 0)
            change_pct = finviz_data.get('change_pct', 0)
            volume = finviz_data.get('volume', 0)

            # Calculate change in dollars
            if change_pct != 0:
                prev_price = price / (1 + change_pct / 100)
                change_dollars = price - prev_price
            else:
                change_dollars = 0
                prev_price = price

            # Attribute the change based on magnitude and context
            if abs(change_pct) > 20:
                if change_pct > 0:
                    attribution = "Major breakout - likely news catalyst or squeeze"
                    category = ChangeCategory.NEWS
                else:
                    attribution = "Major breakdown - likely negative news"
                    category = ChangeCategory.NEWS
            elif abs(change_pct) > 10:
                if change_pct > 0:
                    attribution = "Strong momentum breakout"
                    category = ChangeCategory.TECHNICAL_BREAKOUT
                else:
                    attribution = "Heavy selling pressure"
                    category = ChangeCategory.TECHNICAL_BREAKDOWN
            elif abs(change_pct) > 5:
                if change_pct > 0:
                    attribution = "Moderate upward momentum"
                    category = ChangeCategory.TECHNICAL_BREAKOUT
                else:
                    attribution = "Moderate selling"
                    category = ChangeCategory.PROFIT_TAKING
            else:
                attribution = "Normal trading range"
                category = ChangeCategory.UNKNOWN

            return StockPerformance(
                ticker=ticker,
                company=finviz_data.get('company', ticker),
                sector=finviz_data.get('sector', ''),
                open_price=0,  # Not available from Finviz screener
                close_price=round(price, 2),
                high=0,
                low=0,
                volume=volume,
                avg_volume=0,  # Would need separate lookup
                change_pct=round(change_pct, 2),
                change_dollars=round(change_dollars, 2),
                relative_volume=0.0,  # Not directly available
                attribution=attribution,
                attribution_category=category
            )
        except Exception as e:
            print(f"[ERROR] Failed to process Finviz ticker: {e}")
            return None

    def load_screened_stocks(self) -> List[Dict]:
        """Load today's screened stocks for additional context"""
        try:
            screened_file = os.path.join(os.path.dirname(__file__), 'screened_stocks.json')
            with open(screened_file, 'r') as f:
                data = json.load(f)

            # Get today's entries
            today = datetime.datetime.now(self.est).date()
            today_entries = []

            for entry in data:
                entry_date = datetime.datetime.fromisoformat(entry['timestamp']).date()
                if entry_date == today:
                    today_entries.append(entry)

            return today_entries
        except Exception as e:
            print(f"[WARN] Could not load screened stocks: {e}")
            return []

    def generate_report(self, date: datetime.date = None, live: bool = False) -> Dict:
        """Generate the daily report"""
        if date is None:
            date = datetime.datetime.now(self.est).date()

        print(f"\n{'='*70}")
        print(f"DAILY TRADING REPORT - {date.strftime('%Y-%m-%d')}")
        if live:
            print(f"(LIVE INTRADAY - {datetime.datetime.now(self.est).strftime('%H:%M:%S %Z')})")
        print(f"{'='*70}\n")

        gainers = []
        losers = []

        if self.use_finviz:
            # Use Finviz for gainers/losers (works pre-market and during market hours)
            print("[REPORT] Fetching top gainers from Finviz...")
            gainers_raw = FinvizScreener.get_top_gainers_today(15)

            print("[REPORT] Fetching top losers from Finviz...")
            losers_raw = FinvizScreener.get_top_losers_today(15)

            # Process Finviz data
            for t in gainers_raw:
                perf = self.process_finviz_data(t)
                if perf:
                    gainers.append(perf)

            for t in losers_raw:
                perf = self.process_finviz_data(t)
                if perf:
                    losers.append(perf)
        else:
            # Use Polygon.io API (only works during market hours)
            print("[REPORT] Fetching top gainers from Polygon...")
            gainers_raw = self.get_gainers_losers("gainers", 15)

            print("[REPORT] Fetching top losers from Polygon...")
            losers_raw = self.get_gainers_losers("losers", 15)

            # Process Polygon data
            for t in gainers_raw:
                perf = self.process_ticker_data(t)
                if perf:
                    gainers.append(perf)

            for t in losers_raw:
                perf = self.process_ticker_data(t)
                if perf:
                    losers.append(perf)

        # Sort by change percentage
        gainers.sort(key=lambda x: x.change_pct, reverse=True)
        losers.sort(key=lambda x: x.change_pct)

        # Load screened stocks for context
        screened = self.load_screened_stocks()

        # Build report
        report = {
            'date': date.isoformat(),
            'generated_at': datetime.datetime.now(self.est).isoformat(),
            'is_live': live,
            'summary': {
                'total_gainers_analyzed': len(gainers),
                'total_losers_analyzed': len(losers),
                'avg_gainer_change': round(sum(g.change_pct for g in gainers) / len(gainers), 2) if gainers else 0,
                'avg_loser_change': round(sum(l.change_pct for l in losers) / len(losers), 2) if losers else 0,
                'avg_gainer_rvol': round(sum(g.relative_volume for g in gainers) / len(gainers), 2) if gainers else 0,
                'avg_loser_rvol': round(sum(l.relative_volume for l in losers) / len(losers), 2) if losers else 0,
            },
            'top_gainers': [asdict(g) for g in gainers[:10]],
            'top_losers': [asdict(l) for l in losers[:10]],
            'screened_performance': [],
            'attribution_summary': {}
        }

        # Categorize attributions
        all_stocks = gainers + losers
        attribution_counts = {}
        for stock in all_stocks:
            cat = stock.attribution_category.value
            attribution_counts[cat] = attribution_counts.get(cat, 0) + 1

        report['attribution_summary'] = attribution_counts

        # Print report
        self._print_report(report, gainers, losers)

        # Save report
        report_file = os.path.join(
            self.report_dir,
            f"daily_report_{date.strftime('%Y-%m-%d')}.json"
        )
        with open(report_file, 'w') as f:
            # Convert ChangeCategory enum to string for JSON serialization
            json_report = json.loads(json.dumps(report, default=str))
            json.dump(json_report, f, indent=2)

        print(f"\n[REPORT] Saved to {report_file}")

        return report

    def _print_report(self, report: Dict, gainers: List[StockPerformance],
                      losers: List[StockPerformance]):
        """Print formatted report to console"""

        # Summary
        print("=" * 70)
        print("MARKET SUMMARY")
        print("=" * 70)
        summary = report['summary']
        print(f"  Gainers Analyzed: {summary['total_gainers_analyzed']}")
        print(f"  Losers Analyzed:  {summary['total_losers_analyzed']}")
        print(f"  Avg Gainer Move:  +{summary['avg_gainer_change']:.2f}%")
        print(f"  Avg Loser Move:   {summary['avg_loser_change']:.2f}%")
        print(f"  Avg Gainer RVOL:  {summary['avg_gainer_rvol']:.1f}x")
        print(f"  Avg Loser RVOL:   {summary['avg_loser_rvol']:.1f}x")

        # Top Gainers
        print("\n" + "=" * 70)
        print("TOP 10 GAINERS")
        print("=" * 70)
        print(f"{'Ticker':<8} {'Price':>10} {'Change':>10} {'RVOL':>8} {'Attribution':<30}")
        print("-" * 70)

        for g in gainers[:10]:
            print(f"{g.ticker:<8} ${g.close_price:>8.2f} {g.change_pct:>+9.2f}% {g.relative_volume:>7.1f}x {g.attribution[:30]}")

        # Top Losers
        print("\n" + "=" * 70)
        print("TOP 10 LOSERS")
        print("=" * 70)
        print(f"{'Ticker':<8} {'Price':>10} {'Change':>10} {'RVOL':>8} {'Attribution':<30}")
        print("-" * 70)

        for l in losers[:10]:
            print(f"{l.ticker:<8} ${l.close_price:>8.2f} {l.change_pct:>+9.2f}% {l.relative_volume:>7.1f}x {l.attribution[:30]}")

        # Attribution Summary
        print("\n" + "=" * 70)
        print("ATTRIBUTION BREAKDOWN")
        print("=" * 70)
        for cat, count in sorted(report['attribution_summary'].items(),
                                  key=lambda x: x[1], reverse=True):
            pct = (count / (len(gainers) + len(losers))) * 100 if (gainers or losers) else 0
            print(f"  {cat:<25} {count:>3} stocks ({pct:>5.1f}%)")

    def generate_trade_review(self, trades: List[Dict]) -> Dict:
        """Review specific trades from the day"""
        print("\n" + "=" * 70)
        print("TRADE REVIEW")
        print("=" * 70)

        review = {
            'total_trades': len(trades),
            'winners': 0,
            'losers': 0,
            'total_pnl': 0,
            'best_trade': None,
            'worst_trade': None,
            'trades': []
        }

        for trade in trades:
            ticker = trade.get('ticker', '')
            entry = trade.get('entry_price', 0)
            exit_price = trade.get('exit_price', 0)
            shares = trade.get('shares', 0)

            if entry > 0 and exit_price > 0:
                pnl = (exit_price - entry) * shares
                pnl_pct = ((exit_price - entry) / entry) * 100

                trade_result = {
                    'ticker': ticker,
                    'entry': entry,
                    'exit': exit_price,
                    'shares': shares,
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2)
                }

                review['trades'].append(trade_result)
                review['total_pnl'] += pnl

                if pnl > 0:
                    review['winners'] += 1
                else:
                    review['losers'] += 1

                if review['best_trade'] is None or pnl > review['best_trade']['pnl']:
                    review['best_trade'] = trade_result
                if review['worst_trade'] is None or pnl < review['worst_trade']['pnl']:
                    review['worst_trade'] = trade_result

        review['total_pnl'] = round(review['total_pnl'], 2)
        review['win_rate'] = round(review['winners'] / len(trades) * 100, 1) if trades else 0

        # Print summary
        print(f"  Total Trades:  {review['total_trades']}")
        print(f"  Winners:       {review['winners']}")
        print(f"  Losers:        {review['losers']}")
        print(f"  Win Rate:      {review['win_rate']}%")
        print(f"  Total P&L:     ${review['total_pnl']:+,.2f}")

        if review['best_trade']:
            bt = review['best_trade']
            print(f"\n  Best Trade:    {bt['ticker']} ${bt['pnl']:+,.2f} ({bt['pnl_pct']:+.1f}%)")
        if review['worst_trade']:
            wt = review['worst_trade']
            print(f"  Worst Trade:   {wt['ticker']} ${wt['pnl']:+,.2f} ({wt['pnl_pct']:+.1f}%)")

        return review


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Daily Trading Report Generator')
    parser.add_argument('--date', type=str, help='Report date (YYYY-MM-DD)')
    parser.add_argument('--live', action='store_true', help='Generate live intraday report')
    parser.add_argument('--tickers', type=str, help='Comma-separated tickers to analyze')
    args = parser.parse_args()

    # Get API key
    api_key = os.getenv('MASSIVE_API_KEY', '')
    if not api_key:
        print("ERROR: MASSIVE_API_KEY not set")
        sys.exit(1)

    # Create generator
    generator = DailyReportGenerator(api_key)

    # Parse date
    report_date = None
    if args.date:
        report_date = datetime.datetime.strptime(args.date, '%Y-%m-%d').date()

    # Generate report
    generator.generate_report(date=report_date, live=args.live)


if __name__ == '__main__':
    main()
