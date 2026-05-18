from __future__ import annotations

from .migrations.local import applier, loader, transformer
from .migrations.local.applier import *  # noqa: F401,F403
from .migrations.local.applier import main
from .migrations.local.loader import *  # noqa: F401,F403
from .migrations.local.loader import _migration_memory_embedding_settings  # noqa: F401
from .migrations.local.transformer import *  # noqa: F401,F403

_PATCHABLE_APPLIER_NAMES = (
    "open_postgres_store",
    "open_postgres_saver",
    "setup_trajectory_schema",
    "create_memory_repository",
    "create_memory_embedding_service",
)

__all__ = sorted(
    {
        name
        for module in (loader, transformer, applier)
        for name in dir(module)
        if not name.startswith("_")
    }
)
__all__.append("_migration_memory_embedding_settings")


def run_migration(args, *, sink_discovery=None):
    """Compatibility facade for tests and callers patching this legacy module."""

    originals = {name: getattr(applier, name) for name in _PATCHABLE_APPLIER_NAMES}
    try:
        for name in _PATCHABLE_APPLIER_NAMES:
            setattr(applier, name, globals()[name])
        return applier.run_migration(args, sink_discovery=sink_discovery)
    finally:
        for name, value in originals.items():
            setattr(applier, name, value)


if __name__ == "__main__":
    raise SystemExit(main())
