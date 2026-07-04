from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import BaseExtension, Extension

if TYPE_CHECKING:
    from os import PathLike

logger = logging.getLogger(__name__)


# Module-level sentinel names we look for when loading an extension.
_ENTRYPOINT_CANDIDATES = ("extension", "init", "register")


class ExtensionLoader:
    """Discover and load :class:`Extension` instances from well-known directories.

    Search order:
      1. ``.focus_agent/extensions/`` in the project root (closest cwd upward)
      2. ``~/.focus_agent/extensions/``
      3. Any directories passed explicitly via *extension_dirs*
    """

    def __init__(self, extension_dirs: list[str] | None = None) -> None:
        self._explicit_dirs = list(extension_dirs or [])

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover(self) -> list[Extension]:
        dirs = self._candidate_dirs()
        extensions: list[Extension] = []
        seen: set[str] = set()

        for directory in dirs:
            dir_path = Path(directory)
            if not dir_path.is_dir():
                logger.debug("Extension directory does not exist: %s", dir_path)
                continue

            for entry in sorted(dir_path.iterdir()):
                if entry.name.startswith(("_", ".")):
                    continue
                ext = self._load_extension_from_path(str(entry))
                if ext is None:
                    continue
                name = getattr(ext, "name", None)
                if name and name in seen:
                    logger.warning(
                        "Skipping duplicate extension %r from %s", name, entry
                    )
                    continue
                if name:
                    seen.add(name)
                extensions.append(ext)

        return extensions

    # ------------------------------------------------------------------
    # Directory resolution
    # ------------------------------------------------------------------
    def _candidate_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        # 1. project-local .focus_agent/extensions
        project_root = self._find_project_root()
        if project_root is not None:
            dirs.append(project_root / ".focus_agent" / "extensions")
        # 2. user-level
        dirs.append(Path.home() / ".focus_agent" / "extensions")
        # 3. explicit
        dirs.extend(Path(p) for p in self._explicit_dirs)
        return dirs

    @staticmethod
    def _find_project_root() -> Path | None:
        """Walk upward from cwd looking for a .focus_agent directory."""
        cur = Path.cwd()
        for candidate in (cur, *cur.parents):
            if (candidate / ".focus_agent").is_dir():
                return candidate
        return None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load_extension_from_path(self, path: str) -> Extension | None:
        p = Path(path)
        try:
            if p.is_file() and p.suffix == ".py":
                module = self._load_module_file(p)
            elif p.is_dir():
                entry_file = self._find_dir_entrypoint(p)
                if entry_file is None:
                    logger.debug("No extension entrypoint found in %s", p)
                    return None
                module = self._load_module_file(entry_file, package_dir=p)
            else:
                return None
        except Exception:
            logger.exception("Failed to import extension from %s", path)
            return None

        if module is None:
            return None

        return self._extract_extension(module, source_path=path)

    # ------------------------------------------------------------------
    # Module loading helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _load_module_file(
        file_path: Path,
        package_dir: Path | None = None,
    ):
        module_name = (
            f"_focus_agent_ext_{file_path.stem}_{abs(hash(str(file_path))) & 0xFFFFFFFF:08x}"
        )
        if package_dir is not None:
            # Package-style loading for directories with __init__.py.
            parent_init = package_dir / "__init__.py"
            target = parent_init if parent_init.is_file() else file_path
            spec = importlib.util.spec_from_file_location(
                module_name,
                str(target),
                submodule_search_locations=[str(package_dir)],
            )
        else:
            spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec is None or spec.loader is None:
            logger.warning("Could not build spec for %s", file_path)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _find_dir_entrypoint(directory: Path) -> Path | None:
        for name in ("extension.py", "__init__.py"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
        return None

    # ------------------------------------------------------------------
    # Extract an Extension instance from a module
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_extension(module: Any, source_path: str) -> Extension | None:
        # 1. Look for a callable entrypoint (`extension()`, `init()`, `register()`).
        for attr in _ENTRYPOINT_CANDIDATES:
            factory = getattr(module, attr, None)
            if callable(factory):
                try:
                    produced = factory()
                except Exception:
                    logger.exception(
                        "Extension entrypoint %r in %s raised", attr, source_path
                    )
                    produced = None
                if produced is not None and ExtensionLoader._is_extension(produced):
                    return produced  # type: ignore[return-value]

        # 2. Look for an Extension subclass defined in the module and instantiate it.
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if not isinstance(obj, type):
                continue
            if obj is BaseExtension:
                continue
            try:
                if issubclass(obj, BaseExtension):
                    instance = obj()
                    if ExtensionLoader._is_extension(instance):
                        return instance  # type: ignore[return-value]
            except TypeError:
                continue

        # 3. Look for a pre-instantiated Extension instance.
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if obj is module or isinstance(obj, type):
                continue
            if ExtensionLoader._is_extension(obj):
                return obj  # type: ignore[return-value]

        logger.warning("No Extension found in %s", source_path)
        return None

    @staticmethod
    def _is_extension(obj: Any) -> bool:
        if isinstance(obj, Extension):  # runtime_checkable Protocol
            return True
        return ExtensionLoader._duck_types_as_extension(type(obj))

    @staticmethod
    def _duck_types_as_extension(cls: type) -> bool:
        required_attrs = ("name", "tools", "agent_definitions")
        return all(hasattr(cls, attr) for attr in required_attrs)


__all__ = ["ExtensionLoader"]
