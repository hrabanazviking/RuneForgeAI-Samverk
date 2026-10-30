"""Allow `python -m samverk ...` as an alias for the `samverk` command."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
