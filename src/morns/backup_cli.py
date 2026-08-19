from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .backup import BackupError, BackupService
from .config import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="morns-backup",
        description="Create, inspect, or restore a local MORNS station backup.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Station database path (defaults to MORNS_DATABASE).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Create a portable secret-free backup.")
    create.add_argument("archive", type=Path)

    inspect = commands.add_parser("inspect", help="Validate and print backup metadata.")
    inspect.add_argument("archive", type=Path)

    restore = commands.add_parser(
        "restore", help="Restore while the MORNS service is stopped."
    )
    restore.add_argument("archive", type=Path)
    restore.add_argument(
        "--confirm-offline",
        action="store_true",
        help="Confirm that MORNS and its collector are stopped.",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    database = args.database or Settings.from_env().database_path
    service = BackupService(database, __version__)
    try:
        if args.command == "create":
            result = service.create_archive(args.archive)
        elif args.command == "inspect":
            result = service.inspect_archive(args.archive)
        else:
            if not args.confirm_offline:
                raise BackupError(
                    "Restore is offline-only: stop MORNS and its collector, then pass --confirm-offline"
                )
            result = service.restore_archive(args.archive)
    except (BackupError, OSError) as exc:
        print(f"morns-backup: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
