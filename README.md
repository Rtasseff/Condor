# Condor Funds v2

Relaunch of the Condor Funds project (2023–2024): tools that make rigorous,
diversified portfolio building accessible to people who've never invested.

## Layout

| Path | What it is |
|---|---|
| `context/` | Everything from round one — start with [`context/CONTEXT.md`](context/CONTEXT.md) |
| `context/pitch/` | Investor pitch deck; `concept_slides/` are the UI-vision mockups |
| `context/legacy/` | Snapshot of the real code from `condor_test` (reference only) |
| `drive_export/` | Text dump of the condorfunds@gmail.com work drive (`INDEX.md` lists all 43 docs). `files/` holds originals + bulk market data and stays out of git. |
| `condor/` | v2 analytics core: assets, portfolios, frontier optimization |
| `web/` | v2 Django app: the portfolio Explorer UI |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python web/manage.py migrate
python web/manage.py runserver
```

Then open http://127.0.0.1:8000/.
