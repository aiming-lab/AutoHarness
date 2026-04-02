"""AutoHarness Hook Marketplace — discover, install, and share community hooks.

The marketplace provides a local registry of pre-built community hooks that
can be installed into any AutoHarness-governed project with a single command.

Usage::

    from autoharness.marketplace import HookMarketplace

    marketplace = HookMarketplace()
    hooks = marketplace.list_available()
    marketplace.install("no-production-access")
"""

from autoharness.marketplace.registry import HookMarketplace

__all__ = ["HookMarketplace"]
