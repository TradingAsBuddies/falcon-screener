# Falcon Screener

Multi-profile stock screening service for the Falcon Trading Platform.

## Installation

### Quick Install

```bash
pip install git+https://github.com/TradingAsBuddies/falcon-screener.git
```

### Standalone Setup

```bash
# Clone the repository
git clone https://github.com/TradingAsBuddies/falcon-screener.git
cd falcon-screener

# Install in editable mode
pip install -e .

# Copy the example environment file and fill in your credentials
cp .env.example .env
```

> **Note:** This package depends on
> [falcon-core](https://github.com/TradingAsBuddies/falcon-core), which is
> installed automatically from GitHub. You need git available on your system
> for this to work.

## Features

- **Multi-Profile Screening**: Run multiple screening strategies simultaneously
- **Earnings Plays**: Track stocks with upcoming earnings, includes date/time
- **Momentum Breakouts**: High-volume breakout candidates
- **Seasonal Rotation**: Sector-based seasonal patterns
- **YAML Export/Import**: Portable profile configurations
- **Feedback Loop**: Auto-adjust weights based on performance

## Usage

### Command Line

```bash
# Run morning screen
falcon-screener --run-type morning

# Run specific profile
falcon-screener --profile "Momentum Breakouts"

# Initialize default profiles
falcon-screener --init

# Generate daily report
falcon-daily-report --live
```

### Python API

```python
from falcon_screener import MultiScreener, ProfileManager
from falcon_core import get_db_manager

db = get_db_manager()
profile_manager = ProfileManager(db)
screener = MultiScreener(profile_manager)

# Run morning screen
results = screener.run_scheduled_profiles('morning')
merged = screener.merge_results(results)
```

## Configuration

Copy `.env.example` to `.env` and set the values for your setup.

### Required

| Variable | Description |
|---|---|
| `MASSIVE_API_KEY` | [Polygon.io](https://polygon.io/) API key for market data |

### AI Screener (at least one key needed)

| Variable | Description |
|---|---|
| `CLAUDE_API_KEY` | Anthropic Claude API key |
| `OPENAI_API_KEY` | OpenAI API key (fallback) |
| `PERPLEXITY_API_KEY` | Perplexity Sonar Pro API key (fallback) |

### Optional

| Variable | Description |
|---|---|
| `FINVIZ_AUTH_KEY` | Finviz Elite authentication key (falls back to free tier) |
| `FINVIZ_SCREENER_URL` | Custom Finviz screener URL with filter parameters |
| `MANUAL_WATCHLIST` | Comma-separated ticker symbols (e.g. `AAPL,TSLA,NVDA`) |
| `DB_TYPE` | Database type (`sqlite` or `postgresql`) |
| `DB_PATH` | Path to SQLite database |

## Profiles

Default profiles in `screener_profiles.yaml`:
- **Momentum Breakouts** - High-volume breakouts (morning + midday)
- **Earnings Plays** - Stocks with earnings this week (morning + evening)
- **Seasonal Sector Rotation** - Sector rotation (morning + evening)

## License

MIT
