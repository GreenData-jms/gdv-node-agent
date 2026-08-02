"""Console entry point: ``gdv-node-agent`` / ``python -m gdv_node_agent``."""

from __future__ import annotations

import sys

from .bind_guard import BindGuardError
from .config import Config
from .server import MissingTokenError, serve


def main() -> int:
    config = Config.from_env()
    try:
        serve(config)
    except BindGuardError as exc:
        print(f"[gdv-node-agent] refusing to start: {exc}", file=sys.stderr)
        return 2
    except MissingTokenError as exc:
        print(f"[gdv-node-agent] refusing to start: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:  # pragma: no cover
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
