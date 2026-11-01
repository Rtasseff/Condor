"""The one ticker-symbol shape, shared by the engine, the ledger format and
the web boundary (condor must not import from web)."""

import re

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")
