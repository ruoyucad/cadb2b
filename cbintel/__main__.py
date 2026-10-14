"""cbintel command line.

  python -m cbintel download [--quick] [--force] [names...]
  python -m cbintel build
  python -m cbintel report [--top 50] [--segment 46 --segment 56]
  python -m cbintel all [--quick]
"""
import argparse

from .build import build
from .download import download
from .report import report
from .sources import SOURCES


def main() -> None:
    p = argparse.ArgumentParser(prog="cbintel")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="download raw CSVs to data/raw")
    d.add_argument("names", nargs="*", help=f"subset of: {', '.join(SOURCES)}")
    d.add_argument("--quick", action="store_true", help="skip the big legacy files")
    d.add_argument("--force", action="store_true", help="re-download even if unchanged")
    sub.add_parser("build", help="load CSVs into DuckDB and run SQL models")
    r = sub.add_parser("report", help="export CSVs / overview to output/")
    r.add_argument("--top", type=int, default=50)
    r.add_argument("--segment", action="append", help="UNSPSC 2-digit segment, e.g. 46")
    a = sub.add_parser("all", help="download + build + report")
    a.add_argument("--quick", action="store_true")
    args = p.parse_args()

    if args.cmd == "download":
        bad = [n for n in args.names if n not in SOURCES]
        if bad:
            p.error(f"unknown source(s): {bad}")
        download(args.names or None, quick=args.quick, force=args.force)
    elif args.cmd == "build":
        build()
    elif args.cmd == "report":
        report(top_n=args.top, segments=args.segment)
    elif args.cmd == "all":
        download(quick=args.quick)
        build()
        report()


if __name__ == "__main__":
    main()
