"""Command-line entry point.

    samverk serve [--config PATH] [--host HOST] [--port PORT]

More subcommands arrive with their slices (audit verify in S-007,
operator tools in Part XVIII); the shape is fixed now so scripts and
runbooks can rely on it.
"""

from __future__ import annotations

import argparse

from .config import load_config
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="samverk", description="Samverk — the together-work forge.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the Samverk server")
    p_serve.add_argument("--config", default=None, help="path to samverk.ini")
    p_serve.add_argument("--host", default=None, help="override listen host")
    p_serve.add_argument("--port", type=int, default=None, help="override listen port")

    p_audit = sub.add_parser("audit", help="audit log tools")
    audit_sub = p_audit.add_subparsers(dest="audit_command", required=True)
    p_verify = audit_sub.add_parser("verify", help="verify the audit hash chain")
    p_verify.add_argument("--config", default=None, help="path to samverk.ini")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        cfg = load_config(args.config)
        if args.host is not None:
            cfg.host = args.host
        if args.port is not None:
            cfg.port = args.port
        serve(cfg)
        return 0
    if args.command == "audit" and args.audit_command == "verify":
        from .audit import verify_chain
        from .db import init_db

        cfg = load_config(args.config)
        conn = init_db(cfg.db_path)
        try:
            ok, bad_seq, count = verify_chain(conn)
        finally:
            conn.close()
        if ok:
            print(f"audit chain OK ({count} entries verified)")
            return 0
        print(f"audit chain BROKEN at seq {bad_seq} "
              f"({count} entries verified before the break)")
        return 1
    return 2  # unreachable: subparsers are required


if __name__ == "__main__":
    raise SystemExit(main())
