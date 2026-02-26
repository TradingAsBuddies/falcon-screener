#!/usr/bin/env python3
"""
3rd Day Setup (Trapped Shorts) Pattern Detector

Identifies a specific 3-day candlestick pattern:
1. Day 1: Momentum spike (large bullish candle, high volume)
2. Day 2: Bearish harami or near-harami (smaller bearish candle inside Day 1's body)
3. Day 3: Price crosses above Day 2's high — shorts from Day 2 are trapped,
   fueling a move toward Day 1's high

This is a rules-based pattern detector, not AI-delegated analysis.
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from falcon_core import get_db_manager, get_data_feed

logger = logging.getLogger(__name__)


@dataclass
class ThirdDayPatternConfig:
    """Configurable thresholds for 3rd Day Setup detection"""

    # Day 1: minimum bullish body as % of price
    min_day1_body_pct: float = 3.0

    # Day 1: minimum relative volume (vs avg volume)
    min_day1_rvol_ratio: float = 1.5

    # Day 2: tolerance for near-harami (body can protrude this % beyond Day 1 body)
    harami_tolerance_pct: float = 0.5

    # Minimum average daily volume
    min_avg_volume: int = 500_000


@dataclass
class PatternMatch:
    """Result of pattern detection for a single ticker"""

    symbol: str
    score: float  # 0.0 - 1.0 composite score

    # Day 1 metrics
    day1_body_pct: float
    day1_rvol: float

    # Day 2 metrics
    harami_quality: float  # 0.0 - 1.0 (1.0 = perfect harami)

    # Day 3 trigger
    day3_trigger: bool  # True if Day 3 open/current > Day 2 high

    # Key levels
    day1_high: float  # Target
    day2_high: float  # Entry trigger
    day2_low: float   # Stop loss

    # Raw bar data for reference
    day1_open: float = 0.0
    day1_close: float = 0.0
    day2_open: float = 0.0
    day2_close: float = 0.0
    day3_open: float = 0.0
    day3_close: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'pattern_score': self.score,
            'day1_body_pct': round(self.day1_body_pct, 2),
            'day1_rvol': round(self.day1_rvol, 2),
            'harami_quality': round(self.harami_quality, 2),
            'day3_trigger': self.day3_trigger,
            'day1_high': round(self.day1_high, 2),
            'day2_high': round(self.day2_high, 2),
            'day2_low': round(self.day2_low, 2),
        }


class ThirdDayPatternDetector:
    """
    Detects the 3rd Day Setup (Trapped Shorts) candlestick pattern.

    Data strategy:
    - Tries PostgreSQL daily_bars table first (single query for all symbols)
    - Falls back to DataFeed.get_historical_data() for small batches
    - Average volume comes from Finviz data already in the pipeline
    """

    def __init__(self, config: Optional[ThirdDayPatternConfig] = None,
                 db=None, data_feed=None):
        self.config = config or ThirdDayPatternConfig()
        self._db = db
        self._data_feed = data_feed

    def _get_db(self):
        if self._db is None:
            try:
                self._db = get_db_manager()
            except Exception as e:
                logger.warning(f"[3RDDAY] Could not get db_manager: {e}")
        return self._db

    def _get_data_feed(self):
        if self._data_feed is None:
            try:
                self._data_feed = get_data_feed()
            except Exception as e:
                logger.warning(f"[3RDDAY] Could not get data_feed: {e}")
        return self._data_feed

    def fetch_bars(self, symbols: List[str],
                   num_days: int = 5) -> Dict[str, pd.DataFrame]:
        """
        Fetch last N trading days of daily bars for symbols.

        Tries PostgreSQL daily_bars table first (single query for all tickers),
        falls back to DataFeed.get_historical_data() for small batches.

        Args:
            symbols: List of ticker symbols
            num_days: Number of trading days to fetch (default 5 for safety margin)

        Returns:
            Dict mapping symbol -> DataFrame with columns: open, high, low, close, volume
        """
        if not symbols:
            return {}

        # Calendar days to cover num_days trading days (weekends + holidays buffer)
        calendar_days = num_days * 2 + 5
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=calendar_days)

        bars_by_symbol: Dict[str, pd.DataFrame] = {}

        # Try database first (batch query)
        db = self._get_db()
        if db:
            try:
                bars_by_symbol = self._fetch_from_db(
                    db, symbols, start_date, end_date, num_days
                )
                if bars_by_symbol:
                    logger.info(f"[3RDDAY] Fetched bars from DB for "
                                f"{len(bars_by_symbol)}/{len(symbols)} symbols")
            except Exception as e:
                logger.warning(f"[3RDDAY] DB fetch failed: {e}")

        # Fall back to DataFeed for missing symbols
        missing = [s for s in symbols if s not in bars_by_symbol]
        if missing:
            feed = self._get_data_feed()
            if feed:
                for symbol in missing:
                    try:
                        df = feed.get_historical_data(
                            symbol=symbol,
                            start_date=start_date.strftime('%Y-%m-%d'),
                            end_date=end_date.strftime('%Y-%m-%d'),
                            interval='1d',
                        )
                        if df is not None and len(df) >= 3:
                            bars_by_symbol[symbol] = df.tail(num_days)
                    except Exception as e:
                        logger.debug(f"[3RDDAY] DataFeed failed for {symbol}: {e}")

                logger.info(f"[3RDDAY] Fetched bars from DataFeed for "
                            f"{len(bars_by_symbol) - len([s for s in symbols if s in bars_by_symbol])}"
                            f" additional symbols")

        return bars_by_symbol

    def _fetch_from_db(self, db, symbols: List[str],
                       start_date: datetime.date, end_date: datetime.date,
                       num_days: int) -> Dict[str, pd.DataFrame]:
        """Batch-fetch daily bars from PostgreSQL"""
        placeholders = ','.join(['%s'] * len(symbols))
        query = f"""
            SELECT symbol, date as timestamp, open, high, low, close, volume
            FROM daily_bars
            WHERE symbol IN ({placeholders})
            AND date >= %s
            AND date <= %s
            ORDER BY symbol, date
        """
        params = list(symbols) + [start_date, end_date]
        rows = db.execute(query, params, fetch='all')

        if not rows:
            return {}

        result = {}
        for row in rows:
            sym = row['symbol']
            if sym not in result:
                result[sym] = []
            result[sym].append({
                'timestamp': row['timestamp'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': int(row['volume']),
            })

        bars_by_symbol = {}
        for sym, data in result.items():
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp').sort_index()
            # Keep only the last num_days trading days
            bars_by_symbol[sym] = df.tail(num_days)

        return bars_by_symbol

    def detect(self, symbols: List[str],
               bars_data: Dict[str, pd.DataFrame],
               avg_volumes: Dict[str, float]) -> List[PatternMatch]:
        """
        Core pattern matching on 3-day OHLCV data.

        Args:
            symbols: List of ticker symbols to check
            bars_data: Dict mapping symbol -> DataFrame (open, high, low, close, volume)
            avg_volumes: Dict mapping symbol -> average daily volume (from Finviz)

        Returns:
            List of PatternMatch for symbols that match the pattern
        """
        matches = []

        for symbol in symbols:
            df = bars_data.get(symbol)
            if df is None or len(df) < 3:
                continue

            avg_vol = avg_volumes.get(symbol, 0)
            if avg_vol < self.config.min_avg_volume:
                continue

            # Use the last 3 bars
            bars = df.iloc[-3:]
            day1 = bars.iloc[0]
            day2 = bars.iloc[1]
            day3 = bars.iloc[2]

            match = self._check_pattern(symbol, day1, day2, day3, avg_vol)
            if match:
                matches.append(match)

        # Sort by score descending
        matches.sort(key=lambda m: m.score, reverse=True)

        logger.info(f"[3RDDAY] Found {len(matches)} pattern matches "
                    f"out of {len(symbols)} symbols checked")
        return matches

    def _check_pattern(self, symbol: str, day1, day2, day3,
                       avg_vol: float) -> Optional[PatternMatch]:
        """
        Check if a 3-bar sequence matches the Trapped Shorts pattern.

        Returns PatternMatch if pattern is detected, None otherwise.
        """
        # --- Day 1: Momentum spike (bullish candle with high volume) ---
        day1_open = float(day1['open'])
        day1_close = float(day1['close'])
        day1_high = float(day1['high'])
        day1_low = float(day1['low'])
        day1_volume = float(day1['volume'])

        # Must be bullish (close > open)
        if day1_close <= day1_open:
            return None

        # Body size as percentage of price
        day1_body = day1_close - day1_open
        day1_body_pct = (day1_body / day1_open) * 100

        if day1_body_pct < self.config.min_day1_body_pct:
            return None

        # Relative volume check
        day1_rvol = day1_volume / avg_vol if avg_vol > 0 else 0
        if day1_rvol < self.config.min_day1_rvol_ratio:
            return None

        # --- Day 2: Bearish harami or near-harami ---
        day2_open = float(day2['open'])
        day2_close = float(day2['close'])
        day2_high = float(day2['high'])
        day2_low = float(day2['low'])

        # Must be bearish (close < open)
        if day2_close >= day2_open:
            return None

        # Harami check: Day 2 body should be inside Day 1 body (with tolerance)
        tolerance = day1_close * (self.config.harami_tolerance_pct / 100)

        # Day 2 open should be at or below Day 1 close (with tolerance)
        if day2_open > day1_close + tolerance:
            return None

        # Day 2 close should be at or above Day 1 open (with tolerance)
        if day2_close < day1_open - tolerance:
            return None

        # Harami quality: how well Day 2 body fits inside Day 1 body
        # 1.0 = perfect harami, lower = more protrusion
        day2_body_top = max(day2_open, day2_close)
        day2_body_bottom = min(day2_open, day2_close)
        day1_body_top = day1_close  # bullish: close > open
        day1_body_bottom = day1_open

        # Measure protrusion relative to Day 1 body size
        top_protrusion = max(0, day2_body_top - day1_body_top)
        bottom_protrusion = max(0, day1_body_bottom - day2_body_bottom)
        total_protrusion = top_protrusion + bottom_protrusion
        harami_quality = max(0, 1.0 - (total_protrusion / day1_body)) if day1_body > 0 else 0

        # Day 2 body should be smaller than Day 1 body
        day2_body = abs(day2_open - day2_close)
        if day2_body >= day1_body:
            return None

        # --- Day 3: Trigger check ---
        day3_open = float(day3['open'])
        day3_close = float(day3['close'])
        day3_high = float(day3['high'])

        # Day 3 triggers when price crosses above Day 2 high
        day3_trigger = day3_high > day2_high

        # --- Composite score ---
        # Weight components for ranking
        body_score = min(day1_body_pct / 8.0, 1.0)  # 8% body = perfect score
        rvol_score = min(day1_rvol / 3.0, 1.0)      # 3x rvol = perfect score
        harami_score = harami_quality
        trigger_score = 1.0 if day3_trigger else 0.3

        score = (
            body_score * 0.25 +
            rvol_score * 0.25 +
            harami_score * 0.25 +
            trigger_score * 0.25
        )

        return PatternMatch(
            symbol=symbol,
            score=round(score, 4),
            day1_body_pct=day1_body_pct,
            day1_rvol=day1_rvol,
            harami_quality=harami_quality,
            day3_trigger=day3_trigger,
            day1_high=day1_high,
            day2_high=day2_high,
            day2_low=day2_low,
            day1_open=day1_open,
            day1_close=day1_close,
            day2_open=day2_open,
            day2_close=day2_close,
            day3_open=day3_open,
            day3_close=day3_close,
        )

    def scan(self, symbols: List[str],
             avg_volumes: Optional[Dict[str, float]] = None) -> List[PatternMatch]:
        """
        Convenience method: fetch bars and detect patterns in one call.

        Args:
            symbols: List of ticker symbols
            avg_volumes: Optional pre-fetched average volumes. If None, uses
                         a default of config.min_avg_volume + 1 for all (caller
                         should provide real data from Finviz).

        Returns:
            List of PatternMatch results
        """
        if not symbols:
            return []

        # Fetch bars
        bars_data = self.fetch_bars(symbols)

        # Default avg volumes if not provided (assumes caller filters upstream)
        if avg_volumes is None:
            avg_volumes = {s: self.config.min_avg_volume + 1 for s in symbols}

        return self.detect(symbols, bars_data, avg_volumes)
