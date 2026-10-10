"""Read-only audit of SO Master manufacturer price references.

This tool does not write Google Sheets, the price-master registry, quote drafts,
or the input workbooks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.so_price_reference_audit import audit_price_references, write_audit_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit SO Master manufacturer price references.")
    parser.add_argument("--so", required=True, type=Path)
    parser.add_argument("--dt40", required=True, type=Path)
    parser.add_argument("--pt30", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_price_references(
        args.so,
        args.dt40,
        args.pt30,
        source_names={"so": args.so.name, "dt40": args.dt40.name, "pt30": args.pt30.name},
    )
    csv_path, json_path = write_audit_report(report, args.output)
    print(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    print(f"csv: {csv_path}")
    print(f"json: {json_path}")


if __name__ == "__main__":
    main()
