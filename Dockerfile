# Fedora-native base (mandate: Fedora base OS for every part of the solution)
FROM registry.fedoraproject.org/fedora:42

WORKDIR /app

# git for pip git+ installs; gcc/python3-devel for any sdist builds
RUN dnf -y install python3 python3-pip python3-devel gcc git \
    && dnf clean all && rm -rf /var/cache/dnf

# Upgrade pip for better download handling
RUN pip install --upgrade pip

# falcon-trader #10 (Approach A — thicken the WORKER): this image doubles as the
# intraday scan->persist worker, so it needs THREE things in ONE image that no
# single shipped image had together before:
#   - boto3 + pyarrow (flat-file reads)  -> falcon-core[data-sync] extra (setup.py L28-32)
#   - falcon_trader.intraday_scanner     -> the falcon-trader package
#   - falcon_screener.profile_manager    -> the screener installed from local source below
# The dashboard image (falcon-trader) stays THIN (falcon-core[advisor,postgresql],
# no boto3) — only this worker carries the flat-file + scanner + persist stack.
# NOTE: the #9 freshness-tier code (intraday_scanner.py, falcon-core polygon_client.py)
# is local/unpushed, so intraday-scan.container bind-mounts the local source over
# these git-installed packages at runtime (same idiom as dashboard.container).
RUN pip install --no-cache-dir --timeout 120 \
    "falcon-core[data-sync] @ git+https://github.com/TradingAsBuddies/falcon-core.git" \
    "falcon-trader @ git+https://github.com/TradingAsBuddies/falcon-trader.git" \
    psycopg2-binary

# Copy and install screener
COPY . .
RUN pip install --no-cache-dir --timeout 120 .

ENTRYPOINT ["falcon-screener"]
