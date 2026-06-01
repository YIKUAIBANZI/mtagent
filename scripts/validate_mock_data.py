"""CLI: validate every mock POI parses through Pydantic. Run from project root."""

import json
import sys
from pathlib import Path

from dianping.schemas import POI


def main() -> int:
    base = Path("data/mock_dianping")
    total = 0
    failed = 0
    for city_file in ["深圳.json", "上海.json", "西安.json"]:
        path = base / city_file
        if not path.exists():
            print(f"SKIP {path} (not found)")
            continue
        with path.open(encoding="utf-8") as f:
            pois = json.load(f)
        city_failed = 0
        for i, p in enumerate(pois):
            total += 1
            try:
                POI.model_validate(p)
            except Exception as exc:
                city_failed += 1
                if city_failed <= 3:
                    print(f"FAIL {city_file}[{i}]: {str(exc)[:200]}")
        failed += city_failed
        print(f"{city_file}: {len(pois) - city_failed}/{len(pois)} OK")
    print(f"\nTOTAL: {total - failed}/{total} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
