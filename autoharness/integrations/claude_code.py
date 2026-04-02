"""Claude Code Integration — install AutoHarness as Claude Code hooks.

Claude Code supports lifecycle hooks (PreToolUse, PostToolUse) via a
~/.claude/hooks.json configuration file. This module manages installation,
uninstallation, and status checking of AutoHarness hooks within that system.

Usage::

    from autoharness.integrations.claude_code import ClaudeCodeInstaller

    installer = ClaudeCodeInstaller()
    installer.install(constitution_path="./constitution.yaml")
    installer.status()  # -> {"installed": True, "hooks": [...]}
    installer.uninstall()

Or via CLI::

    autoharness install claude-code --constitution constitution.yaml
    autoharness uninstall claude-code
    autoharness status claude-code
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HOOK_TAG = "autoharness"  # Marker to identify our hooks in hooks.json

# Where Claude Code stores its configuration
_CLAUDE_DIR_DEFAULT = Path.home() / ".claude"
_HOOKS_JSON = "hooks.json"

# AutoHarness subdirectory within .claude
_AUTOHARNESS_DIR = "autoharness"
_CONSTITUTION_FILENAME = "constitution.yaml"
_AUDIT_DIR = "audit"

# Hook commands
_PRE_TOOL_USE_CMD = "autoharness check --stdin --format hook"
_POST_TOOL_USE_CMD = "autoharness audit --stdin --format hook"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ClaudeCodeError(Exception):
    """Raised when Claude Code integration encounters a problem."""


class ClaudeCodeNotFoundError(ClaudeCodeError):
    """Raised when Claude Code does not appear to be installed."""


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


class ClaudeCodeInstaller:
    """Install and manage AutoHarness hooks in Claude Code.

    Parameters
    ----------
    claude_dir : Path | None
        Override the Claude Code configuration directory.
        Defaults to ``~/.claude``.
    """

    def __init__(self, claude_dir: Path | None = None) -> None:
        self._claude_dir = claude_dir or _CLAUDE_DIR_DEFAULT
        self._hooks_path = self._claude_dir / _HOOKS_JSON
        self._autoharness_dir = self._claude_dir / _AUTOHARNESS_DIR
        self._constitution_dest = self._autoharness_dir / _CONSTITUTION_FILENAME
        self._audit_dir = self._autoharness_dir / _AUDIT_DIR

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def install(self, constitution_path: str | Path | None = None) -> dict[str, Any]:
        """Install AutoHarness hooks into the Claude Code settings file.

        Steps:
          1. Verify Claude Code configuration directory exists (or create it)
          2. Load existing hooks.json (or start fresh)
          3. Add PreToolUse hook: ``autoharness check --stdin --format hook``
          4. Add PostToolUse hook: ``autoharness audit --stdin --format hook``
          5. Copy constitution to ``~/.claude/autoharness/constitution.yaml``
          6. Create audit directory ``~/.claude/autoharness/audit/``

        Parameters
        ----------
        constitution_path : str | Path | None
            Path to a constitution YAML file to copy into the Claude Code
            config directory. If None, a default constitution is not copied
            (the CLI will use its own default).

        Returns
        -------
        dict
            Summary of what was installed, including paths and hook names.

        Raises
        ------
        ClaudeCodeNotFoundError
            If Claude Code does not appear to be installed and the config
            directory cannot be created.
        ClaudeCodeError
            For permission or I/O errors.
        """
        self._verify_autoharness_cli()

        # Step 1: Ensure directories exist
        try:
            self._claude_dir.mkdir(parents=True, exist_ok=True)
            self._autoharness_dir.mkdir(parents=True, exist_ok=True)
            self._audit_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ClaudeCodeError(
                f"Permission denied creating directories under {self._claude_dir}. "
                f"Check filesystem permissions: {exc}"
            ) from exc
        except OSError as exc:
            raise ClaudeCodeError(
                f"Failed to create directories under {self._claude_dir}: {exc}"
            ) from exc

        # Step 2: Load existing hooks.json
        existing_hooks = self._load_hooks_json()

        # Step 3 & 4: Add/update AutoHarness hooks
        updated_hooks = self._merge_hooks(existing_hooks)

        # Write hooks.json
        self._write_hooks_json(updated_hooks)

        # Step 5: Copy constitution
        constitution_copied = False
        if constitution_path is not None:
            constitution_copied = self._copy_constitution(Path(constitution_path))

        result = {
            "installed": True,
            "hooks_json": str(self._hooks_path),
            "autoharness_dir": str(self._autoharness_dir),
            "audit_dir": str(self._audit_dir),
            "constitution_copied": constitution_copied,
            "constitution_path": str(self._constitution_dest) if constitution_copied else None,
            "hooks_added": ["PreToolUse", "PostToolUse"],
        }

        logger.info(
            "AutoHarness installed in Claude Code: hooks_json=%s, constitution=%s",
            self._hooks_path,
            self._constitution_dest if constitution_copied else "(default)",
        )

        return result

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self) -> dict[str, Any]:
        """Remove AutoHarness hooks from Claude Code.

        Removes AutoHarness entries from hooks.json but preserves other hooks.
        Optionally removes the autoharness config directory.

        Returns
        -------
        dict
            Summary of what was removed.
        """
        removed_hooks: list[str] = []

        # Remove from hooks.json
        if self._hooks_path.exists():
            existing = self._load_hooks_json()
            cleaned, removed = self._remove_autoharness_hooks(existing)

            if removed:
                self._write_hooks_json(cleaned)
                removed_hooks = removed
                logger.info("Removed AutoHarness hooks from %s: %s", self._hooks_path, removed)

                # If hooks.json is now empty, remove it
                if not any(cleaned.values()):
                    try:
                        self._hooks_path.unlink()
                        logger.info("Removed empty hooks.json: %s", self._hooks_path)
                    except OSError:
                        pass  # Not critical
            else:
                logger.info("No AutoHarness hooks found in %s", self._hooks_path)

        # Remove autoharness config directory
        config_removed = False
        if self._autoharness_dir.exists():
            try:
                shutil.rmtree(self._autoharness_dir)
                config_removed = True
                logger.info("Removed AutoHarness config directory: %s", self._autoharness_dir)
            except OSError as exc:
                logger.warning(
                    "Could not remove AutoHarness config directory %s: %s",
                    self._autoharness_dir,
                    exc,
                )

        return {
            "uninstalled": True,
            "hooks_removed": removed_hooks,
            "config_removed": config_removed,
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Check if AutoHarness is installed in Claude Code.

        Returns
        -------
        dict
            Installation status including:
            - installed: bool
            - hooks: list of installed hook event types
            - constitution_present: bool
            - audit_dir_present: bool
            - hooks_json_path: str
        """
        hooks_present: list[str] = []
        hooks_json_exists = self._hooks_path.exists()

        if hooks_json_exists:
            existing = self._load_hooks_json()
            for event_type, hook_list in existing.items():
                if not isinstance(hook_list, list):
                    continue
                for entry in hook_list:
                    if self._is_autoharness_hook(entry):
                        hooks_present.append(event_type)
                        break

        constitution_present = self._constitution_dest.exists()
        audit_dir_present = self._audit_dir.exists()

        installed = len(hooks_present) > 0

        return {
            "installed": installed,
            "hooks": hooks_present,
            "hooks_json_exists": hooks_json_exists,
            "hooks_json_path": str(self._hooks_path),
            "constitution_present": constitution_present,
            "constitution_path": str(self._constitution_dest) if constitution_present else None,
            "audit_dir_present": audit_dir_present,
            "audit_dir_path": str(self._audit_dir) if audit_dir_present else None,
            "autoharness_cli_available": shutil.which("autoharness") is not None,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _verify_autoharness_cli(self) -> None:
        """Warn (but don't fail) if the autoharness CLI is not on PATH."""
        if shutil.which("autoharness") is None:
            logger.warning(
                "The 'autoharness' CLI command was not found on PATH. "
                "Hooks will be installed but will fail at runtime unless "
                "autoharness is installed (pip install autoharness) and available on PATH."
            )

    def _load_hooks_json(self) -> dict[str, Any]:
        """Load hooks.json, returning an empty dict if it doesn't exist or is invalid."""
        if not self._hooks_path.exists():
            return {}

        try:
            text = self._hooks_path.read_text(encoding="utf-8")
        except PermissionError as exc:
            raise ClaudeCodeError(
                f"Permission denied reading {self._hooks_path}: {exc}"
            ) from exc
        except OSError as exc:
            raise ClaudeCodeError(
                f"Cannot read {self._hooks_path}: {exc}"
            ) from exc

        if not text.strip():
            return {}

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeError(
                f"Invalid JSON in {self._hooks_path}: {exc}. "
                f"Please fix the file manually or remove it and reinstall."
            ) from exc

        if not isinstance(data, dict):
            raise ClaudeCodeError(
                f"Expected a JSON object in {self._hooks_path}, "
                f"got {type(data).__name__}."
            )

        return data

    def _write_hooks_json(self, data: dict[str, Any]) -> None:
        """Write hooks.json atomically."""
        try:
            # Write to a temp file first, then rename for atomicity
            tmp_path = self._hooks_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp_path.rename(self._hooks_path)
        except PermissionError as exc:
            raise ClaudeCodeError(
                f"Permission denied writing {self._hooks_path}: {exc}"
            ) from exc
        except OSError as exc:
            raise ClaudeCodeError(
                f"Failed to write {self._hooks_path}: {exc}"
            ) from exc

    def _merge_hooks(self, existing: dict[str, Any]) -> dict[str, Any]:
        """Merge AutoHarness hooks into existing hooks.json data.

        Preserves all non-AutoHarness hooks. Replaces any existing AutoHarness
        hooks with the current versions.
        """
        result = dict(existing)

        # Define our hooks
        pre_hook = {
            "type": "command",
            "command": _PRE_TOOL_USE_CMD,
            "description": (
                "AutoHarness governance check "
                "— evaluates tool calls against constitution rules"
            ),
            "tag": _HOOK_TAG,
        }
        post_hook = {
            "type": "command",
            "command": _POST_TOOL_USE_CMD,
            "description": (
                "AutoHarness audit "
                "— logs tool execution results for governance audit trail"
            ),
            "tag": _HOOK_TAG,
        }

        # Merge PreToolUse
        pre_list = result.get("PreToolUse", [])
        if not isinstance(pre_list, list):
            pre_list = []
        pre_list = [h for h in pre_list if not self._is_autoharness_hook(h)]
        pre_list.append(pre_hook)
        result["PreToolUse"] = pre_list

        # Merge PostToolUse
        post_list = result.get("PostToolUse", [])
        if not isinstance(post_list, list):
            post_list = []
        post_list = [h for h in post_list if not self._is_autoharness_hook(h)]
        post_list.append(post_hook)
        result["PostToolUse"] = post_list

        return result

    def _remove_autoharness_hooks(
        self, existing: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """Remove all AutoHarness hooks from the hooks data.

        Returns the cleaned data and a list of event types that had hooks removed.
        """
        result = dict(existing)
        removed_from: list[str] = []

        for event_type in list(result.keys()):
            hook_list = result[event_type]
            if not isinstance(hook_list, list):
                continue

            original_len = len(hook_list)
            cleaned = [h for h in hook_list if not self._is_autoharness_hook(h)]

            if len(cleaned) < original_len:
                removed_from.append(event_type)
                result[event_type] = cleaned

        return result, removed_from

    @staticmethod
    def _is_autoharness_hook(entry: Any) -> bool:
        """Check if a hook entry belongs to AutoHarness."""
        if not isinstance(entry, dict):
            return False
        # Match by tag
        if entry.get("tag") == _HOOK_TAG:
            return True
        # Fallback: match by command prefix
        cmd = entry.get("command", "")
        return bool(isinstance(cmd, str) and cmd.startswith("autoharness "))

    def _copy_constitution(self, source: Path) -> bool:
        """Copy a constitution file to the autoharness config directory.

        Parameters
        ----------
        source : Path
            Path to the source constitution YAML file.

        Returns
        -------
        bool
            True if the file was copied successfully.

        Raises
        ------
        ClaudeCodeError
            If the source file doesn't exist or can't be copied.
        """
        if not source.exists():
            raise ClaudeCodeError(
                f"Constitution file not found: {source}. "
                f"Provide a valid path or omit to use defaults."
            )

        if not source.is_file():
            raise ClaudeCodeError(
                f"Constitution path is not a file: {source}"
            )

        try:
            shutil.copy2(source, self._constitution_dest)
            logger.info(
                "Copied constitution: %s -> %s", source, self._constitution_dest,
            )
            return True
        except PermissionError as exc:
            raise ClaudeCodeError(
                f"Permission denied copying constitution to {self._constitution_dest}: {exc}"
            ) from exc
        except OSError as exc:
            raise ClaudeCodeError(
                f"Failed to copy constitution to {self._constitution_dest}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        installed = self.status().get("installed", False)
        return (
            f"<ClaudeCodeInstaller claude_dir={self._claude_dir!r} "
            f"installed={installed}>"
        )
