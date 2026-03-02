# Falcon Screener - Podman Quadlet Deployment

Systemd-managed container deployment using Podman Quadlet.

## Files

| File | Purpose |
|---|---|
| `falcon-screener.build` | Builds the container image from Dockerfile |
| `falcon-screener.volume` | Persistent volume for results, reports, and database |
| `falcon-screener.network` | Shared container network |
| `falcon-screener-morning.container` | Morning screening (4 AM ET) |
| `falcon-screener-midday.container` | Midday screening (10 AM ET) |
| `falcon-screener-evening.container` | Evening screening (7 PM ET) |
| `falcon-daily-report.container` | Daily report generation (8 PM ET) |
| `*.timer` | Systemd timers for each run (Mon-Fri) |

## Installation (rootless / user service)

```bash
# 1. Copy quadlet files
mkdir -p ~/.config/containers/systemd
cp deploy/quadlet/*.{container,timer,volume,network,build} \
   ~/.config/containers/systemd/

# 2. Create the credentials file
mkdir -p ~/.config/falcon-screener
cp .env.example ~/.config/falcon-screener/env
chmod 600 ~/.config/falcon-screener/env
# Edit ~/.config/falcon-screener/env with your API keys

# 3. Build the image
cd /path/to/falcon-screener
podman build -t localhost/falcon-screener .

# 4. Reload systemd and enable the timers
systemctl --user daemon-reload
systemctl --user enable --now falcon-screener-morning.timer
systemctl --user enable --now falcon-screener-midday.timer
systemctl --user enable --now falcon-screener-evening.timer
systemctl --user enable --now falcon-daily-report.timer
```

## Verify

```bash
# Check timer status
systemctl --user list-timers 'falcon-*'

# Run a manual screening
systemctl --user start falcon-screener-morning.service

# Check logs
journalctl --user -u falcon-screener-morning.service

# Inspect the persistent volume
podman volume inspect systemd-falcon-screener
```

## Using PostgreSQL Instead of SQLite

To use an external PostgreSQL database, update `~/.config/falcon-screener/env`:

```bash
DB_TYPE=postgresql
DB_HOST=your-postgres-host
DB_PORT=5432
DB_NAME=falcon
DB_USER=falcon
DB_PASSWORD=your-password
```

## Uninstall

```bash
systemctl --user disable --now falcon-screener-{morning,midday,evening}.timer
systemctl --user disable --now falcon-daily-report.timer
rm ~/.config/containers/systemd/falcon-*
rm ~/.config/containers/systemd/falcon-daily-report.*
systemctl --user daemon-reload
podman volume rm systemd-falcon-screener
```
