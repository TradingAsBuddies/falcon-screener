#!/usr/bin/env python3
"""
Finviz Elite CSV Screener
Fetches stock data from Finviz Elite CSV export with 5-minute performance
"""

import os
import csv
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass
from io import StringIO

@dataclass
class StockPerformance:
    """Stock with performance data"""
    ticker: str
    performance_5min: float  # Percentage
    raw_data: Dict  # All CSV columns

    def __repr__(self):
        return f"{self.ticker}: {self.performance_5min:+.2f}%"


class FinvizCSVScreener:
    """Fetch and parse Finviz Elite CSV exports"""

    def __init__(self, auth_key: str):
        self.auth_key = auth_key
        self.base_url = "https://elite.finviz.com/export.ashx"

    def fetch_csv(self, view: int = 152, columns: str = "1,93",
                  filters: str = None) -> Optional[str]:
        """
        Fetch CSV data from Finviz Elite

        Args:
            view: View type (152 for custom)
            columns: Comma-separated column IDs (1=Ticker, 93=Performance 5min)
            filters: Optional filters (e.g., "sh_avgvol_o750,sh_price_u20")

        Returns:
            CSV data as string, or None if error
        """
        params = {
            'v': view,
            'c': columns,
            'auth': self.auth_key
        }

        if filters:
            params['f'] = filters

        try:
            response = requests.get(self.base_url, params=params, timeout=15)
            response.raise_for_status()
            return response.text

        except requests.exceptions.HTTPError as e:
            print(f"[FINVIZ CSV] HTTP error: {e.response.status_code}")
            return None
        except requests.exceptions.Timeout:
            print(f"[FINVIZ CSV] Request timeout")
            return None
        except Exception as e:
            print(f"[FINVIZ CSV] Error: {type(e).__name__}")
            return None

    def parse_csv(self, csv_data: str) -> List[Dict]:
        """
        Parse CSV data into list of dictionaries

        Args:
            csv_data: CSV string

        Returns:
            List of stock data dictionaries
        """
        stocks = []
        reader = csv.DictReader(StringIO(csv_data))

        for row in reader:
            stocks.append(row)

        return stocks

    def get_stocks_with_5min_performance(self, filters: str = None,
                                         additional_columns: List[int] = None) -> List[StockPerformance]:
        """
        Fetch stocks with 5-minute performance data

        Args:
            filters: Optional Finviz filters (e.g., "sh_avgvol_o750,sh_price_u20,ta_rsi_os40")
            additional_columns: Additional column IDs to include (e.g., [2, 3, 6] for company, sector, market cap)

        Returns:
            List of StockPerformance objects
        """
        # Build columns string: always include ticker (1) and 5-min performance (93)
        columns = "1,93"  # Ticker, Performance (5 Minutes)

        if additional_columns:
            columns += "," + ",".join(map(str, additional_columns))

        print(f"[FINVIZ CSV] Fetching stocks with filters: {filters or 'none'}")
        print(f"[FINVIZ CSV] Columns: {columns}")

        csv_data = self.fetch_csv(view=152, columns=columns, filters=filters)

        if not csv_data:
            print("[FINVIZ CSV] Failed to fetch data")
            return []

        stocks = self.parse_csv(csv_data)
        print(f"[FINVIZ CSV] Parsed {len(stocks)} stocks")

        # Convert to StockPerformance objects
        results = []
        for stock in stocks:
            ticker = stock.get('Ticker', '')
            perf_str = stock.get('Performance (5 Minutes)', '0.00%')

            # Parse percentage (remove % sign and convert to float)
            try:
                perf_5min = float(perf_str.strip('%'))
            except (ValueError, AttributeError):
                perf_5min = 0.0

            results.append(StockPerformance(
                ticker=ticker,
                performance_5min=perf_5min,
                raw_data=stock
            ))

        return results

    def get_top_movers(self, filters: str = None,
                      top_n: int = 20,
                      direction: str = 'both') -> List[StockPerformance]:
        """
        Get top N 5-minute movers

        Args:
            filters: Optional Finviz filters
            top_n: Number of top movers to return
            direction: 'up' (gainers), 'down' (losers), 'both' (absolute movers)

        Returns:
            List of top N StockPerformance objects sorted by 5-min performance
        """
        all_stocks = self.get_stocks_with_5min_performance(filters=filters)

        if direction == 'up':
            # Only gainers, sorted descending
            stocks = [s for s in all_stocks if s.performance_5min > 0]
            stocks.sort(key=lambda x: x.performance_5min, reverse=True)
        elif direction == 'down':
            # Only losers, sorted ascending (most negative first)
            stocks = [s for s in all_stocks if s.performance_5min < 0]
            stocks.sort(key=lambda x: x.performance_5min)
        else:
            # Both directions - absolute value movers
            stocks = sorted(all_stocks, key=lambda x: abs(x.performance_5min), reverse=True)

        return stocks[:top_n]


# Column ID reference (commonly used):
# 1 = Ticker
# 2 = Company
# 3 = Sector
# 4 = Industry
# 6 = Market Cap
# 7 = P/E
# 8 = Price
# 9 = Change
# 10 = Volume
# 65 = RSI (14)
# 66 = Relative Volume
# 93 = Performance (5 Minutes)
# For full list, configure on finviz.com and check the export URL


def main():
    """Test the Finviz CSV screener"""
    from dotenv import load_dotenv
    import sys

    load_dotenv('/home/ospartners/.local/.env')

    # Get auth key from environment
    auth_key = os.getenv('FINVIZ_AUTH_KEY')
    if not auth_key:
        print("ERROR: FINVIZ_AUTH_KEY environment variable not set")
        print("Please add it to your .env file")
        sys.exit(1)

    screener = FinvizCSVScreener(auth_key)

    print("=" * 80)
    print("FINVIZ CSV SCREENER - 5-MINUTE PERFORMANCE TEST")
    print("=" * 80)
    print()

    # Filters: average volume > 750K, price < $20, RSI < 40
    filters = "sh_avgvol_o750,sh_price_u20,ta_rsi_os40"

    print("Getting top 20 5-minute movers with filters:")
    print(f"  - Average volume > 750K")
    print(f"  - Price < $20")
    print(f"  - RSI < 40 (oversold)")
    print()

    top_movers = screener.get_top_movers(filters=filters, top_n=20, direction='both')

    if not top_movers:
        print("No stocks found matching criteria")
        return

    print("=" * 80)
    print(f"TOP 20 5-MINUTE MOVERS (from {len(top_movers)} matches)")
    print("=" * 80)

    for i, stock in enumerate(top_movers, 1):
        print(f"{i:2d}. {stock.ticker:6s} {stock.performance_5min:+6.2f}%")

    print("\n" + "=" * 80)
    print("TOP 10 GAINERS (5-minute)")
    print("=" * 80)

    top_gainers = screener.get_top_movers(filters=filters, top_n=10, direction='up')
    for i, stock in enumerate(top_gainers, 1):
        print(f"{i:2d}. {stock.ticker:6s} {stock.performance_5min:+6.2f}%")

    print("\n" + "=" * 80)
    print("TOP 10 LOSERS (5-minute)")
    print("=" * 80)

    top_losers = screener.get_top_movers(filters=filters, top_n=10, direction='down')
    for i, stock in enumerate(top_losers, 1):
        print(f"{i:2d}. {stock.ticker:6s} {stock.performance_5min:+6.2f}%")


if __name__ == '__main__':
    main()
