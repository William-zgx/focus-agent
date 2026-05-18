from __future__ import annotations

from .migrations.local import applier, loader, transformer

from .migrations.local.applier import *  # noqa: F401,F403
from .migrations.local.loader import *  # noqa: F401,F403
from .migrations.local.transformer import *  # noqa: F401,F403

from .migrations.local.applier import main

__all__ = sorted(
    {
        name
        for module in (loader, transformer, applier)
        for name in dir(module)
        if not name.startswith("_")
    }
)


if __name__ == "__main__":
    raise SystemExit(main())
