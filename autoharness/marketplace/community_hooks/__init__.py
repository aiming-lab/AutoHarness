"""Community Hooks — pre-built hooks for common governance patterns.

Each hook in this package is a standalone Python file that uses the ``@hook``
decorator from ``autoharness.core.hooks``. Hooks are discovered automatically
by the ``HookMarketplace`` registry.

Available hooks:

- **no-production-access**: Block tool calls targeting production environments
- **cost-tracker**: Track estimated API cost based on token usage
- **working-hours**: Restrict agent actions to configurable working hours
- **git-safety**: Enhanced git safety rules (no force push, branch naming, etc.)
- **code-quality**: Block commits containing debug statements or TODOs

Registration
------------
Hooks register themselves via the ``@hook`` decorator. The marketplace
discovers them by scanning ``.py`` files in this directory (excluding
files starting with ``_``).

Each hook file should define a ``HOOK_METADATA`` dict at module level::

    HOOK_METADATA = {
        "name": "my-hook",
        "description": "What this hook does",
        "event": "pre_tool_use",
        "author": "Your Name",
        "version": "1.0.0",
        "tags": ["safety", "governance"],
    }
"""

from pathlib import Path

COMMUNITY_HOOKS_DIR = Path(__file__).resolve().parent

__all__ = ["COMMUNITY_HOOKS_DIR"]
