"""Create a read-only DQ-5B repair plan and an xlsx preview copy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.so_price_reference_repair import SourceSnapshot, create_repair_preview


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a DQ-5B SO reference repair preview.")
    parser.add_argument("--so", required=True, type=Path)
    parser.add_argument("--so-import-id", required=True)
    parser.add_argument("--so-sha256", required=True)
    parser.add_argument("--dt40", required=True, type=Path)
    parser.add_argument("--dt40-import-id", required=True)
    parser.add_argument("--dt40-sha256", required=True)
    parser.add_argument("--pt30", required=True, type=Path)
    parser.add_argument("--pt30-import-id", required=True)
    parser.add_argument("--pt30-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-fields", type=int, default=64)
    parser.add_argument("--expected-rows", type=int, default=32)
    args = parser.parse_args()
    result = create_repair_preview(
        args.so,
        args.dt40,
        args.pt30,
        output_dir=args.output,
        snapshots={
            "SO_MASTER": SourceSnapshot(args.so_import_id, args.so_sha256),
            "DT40": SourceSnapshot(args.dt40_import_id, args.dt40_sha256),
            "PT30": SourceSnapshot(args.pt30_import_id, args.pt30_sha256),
        },
        expected_fields=args.expected_fields,
        expected_rows=args.expected_rows,
    )
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2))
    for label, path in result.output_paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
