"""Export the synthetic research walkthrough for the public interview site."""

import argparse
import json
from pathlib import Path

from ceremyn.research.demo import export_demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("interview-site/dist/demo.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(export_demo(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
