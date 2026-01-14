# Falcon Screener

Multi-profile stock screening service for the Falcon Trading Platform.

## Installation

```bash
pip install git+https://github.com/TradingAsBuddies/falcon-screener.git
```

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

Environment variables:
- `FINVIZ_AUTH_KEY` - Finviz Elite authentication key
- `DB_TYPE` - Database type (`sqlite` or `postgresql`)
- `DB_PATH` - Path to SQLite database

## Profiles

Default profiles in `screener_profiles.yaml`:
- **Momentum Breakouts** - High-volume breakouts (morning + midday)
- **Earnings Plays** - Stocks with earnings this week (morning + evening)
- **Seasonal Sector Rotation** - Sector rotation (morning + evening)

## License

MIT
