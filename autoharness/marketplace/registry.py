"""Hook Marketplace Registry — local registry for community-shared hooks.

Manages discovery, installation, packaging, and removal of community hooks.
Hooks are standalone Python files that use the ``@hook`` decorator from
``autoharness.core.hooks`` and can be loaded dynamically into any HookRegistry.

Usage::

    from autoharness.marketplace import HookMarketplace

    marketplace = HookMarketplace()

    # List available community hooks
    hooks = marketplace.list_available()

    # Install a community hook into the current project
    marketplace.install("no-production-access")

    # List installed hooks
    installed = marketplace.list_installed()

    # Remove an installed hook
    marketplace.uninstall("no-production-access")

    # Package a custom hook for sharing
    marketplace.package("my_hook.py", name="my-hook", description="My hook")
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directory containing bundled community hooks
_COMMUNITY_HOOKS_DIR = Path(__file__).resolve().parent / "community_hooks"

# Default installation target within a project
_DEFAULT_HOOKS_DIR = Path(".autoharness") / "hooks"

# Metadata file for tracking installed hooks
_INSTALLED_MANIFEST = "installed_hooks.json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MarketplaceError(Exception):
    """Raised when a marketplace operation fails."""


class HookNotFoundError(MarketplaceError):
    """Raised when a requested hook does not exist in the registry."""


class HookAlreadyInstalledError(MarketplaceError):
    """Raised when attempting to install a hook that is already installed."""


class InvalidHookError(MarketplaceError):
    """Raised when a hook file is invalid or cannot be loaded."""


# ---------------------------------------------------------------------------
# Hook metadata
# ---------------------------------------------------------------------------


class HookMetadata:
    """Metadata for a registered community hook.

    Attributes
    ----------
    name : str
        Unique kebab-case identifier (e.g., ``"no-production-access"``).
    description : str
        Short human-readable description.
    source_path : Path
        Path to the hook's Python source file.
    event : str
        Hook event type (``"pre_tool_use"`` or ``"post_tool_use"``).
    author : str
        Author name or handle.
    version : str
        Semver version string.
    tags : list[str]
        Categorization tags for search and filtering.
    """

    def __init__(
        self,
        name: str,
        description: str,
        source_path: Path,
        event: str = "pre_tool_use",
        author: str = "AutoHarness Community",
        version: str = "1.0.0",
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.source_path = source_path
        self.event = event
        self.author = author
        self.version = version
        self.tags = tags or []

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "source_path": str(self.source_path),
            "event": self.event,
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
        }

    def __repr__(self) -> str:
        return f"<HookMetadata name={self.name!r} event={self.event!r}>"


# ---------------------------------------------------------------------------
# HookMarketplace
# ---------------------------------------------------------------------------


class HookMarketplace:
    """Local registry for community-shared hooks.

    Provides discovery, installation, and packaging of hooks. Community
    hooks are bundled with AutoHarness and can also be loaded from external
    directories.

    Parameters
    ----------
    project_dir : Path | None
        Project root directory. Hooks are installed into
        ``<project_dir>/.autoharness/hooks/``. Defaults to cwd.
    extra_sources : list[Path] | None
        Additional directories to search for community hooks beyond
        the bundled collection.
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        extra_sources: list[Path] | None = None,
    ) -> None:
        self._project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._hooks_dir = self._project_dir / _DEFAULT_HOOKS_DIR
        self._manifest_path = self._hooks_dir / _INSTALLED_MANIFEST

        # Hook source directories: bundled + any extras
        self._sources: list[Path] = [_COMMUNITY_HOOKS_DIR]
        if extra_sources:
            self._sources.extend(extra_sources)

        # Cache of discovered hooks: name -> HookMetadata
        self._registry: dict[str, HookMetadata] | None = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_available(self) -> list[dict[str, Any]]:
        """List all available community hooks.

        Returns
        -------
        list[dict]
            List of hook metadata dictionaries, each containing:
            name, description, event, author, version, tags, installed.
        """
        registry = self._get_registry()
        installed = self._load_manifest()

        results = []
        for name, meta in sorted(registry.items()):
            entry = meta.to_dict()
            entry["installed"] = name in installed
            results.append(entry)

        return results

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search available hooks by name, description, or tags.

        Parameters
        ----------
        query : str
            Search term (case-insensitive substring match).

        Returns
        -------
        list[dict]
            Matching hook metadata dictionaries.
        """
        query_lower = query.lower()
        results = []
        for hook_info in self.list_available():
            searchable = " ".join([
                hook_info["name"],
                hook_info["description"],
                " ".join(hook_info.get("tags", [])),
            ]).lower()
            if query_lower in searchable:
                results.append(hook_info)
        return results

    def get_info(self, name: str) -> dict[str, Any]:
        """Get detailed information about a specific hook.

        Parameters
        ----------
        name : str
            Hook name (kebab-case).

        Returns
        -------
        dict
            Hook metadata dictionary.

        Raises
        ------
        HookNotFoundError
            If the hook is not in the registry.
        """
        registry = self._get_registry()
        if name not in registry:
            raise HookNotFoundError(
                f"Hook {name!r} not found. "
                f"Available hooks: {', '.join(sorted(registry.keys()))}"
            )

        meta = registry[name]
        info = meta.to_dict()
        installed = self._load_manifest()
        info["installed"] = name in installed

        # Include the source code for inspection
        if meta.source_path.exists():
            info["source"] = meta.source_path.read_text(encoding="utf-8")

        return info

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def install(self, name: str, force: bool = False) -> dict[str, Any]:
        """Install a community hook into the current project.

        Copies the hook source file to ``.autoharness/hooks/`` and updates
        the installed manifest.

        Parameters
        ----------
        name : str
            Hook name (kebab-case).
        force : bool
            If True, overwrite an existing installation.

        Returns
        -------
        dict
            Installation result with paths and status.

        Raises
        ------
        HookNotFoundError
            If the hook is not in the registry.
        HookAlreadyInstalledError
            If the hook is already installed and ``force`` is False.
        """
        registry = self._get_registry()
        if name not in registry:
            raise HookNotFoundError(
                f"Hook {name!r} not found. "
                f"Available: {', '.join(sorted(registry.keys()))}"
            )

        installed = self._load_manifest()
        if name in installed and not force:
            raise HookAlreadyInstalledError(
                f"Hook {name!r} is already installed. "
                f"Use force=True to overwrite."
            )

        meta = registry[name]
        if not meta.source_path.exists():
            raise MarketplaceError(
                f"Source file for hook {name!r} not found at {meta.source_path}"
            )

        # Ensure target directory exists
        self._hooks_dir.mkdir(parents=True, exist_ok=True)

        # Copy the hook file
        dest_filename = meta.source_path.name
        dest_path = self._hooks_dir / dest_filename

        try:
            shutil.copy2(meta.source_path, dest_path)
        except (PermissionError, OSError) as exc:
            raise MarketplaceError(
                f"Failed to copy hook to {dest_path}: {exc}"
            ) from exc

        # Update manifest
        installed[name] = {
            "file": dest_filename,
            "version": meta.version,
            "event": meta.event,
            "source": str(meta.source_path),
        }
        self._save_manifest(installed)

        logger.info("Installed hook %r to %s", name, dest_path)

        return {
            "installed": True,
            "name": name,
            "dest_path": str(dest_path),
            "version": meta.version,
            "event": meta.event,
        }

    def uninstall(self, name: str) -> dict[str, Any]:
        """Remove an installed community hook.

        Parameters
        ----------
        name : str
            Hook name (kebab-case).

        Returns
        -------
        dict
            Uninstallation result.
        """
        installed = self._load_manifest()
        if name not in installed:
            return {
                "uninstalled": False,
                "name": name,
                "reason": "Hook is not installed",
            }

        entry = installed[name]
        hook_file = self._hooks_dir / entry["file"]

        # Remove the hook file
        if hook_file.exists():
            try:
                hook_file.unlink()
                logger.info("Removed hook file: %s", hook_file)
            except OSError as exc:
                logger.warning("Could not remove hook file %s: %s", hook_file, exc)

        # Update manifest
        del installed[name]
        self._save_manifest(installed)

        logger.info("Uninstalled hook %r", name)

        return {
            "uninstalled": True,
            "name": name,
            "removed_file": str(hook_file),
        }

    def list_installed(self) -> list[dict[str, Any]]:
        """List all installed hooks in the current project.

        Returns
        -------
        list[dict]
            List of installed hook entries.
        """
        installed = self._load_manifest()
        results = []
        for name, entry in sorted(installed.items()):
            results.append({
                "name": name,
                "file": entry.get("file"),
                "version": entry.get("version"),
                "event": entry.get("event"),
                "path": str(self._hooks_dir / entry["file"]),
            })
        return results

    # ------------------------------------------------------------------
    # Packaging
    # ------------------------------------------------------------------

    def package(
        self,
        source_path: str | Path,
        name: str,
        description: str,
        event: str = "pre_tool_use",
        author: str = "",
        version: str = "1.0.0",
        tags: list[str] | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Package a custom hook for sharing.

        Validates the hook file, extracts metadata, and copies it to
        the output directory with a standardized name.

        Parameters
        ----------
        source_path : str | Path
            Path to the hook Python file.
        name : str
            Hook name (kebab-case).
        description : str
            Short description of what the hook does.
        event : str
            Hook event type.
        author : str
            Author name.
        version : str
            Version string.
        tags : list[str] | None
            Categorization tags.
        output_dir : Path | None
            Where to write the packaged hook. Defaults to cwd.

        Returns
        -------
        dict
            Packaging result with output path.

        Raises
        ------
        InvalidHookError
            If the source file is not a valid hook.
        """
        source = Path(source_path)
        if not source.exists():
            raise InvalidHookError(f"Source file not found: {source}")
        if not source.is_file() or not source.suffix == ".py":
            raise InvalidHookError(f"Source must be a .py file: {source}")

        # Validate that the file can be loaded and contains hook functions
        hook_funcs = self._load_hooks_from_file(source)
        if not hook_funcs:
            raise InvalidHookError(
                f"No @hook-decorated functions found in {source}. "
                f"Hooks must use the @hook decorator from autoharness.core.hooks."
            )

        # Standardize the filename
        safe_name = name.replace("-", "_")
        dest_filename = f"{safe_name}.py"
        target_dir = Path(output_dir) if output_dir else Path.cwd()
        dest_path = target_dir / dest_filename

        try:
            shutil.copy2(source, dest_path)
        except (PermissionError, OSError) as exc:
            raise MarketplaceError(
                f"Failed to copy hook to {dest_path}: {exc}"
            ) from exc

        logger.info(
            "Packaged hook %r: %s -> %s", name, source, dest_path
        )

        return {
            "packaged": True,
            "name": name,
            "description": description,
            "event": event,
            "author": author,
            "version": version,
            "tags": tags or [],
            "output_path": str(dest_path),
            "hook_functions": [f.__name__ for f in hook_funcs],
        }

    # ------------------------------------------------------------------
    # Loading hooks into a HookRegistry
    # ------------------------------------------------------------------

    def load_installed_hooks(self) -> list[Callable[..., Any]]:
        """Load all installed hooks as callable functions.

        Returns a list of hook functions that can be registered with
        a ``HookRegistry`` via ``registry.register_hooks(hooks)``.

        Returns
        -------
        list[Callable]
            Hook functions with ``_hook_event`` and ``_hook_name`` attributes.
        """
        installed = self._load_manifest()
        all_hooks: list[Callable[..., Any]] = []

        for name, entry in installed.items():
            hook_file = self._hooks_dir / entry["file"]
            if not hook_file.exists():
                logger.warning(
                    "Installed hook %r file missing: %s", name, hook_file
                )
                continue

            try:
                funcs = self._load_hooks_from_file(hook_file)
                all_hooks.extend(funcs)
                logger.debug(
                    "Loaded %d hook function(s) from %s", len(funcs), hook_file
                )
            except Exception:
                logger.exception(
                    "Failed to load hook %r from %s", name, hook_file
                )

        return all_hooks

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_registry(self) -> dict[str, HookMetadata]:
        """Build or return the cached registry of available hooks."""
        if self._registry is not None:
            return self._registry

        self._registry = {}

        for source_dir in self._sources:
            if not source_dir.is_dir():
                continue

            for py_file in sorted(source_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue  # Skip __init__.py and private files

                meta = self._extract_metadata(py_file)
                if meta is not None:
                    self._registry[meta.name] = meta

        logger.debug(
            "Hook registry built: %d hooks from %d sources",
            len(self._registry),
            len(self._sources),
        )

        return self._registry

    def _extract_metadata(self, py_file: Path) -> HookMetadata | None:
        """Extract hook metadata from a Python file.

        Reads the module docstring and any ``HOOK_METADATA`` dict defined
        at the module level to build a ``HookMetadata`` instance.

        Parameters
        ----------
        py_file : Path
            Path to the Python hook file.

        Returns
        -------
        HookMetadata | None
            Extracted metadata, or None if the file is not a valid hook.
        """
        try:
            py_file.read_text(encoding="utf-8")
        except OSError:
            return None

        # Try to load the module to get HOOK_METADATA
        try:
            module = self._import_module_from_path(py_file)
        except Exception:
            logger.debug("Could not import %s for metadata extraction", py_file)
            return None

        hook_meta = getattr(module, "HOOK_METADATA", None)
        if not isinstance(hook_meta, dict):
            # Infer metadata from filename
            name = py_file.stem.replace("_", "-")
            description = (module.__doc__ or "").strip().split("\n")[0]
            return HookMetadata(
                name=name,
                description=description or f"Community hook: {name}",
                source_path=py_file,
            )

        return HookMetadata(
            name=hook_meta.get("name", py_file.stem.replace("_", "-")),
            description=hook_meta.get("description", ""),
            source_path=py_file,
            event=hook_meta.get("event", "pre_tool_use"),
            author=hook_meta.get("author", "AutoHarness Community"),
            version=hook_meta.get("version", "1.0.0"),
            tags=hook_meta.get("tags", []),
        )

    @staticmethod
    def _import_module_from_path(py_file: Path) -> ModuleType:
        """Dynamically import a Python module from a file path.

        Parameters
        ----------
        py_file : Path
            Path to the .py file.

        Returns
        -------
        ModuleType
            The imported module.
        """
        module_name = f"autoharness_hook_{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise InvalidHookError(f"Cannot create module spec for {py_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _load_hooks_from_file(py_file: Path) -> list[Callable[..., Any]]:
        """Load all @hook-decorated functions from a Python file.

        Parameters
        ----------
        py_file : Path
            Path to the .py file.

        Returns
        -------
        list[Callable]
            Functions with ``_hook_event`` attribute set by the @hook decorator.
        """
        module_name = f"autoharness_hook_{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise InvalidHookError(f"Cannot create module spec for {py_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        hook_funcs: list[Callable[..., Any]] = []
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if callable(obj) and hasattr(obj, "_hook_event"):
                hook_funcs.append(obj)

        return hook_funcs

    def _load_manifest(self) -> dict[str, Any]:
        """Load the installed hooks manifest.

        Returns
        -------
        dict
            Mapping of hook name to installation entry.
        """
        if not self._manifest_path.exists():
            return {}

        try:
            text = self._manifest_path.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_manifest(self, data: dict[str, Any]) -> None:
        """Save the installed hooks manifest atomically.

        Parameters
        ----------
        data : dict
            Manifest data to write.
        """
        self._hooks_dir.mkdir(parents=True, exist_ok=True)

        try:
            tmp_path = self._manifest_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp_path.rename(self._manifest_path)
        except (PermissionError, OSError) as exc:
            raise MarketplaceError(
                f"Failed to save manifest {self._manifest_path}: {exc}"
            ) from exc

    def __repr__(self) -> str:
        registry = self._get_registry()
        installed = self._load_manifest()
        return (
            f"<HookMarketplace available={len(registry)} "
            f"installed={len(installed)} "
            f"project_dir={self._project_dir!r}>"
        )
