#!/usr/bin/env python3
"""
Harvest DWS monthly flood-peak CSVs for a curated station list.

Fetches the STATIC peak files from
  https://www.dws.gov.za/Hydrology/Flood%20Peaks/Monthly/<CODE>PK.CSV
which (unlike the HyDataSets.aspx portal) are served as plain files.

Writes the raw CSV verbatim to  data/peaks/<CODE>PK.CSV  so the dashboard
can read it client-side with the exact same parser it uses for uploads.
Also writes data/peaks/index.json listing which stations succeeded, so the
map can show which stations have harvested data.

Run locally, on an ARC cron job, or in a GitHub Action. If DWS blocks the
runner's IP, run it somewhere that can reach the site and commit the output.
"""
import json, sys, time
from pathlib import Path
from datetime import datetime, timezone
import requests

BASE = "https://www.dws.gov.za/Hydrology/Flood%20Peaks/Monthly/{code}PK.CSV"
OUT = Path("data/peaks")
STATION_LIST = Path("stations_to_harvest.txt")  # one code per line, # for comments
TIMEOUT = 120
PAUSE = 2.0          # seconds between requests — be polite to DWS
RETRIES = 2

HEADERS = {
    # Mimic a normal browser; the static dir is not behind the portal bot-gate,
    # but a plain UA is still courteous and less likely to be filtered.
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "text/csv,text/plain,*/*",
}

def load_stations():
    if not STATION_LIST.exists():
        print(f"! {STATION_LIST} not found — create it, one station code per line.")
        sys.exit(1)
    codes = []
    for line in STATION_LIST.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            codes.append(line.upper())
    return codes

def looks_valid(text):
    # The real file contains the SAFMAXLEVELFLOW header and a Year,Date,Time line.
    return ("Year,Date,Time" in text) and ("SAFMAXLEVELFLOW" in text or "Monthly Maximum" in text)

def fetch(code):
    url = BASE.format(code=code)
    for attempt in range(1, RETRIES + 2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and looks_valid(r.text):
                return r.text
            if r.status_code == 404:
                return None  # no peaks file for this station
            print(f"  attempt {attempt}: HTTP {r.status_code}"
                  f"{' (unexpected body)' if r.status_code==200 else ''}")
        except requests.RequestException as e:
            print(f"  attempt {attempt}: {type(e).__name__}: {e}")
        time.sleep(PAUSE * attempt)
    return False  # failed after retries (distinct from 404 -> None)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    codes = load_stations()
    print(f"Harvesting {len(codes)} stations -> {OUT}/")
    ok, missing, failed = [], [], []
    for code in codes:
        print(f"- {code}")
        text = fetch(code)
        if text is None:
            print("    no peaks file (404)"); missing.append(code)
        elif text is False:
            print("    FAILED"); failed.append(code)
        else:
            (OUT / f"{code}PK.CSV").write_text(text, encoding="utf-8")
            print(f"    saved {len(text):,} bytes"); ok.append(code)
        time.sleep(PAUSE)

    index = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "available": sorted(ok),
        "missing": sorted(missing),
        "failed": sorted(failed),
    }
    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    print(f"\nDone. ok={len(ok)} missing={len(missing)} failed={len(failed)}")
    if failed:
        print("Failed (will retry next run):", ", ".join(failed))
        # non-zero exit if everything failed — likely an IP block worth noticing
        if not ok:
            sys.exit(2)

if __name__ == "__main__":
    main()
