#!/usr/bin/env python3
"""
AI-Powered Stock Screener with Multiple Agent Backends
Supports: Claude (Anthropic), ChatGPT (OpenAI), Perplexity Sonar Pro
"""

import os
import re
import sys
import requests
import json
import time
import datetime
import pytz
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import schedule
import pandas as pd
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class AgentBackend(Enum):
    CLAUDE = "claude"
    CHATGPT = "chatgpt"
    PERPLEXITY = "perplexity"

@dataclass
class AgentConfig:
    """Configuration for AI agent"""
    backend: AgentBackend
    api_key: str
    model: str
    priority: int  # Lower number = higher priority

class AIAgentManager:
    """Manage multiple AI agent backends with fallback"""
    
    def __init__(self, agents: List[AgentConfig]):
        # Sort by priority
        self.agents = sorted(agents, key=lambda x: x.priority)
        self.last_used = None
    
    def _sanitize_error(self, error: Exception) -> str:
        """Sanitize error message to avoid exposing sensitive information"""
        error_str = str(error)
        # Mask patterns that look like API keys
        # Claude API keys (sk-ant-...)
        error_str = re.sub(r'sk-ant-[a-zA-Z0-9_-]{20,}', 'sk-ant-***REDACTED***', error_str)
        # OpenAI API keys (sk-... or sk-proj-...)
        error_str = re.sub(r'sk-(?:proj-)?[a-zA-Z0-9_-]{20,}', 'sk-***REDACTED***', error_str)
        # Perplexity API keys (pplx-...)
        error_str = re.sub(r'pplx-[a-zA-Z0-9_-]{20,}', 'pplx-***REDACTED***', error_str)
        # Bearer tokens (case-insensitive, including JWTs with dots)
        error_str = re.sub(
            r'[Bb]earer\s+[a-zA-Z0-9_.\-]{20,}',
            'Bearer ***REDACTED***',
            error_str
        )
        # Authorization header values
        error_str = re.sub(
            r'[Aa]uthorization["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_.\-]{20,}',
            'Authorization: ***REDACTED***',
            error_str
        )
        # Generic long alphanumeric strings that might be tokens (40+ chars)
        error_str = re.sub(
            r'[a-zA-Z0-9_-]{40,}',
            '***REDACTED***',
            error_str
        )
        return error_str

    def query(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """Query agents in priority order with fallback"""

        for agent in self.agents:
            try:
                print(f"[AGENT] Trying {agent.backend.value} ({agent.model})...")
                response = self._query_agent(agent, prompt, system_prompt)

                if response:
                    self.last_used = agent.backend
                    print(f"[AGENT] Success with {agent.backend.value}")
                    return response

            except requests.exceptions.HTTPError as e:
                # Handle HTTP errors without exposing sensitive details
                status_code = e.response.status_code if e.response else 'unknown'
                print(f"[AGENT] {agent.backend.value} failed: HTTP {status_code}")
                continue
            except requests.exceptions.Timeout:
                print(f"[AGENT] {agent.backend.value} failed: Request timeout")
                continue
            except requests.exceptions.ConnectionError:
                print(f"[AGENT] {agent.backend.value} failed: Connection error")
                continue
            except Exception as e:
                # Sanitize any other errors to prevent sensitive data exposure
                safe_error = self._sanitize_error(e)
                print(f"[AGENT] {agent.backend.value} failed: {safe_error}")
                continue

        print("[AGENT] All agents failed!")
        return None
    
    def _query_agent(self, agent: AgentConfig, prompt: str, 
                     system_prompt: Optional[str]) -> Optional[str]:
        """Query a specific agent backend"""
        
        if agent.backend == AgentBackend.CLAUDE:
            return self._query_claude(agent, prompt, system_prompt)
        elif agent.backend == AgentBackend.CHATGPT:
            return self._query_openai(agent, prompt, system_prompt)
        elif agent.backend == AgentBackend.PERPLEXITY:
            return self._query_perplexity(agent, prompt, system_prompt)
        
        return None
    
    def _query_claude(self, agent: AgentConfig, prompt: str, 
                      system_prompt: Optional[str]) -> str:
        """Query Claude API"""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": agent.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        messages = [{"role": "user", "content": prompt}]
        
        payload = {
            "model": agent.model,
            "max_tokens": 4000,
            "messages": messages
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        
        return response.json()["content"][0]["text"]
    
    def _query_openai(self, agent: AgentConfig, prompt: str,
                      system_prompt: Optional[str]) -> str:
        """Query OpenAI ChatGPT API"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {agent.api_key}"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": agent.model,
            "messages": messages,
            "max_tokens": 4000
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        
        return response.json()["choices"][0]["message"]["content"]
    
    def _query_perplexity(self, agent: AgentConfig, prompt: str,
                          system_prompt: Optional[str]) -> str:
        """Query Perplexity Sonar Pro API"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {agent.api_key}"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": agent.model,
            "messages": messages
        }
        
        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        
        return response.json()["choices"][0]["message"]["content"]


class FinvizScraper:
    """
    Fetch stocks from Finviz Elite CSV export with 5-minute performance sorting.

    This is a wrapper around the centralized FinvizClient that provides
    rate limiting and exponential backoff to avoid throttling.
    """

    def __init__(self, screener_url: str):
        self.screener_url = screener_url

        # Extract filters from URL
        import urllib.parse
        parsed = urllib.parse.urlparse(screener_url)
        params = urllib.parse.parse_qs(parsed.query)
        self.filters = params.get('f', [''])[0]

        # Use centralized Finviz client with rate limiting
        try:
            from finviz_client import get_finviz_client
            self._client = get_finviz_client()
        except ImportError:
            print("[FINVIZ] Warning: finviz_client not available, using legacy mode")
            self._client = None

    def get_stocks(self, sort_by_5min: bool = True, limit: int = None) -> List[Dict[str, str]]:
        """
        Fetch stocks from Finviz CSV export with rate limiting

        Args:
            sort_by_5min: Sort by 5-minute performance (default True)
            limit: Optional limit on number of stocks to return

        Returns:
            List of stock dictionaries
        """
        print(f"[FINVIZ] Fetching stocks with filters: {self.filters or 'none'}")

        # Use centralized client if available
        if self._client:
            stocks = self._client.get_stocks(
                filters=self.filters,
                sort_by_5min=sort_by_5min,
                limit=limit
            )

            # Convert to legacy format for compatibility
            legacy_stocks = []
            for stock in stocks:
                legacy_stock = {
                    'ticker': stock.get('ticker', ''),
                    'company': stock.get('company', ''),
                    'sector': stock.get('sector', ''),
                    'industry': stock.get('industry', ''),
                    'market_cap': stock.get('market_cap', ''),
                    'pe_ratio': stock.get('pe_ratio', ''),
                    'price': str(stock.get('price', '')),
                    'change': stock.get('change', ''),
                    'volume': str(stock.get('volume', '')),
                    'rsi': str(stock.get('rsi', '')),
                    'rel_volume': str(stock.get('rel_volume', '')),
                    'performance_5min': stock.get('performance_5min', 0),
                    'performance_5min_str': stock.get('performance_5min_str', '0.00%'),
                }
                legacy_stocks.append(legacy_stock)

            if legacy_stocks:
                print(f"[FINVIZ] Found {len(legacy_stocks)} stocks")
                print(f"[FINVIZ] Top mover: {legacy_stocks[0]['ticker']} ({legacy_stocks[0]['performance_5min']:+.2f}%)")

            return legacy_stocks

        # Fallback to legacy implementation if client not available
        return self._legacy_get_stocks(sort_by_5min, limit)

    def _legacy_get_stocks(self, sort_by_5min: bool = True, limit: int = None) -> List[Dict[str, str]]:
        """Legacy implementation without rate limiting (fallback only)"""
        import urllib.parse
        parsed = urllib.parse.urlparse(self.screener_url)
        params = urllib.parse.parse_qs(parsed.query)
        auth_key = params.get('auth', [''])[0]

        try:
            print(f"[FINVIZ LEGACY] Fetching stocks (no rate limiting)...")
            columns = "1,2,3,4,6,7,8,9,10,65,66,93"

            request_params = {
                'v': 152,
                'c': columns,
                'auth': auth_key
            }

            if self.filters:
                request_params['f'] = self.filters

            response = requests.get('https://elite.finviz.com/export.ashx',
                                   params=request_params, timeout=30)
            response.raise_for_status()

            import csv
            from io import StringIO

            reader = csv.DictReader(StringIO(response.text))
            stocks = []

            for row in reader:
                perf_5min_str = row.get('Performance (5 Minutes)', '0.00%')
                try:
                    perf_5min = float(perf_5min_str.strip('%'))
                except (ValueError, AttributeError):
                    perf_5min = 0.0

                stock = {
                    'ticker': row.get('Ticker', ''),
                    'company': row.get('Company', ''),
                    'sector': row.get('Sector', ''),
                    'industry': row.get('Industry', ''),
                    'market_cap': row.get('Market Cap', ''),
                    'pe_ratio': row.get('P/E', ''),
                    'price': row.get('Price', ''),
                    'change': row.get('Change', ''),
                    'volume': row.get('Volume', ''),
                    'rsi': row.get('RSI (14)', ''),
                    'rel_volume': row.get('Relative Volume', ''),
                    'performance_5min': perf_5min,
                    'performance_5min_str': perf_5min_str
                }
                stocks.append(stock)

            if sort_by_5min:
                import random
                random.shuffle(stocks)

                def sort_key(stock):
                    perf_5min = abs(stock.get('performance_5min', 0))
                    try:
                        rel_vol = float(stock.get('rel_volume', '0'))
                    except (ValueError, TypeError):
                        rel_vol = 0
                    try:
                        volume = int(stock.get('volume', '0').replace(',', ''))
                    except (ValueError, TypeError):
                        volume = 0
                    return (perf_5min, rel_vol, volume)

                stocks.sort(key=sort_key, reverse=True)

            if limit:
                stocks = stocks[:limit]

            print(f"[FINVIZ LEGACY] Found {len(stocks)} stocks")
            return stocks

        except Exception as e:
            print(f"[FINVIZ LEGACY] Error fetching: {e}")
            return []


class StockScreener:
    """AI-powered stock screener with scheduled runs"""

    def __init__(self, agent_manager: AIAgentManager,
                 finviz_url: str,
                 massive_api_key: str,
                 output_file: str = "screened_stocks.json",
                 manual_watchlist: List[str] = None):
        self.agent = agent_manager
        self.finviz = FinvizScraper(finviz_url)
        self.massive_api_key = massive_api_key
        self.output_file = output_file
        self.current_watchlist = []
        self.manual_watchlist = manual_watchlist or []

        # Timezone for scheduling
        self.est = pytz.timezone('US/Eastern')

    def load_manual_watchlist(self) -> List[Dict]:
        """Load manual watchlist tickers and fetch their data"""
        if not self.manual_watchlist:
            return []

        print(f"[WATCHLIST] Loading {len(self.manual_watchlist)} manual tickers: {', '.join(self.manual_watchlist)}")

        manual_stocks = []
        for ticker in self.manual_watchlist:
            ticker = ticker.strip().upper()
            if not ticker:
                continue

            # Fetch data from Polygon.io
            data = self.get_stock_data(ticker)
            if data:
                stock = {
                    'ticker': ticker,
                    'company': f'{ticker} (Manual)',
                    'sector': 'Manual Watchlist',
                    'industry': '',
                    'market_cap': '',
                    'pe_ratio': '',
                    'price': str(data.get('current_price', '')),
                    'change': f"{data.get('change_pct', 0):.2f}%",
                    'volume': str(data.get('volume', '')),
                    'rsi': '',
                    'rel_volume': '',
                    'performance_5min': 0,
                    'performance_5min_str': '0.00%',
                    'source': 'manual_watchlist'
                }
                stock.update(data)
                manual_stocks.append(stock)
                print(f"[WATCHLIST] {ticker}: ${data.get('current_price', 'N/A'):.2f} ({data.get('change_pct', 0):+.2f}%)")
            else:
                print(f"[WATCHLIST] {ticker}: Failed to fetch data")

            time.sleep(0.3)  # Rate limiting

        return manual_stocks

    def merge_stock_lists(self, finviz_stocks: List[Dict], manual_stocks: List[Dict]) -> List[Dict]:
        """Merge Finviz and manual stocks, prioritizing manual entries"""
        # Create a set of manual tickers
        manual_tickers = {s['ticker'].upper() for s in manual_stocks}

        # Filter out duplicates from Finviz list
        filtered_finviz = [s for s in finviz_stocks if s['ticker'].upper() not in manual_tickers]

        # Manual stocks go first (priority), then Finviz stocks
        merged = manual_stocks + filtered_finviz

        print(f"[MERGE] Combined {len(manual_stocks)} manual + {len(filtered_finviz)} Finviz = {len(merged)} total")

        return merged
    
    def get_stock_data(self, ticker: str) -> Optional[Dict]:
        """Get additional stock data from Massive.com"""
        try:
            url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
            params = {'apiKey': self.massive_api_key}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data['status'] == 'OK' and 'ticker' in data:
                ticker_data = data['ticker']
                return {
                    'current_price': ticker_data['day']['c'],
                    'volume': ticker_data['day']['v'],
                    'day_high': ticker_data['day']['h'],
                    'day_low': ticker_data['day']['l'],
                    'prev_close': ticker_data['prevDay']['c'],
                    'change_pct': ((ticker_data['day']['c'] - ticker_data['prevDay']['c']) / 
                                  ticker_data['prevDay']['c'] * 100)
                }
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 'unknown'
            print(f"[DATA] Error fetching {ticker}: HTTP {status_code}")
        except requests.exceptions.Timeout:
            print(f"[DATA] Error fetching {ticker}: Request timeout")
        except requests.exceptions.ConnectionError:
            print(f"[DATA] Error fetching {ticker}: Connection error")
        except Exception:
            print(f"[DATA] Error fetching {ticker}: Unexpected error")

        return None
    
    def analyze_stocks_with_ai(self, stocks: List[Dict], 
                               analysis_type: str) -> List[Dict]:
        """Use AI to analyze and rank stocks"""
        
        system_prompt = """You are an expert stock analyst and trader. Your job is to analyze stocks 
and provide actionable trading recommendations. Focus on technical indicators, market sentiment, 
recent news, and fundamental data. Be specific and data-driven in your analysis."""
        
        if analysis_type == "morning":
            user_prompt = f"""Analyze these {len(stocks)} stocks for day trading opportunities. 
Consider: momentum, volume, volatility, sector trends, and pre-market activity.

Stocks to analyze:
{json.dumps(stocks[:20], indent=2)}

Provide your top 5-10 picks with:
1. Ticker symbol
2. Entry price range
3. Target price
4. Stop loss
5. Reasoning (2-3 sentences)
6. Risk level (Low/Medium/High)
7. Confidence score (1-10)

Format as JSON array."""
        
        elif analysis_type == "midday":
            user_prompt = f"""Review these stocks for afternoon trading opportunities. 
Consider: price action so far today, volume patterns, momentum shifts, and sector rotation.

Stocks to analyze:
{json.dumps(stocks[:20], indent=2)}

Update your recommendations considering morning performance. Format as JSON array with:
- Ticker, Entry, Target, Stop, Reasoning, Risk, Confidence"""
        
        else:  # evening
            user_prompt = f"""Evening review: Analyze today's market action and these stocks for tomorrow.
Consider: earnings reports, after-hours moves, financial news, sector performance, and setup quality.

Stocks to analyze:
{json.dumps(stocks[:20], indent=2)}

Provide tomorrow's watchlist with detailed analysis. Format as JSON array."""
        
        # Query AI agent
        response = self.agent.query(user_prompt, system_prompt)
        
        if not response:
            print("[AI] No response from agent")
            return []
        
        # Try to extract JSON from response
        try:
            # Look for JSON array in response
            start = response.find('[')
            end = response.rfind(']') + 1
            
            if start >= 0 and end > start:
                json_str = response[start:end]
                recommendations = json.loads(json_str)
                return recommendations
            else:
                print("[AI] No JSON array found in response")
                return []

        except json.JSONDecodeError:
            print("[AI] Failed to parse JSON from response")
            return []
    
    def morning_screen(self):
        """4:00 AM EST - Initial screening"""
        print("\n" + "="*70)
        print(f"MORNING SCREEN - {datetime.datetime.now(self.est).strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("="*70)

        # Load manual watchlist first
        manual_stocks = self.load_manual_watchlist()

        # Get stocks from Finviz
        finviz_stocks = self.finviz.get_stocks()

        if not finviz_stocks and not manual_stocks:
            print("[SCREEN] No stocks found from Finviz or manual watchlist")
            return

        # Merge manual and Finviz stocks
        stocks = self.merge_stock_lists(finviz_stocks, manual_stocks)

        # Enrich Finviz stocks with Massive.com data (manual already enriched)
        print(f"[SCREEN] Enriching data for Finviz stocks...")
        for stock in stocks[:30]:  # Limit to avoid rate limits
            if stock.get('source') == 'manual_watchlist':
                continue  # Already enriched
            ticker = stock['ticker']
            data = self.get_stock_data(ticker)
            if data:
                stock.update(data)
            time.sleep(0.5)  # Rate limiting

        # AI analysis
        print("[SCREEN] Running AI analysis...")
        recommendations = self.analyze_stocks_with_ai(stocks, "morning")
        
        # Save results
        result = {
            'timestamp': datetime.datetime.now(self.est).isoformat(),
            'screen_type': 'morning',
            'total_stocks': len(stocks),
            'recommendations': recommendations
        }
        
        self._save_results(result)
        self.current_watchlist = recommendations
        
        print(f"[SCREEN] Morning screen complete: {len(recommendations)} recommendations")
    
    def midday_update(self):
        """9:00 AM - 12:00 PM EST - Updates every hour"""
        print("\n" + "="*70)
        print(f"MIDDAY UPDATE - {datetime.datetime.now(self.est).strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("="*70)
        
        if not self.current_watchlist:
            print("[UPDATE] No watchlist from morning, running fresh screen...")
            self.morning_screen()
            return
        
        # Get fresh data for watchlist
        print(f"[UPDATE] Updating {len(self.current_watchlist)} stocks...")
        
        updated_stocks = []
        for stock in self.current_watchlist:
            ticker = stock.get('ticker') or stock.get('Ticker')
            if ticker:
                data = self.get_stock_data(ticker)
                if data:
                    stock.update(data)
                    updated_stocks.append(stock)
                time.sleep(0.5)
        
        # AI re-analysis
        recommendations = self.analyze_stocks_with_ai(updated_stocks, "midday")
        
        result = {
            'timestamp': datetime.datetime.now(self.est).isoformat(),
            'screen_type': 'midday',
            'recommendations': recommendations
        }
        
        self._save_results(result)
        self.current_watchlist = recommendations
        
        print(f"[UPDATE] Midday update complete: {len(recommendations)} recommendations")
    
    def evening_review(self):
        """7:00 PM EST - Final review with earnings and news"""
        print("\n" + "="*70)
        print(f"EVENING REVIEW - {datetime.datetime.now(self.est).strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("="*70)
        
        # Get fresh Finviz data
        stocks = self.finviz.get_stocks()
        
        # Enrich with latest data
        for stock in stocks[:30]:
            ticker = stock['ticker']
            data = self.get_stock_data(ticker)
            if data:
                stock.update(data)
            time.sleep(0.5)
        
        # AI evening analysis
        recommendations = self.analyze_stocks_with_ai(stocks, "evening")
        
        result = {
            'timestamp': datetime.datetime.now(self.est).isoformat(),
            'screen_type': 'evening',
            'total_stocks': len(stocks),
            'recommendations': recommendations
        }
        
        self._save_results(result)
        
        print(f"[REVIEW] Evening review complete: {len(recommendations)} recommendations")
        print("\nTop Picks for Tomorrow:")
        for i, stock in enumerate(recommendations[:5], 1):
            ticker = stock.get('ticker') or stock.get('Ticker', 'N/A')
            confidence = stock.get('confidence') or stock.get('Confidence', 'N/A')
            print(f"  {i}. {ticker} (Confidence: {confidence})")
    
    def _save_results(self, result: Dict):
        """Save screening results to file"""
        try:
            # Load existing results
            try:
                with open(self.output_file, 'r') as f:
                    results = json.load(f)
            except FileNotFoundError:
                results = []
            
            # Append new result
            results.append(result)
            
            # Keep only last 30 days (use timezone-aware datetime)
            cutoff = datetime.datetime.now(self.est) - datetime.timedelta(days=30)
            results = [r for r in results if
                      datetime.datetime.fromisoformat(r['timestamp']) > cutoff]
            
            # Save
            with open(self.output_file, 'w') as f:
                json.dump(results, f, indent=2)
            
            print(f"[SAVE] Results saved to {self.output_file}")
            
        except Exception as e:
            print(f"[SAVE] Error saving results: {e}")
    
    def get_current_recommendations(self) -> List[Dict]:
        """Get current stock recommendations for trading bot"""
        return self.current_watchlist
    
    def start_scheduler(self):
        """Start scheduled screening"""
        print("\n" + "="*70)
        print("AI STOCK SCREENER - SCHEDULER STARTED")
        print("="*70)
        print(f"Timezone: US/Eastern")
        print(f"Morning Screen: 4:00 AM EST")
        print(f"Midday Updates: 9:00 AM, 10:00 AM, 11:00 AM, 12:00 PM EST")
        print(f"Evening Review: 7:00 PM EST")
        print("="*70)
        
        # Schedule jobs
        schedule.every().day.at("04:00").do(self.morning_screen)
        schedule.every().day.at("09:00").do(self.midday_update)
        schedule.every().day.at("10:00").do(self.midday_update)
        schedule.every().day.at("11:00").do(self.midday_update)
        schedule.every().day.at("12:00").do(self.midday_update)
        schedule.every().day.at("19:00").do(self.evening_review)
        
        # Run forever
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
                
        except KeyboardInterrupt:
            print("\n[SCHEDULER] Stopped by user")


def validate_api_key(key: str, key_name: str, min_length: int = 20,
                     expected_prefix: Optional[str] = None) -> bool:
    """Validate API key format without exposing the key value"""
    if not key:
        return False

    if len(key) < min_length:
        print(f"WARNING: {key_name} appears invalid (too short)")
        return False

    if expected_prefix and not key.startswith(expected_prefix):
        print(f"WARNING: {key_name} appears invalid (unexpected format)")
        return False

    # Check for placeholder values
    placeholder_patterns = ['your_', 'xxx', 'placeholder', 'example', 'test_key']
    key_lower = key.lower()
    for pattern in placeholder_patterns:
        if pattern in key_lower:
            print(f"WARNING: {key_name} appears to be a placeholder value")
            return False

    return True


def main():
    """Main entry point for the AI stock screener"""
    # Get API keys from environment
    massive_api_key = os.getenv('MASSIVE_API_KEY', '')
    claude_api_key = os.getenv('CLAUDE_API_KEY', '')
    openai_api_key = os.getenv('OPENAI_API_KEY', '')
    perplexity_api_key = os.getenv('PERPLEXITY_API_KEY', '')

    # Updated default: relaxed volume + rvol focus
    finviz_url = os.getenv('FINVIZ_SCREENER_URL',
                           'https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o100,sh_price_u20,sh_relvol_o1.5')

    # Load manual watchlist from environment
    manual_watchlist_str = os.getenv('MANUAL_WATCHLIST', '')
    manual_watchlist = [t.strip() for t in manual_watchlist_str.split(',') if t.strip()]

    if manual_watchlist:
        print(f"[CONFIG] Manual watchlist: {', '.join(manual_watchlist)}")

    # Validate Finviz URL
    if finviz_url and not finviz_url.startswith('https://finviz.com/'):
        print("ERROR: FINVIZ_SCREENER_URL must be a valid finviz.com URL")
        sys.exit(1)

    # Build agent list based on validated keys
    agents = []

    # Note: API key formats change over time, so we don't enforce strict prefixes
    # The actual API calls will fail with clear errors if keys are invalid
    if validate_api_key(claude_api_key, 'CLAUDE_API_KEY', min_length=20):
        agents.append(AgentConfig(
            backend=AgentBackend.CLAUDE,
            api_key=claude_api_key,
            model="claude-sonnet-4-20250514",
            priority=1
        ))

    if validate_api_key(openai_api_key, 'OPENAI_API_KEY', min_length=20):
        agents.append(AgentConfig(
            backend=AgentBackend.CHATGPT,
            api_key=openai_api_key,
            model="gpt-4-turbo-preview",
            priority=2
        ))

    if validate_api_key(perplexity_api_key, 'PERPLEXITY_API_KEY', min_length=20):
        agents.append(AgentConfig(
            backend=AgentBackend.PERPLEXITY,
            api_key=perplexity_api_key,
            model="sonar-pro",
            priority=3
        ))

    if not agents:
        print("ERROR: No valid AI agent API keys configured!")
        print("Set at least one of: CLAUDE_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY")
        sys.exit(1)

    if not validate_api_key(massive_api_key, 'MASSIVE_API_KEY', min_length=10):
        print("WARNING: MASSIVE_API_KEY not set or invalid. Real-time data will not be available.")

    # Create agent manager and screener
    agent_manager = AIAgentManager(agents)
    screener = StockScreener(agent_manager, finviz_url, massive_api_key,
                             manual_watchlist=manual_watchlist)

    # Test mode: run once and exit
    if '--test' in sys.argv:
        print("\nTEST MODE - Running morning screen once\n")
        screener.morning_screen()
        sys.exit(0)

    # Normal mode: start scheduler
    screener.start_scheduler()


if __name__ == '__main__':
    main()
