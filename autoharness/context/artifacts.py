"""Artifact handle system — external storage with lightweight context references.

Implements the artifact handle pattern: large data objects (file contents,
tool outputs, search results) are stored externally, while only compact
handles remain in the conversation context.  This can reduce context usage
by 60-80% for data-heavy workflows.

Usage::

    store = ArtifactStore()
    handle = store.put("large file content here..." * 1000, label="auth.py")
    # handle.reference -> "[Artifact: auth.py (handle=abc123, ~2500 tokens)]"

    # Later, retrieve when needed:
    content = store.get(handle.id)
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoharness.context.tokens import estimate_tokens

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARTIFACT_MIN_TOKENS: int = 500
"""Minimum estimated token count for content to be replaced with a handle."""

ARTIFACT_HANDLE_PREFIX: str = "[Artifact:"
"""Prefix string that marks the start of an artifact handle reference."""

ARTIFACT_HANDLE_PATTERN: re.Pattern[str] = re.compile(
    r"\[Artifact:\s*(?P<label>[^\(]*?)\s*"
    r"\(handle=(?P<id>[a-f0-9]+),\s*~(?P<tokens>\d+)\s*tokens\)\]"
)
"""Regex pattern to locate artifact handle references in text."""

_HASH_LENGTH: int = 12
"""Number of hex characters used for handle IDs."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactHandle:
    """Lightweight reference to an externally-stored artifact.

    Attributes
    ----------
    id : str
        Short hex hash that uniquely identifies this artifact.
    label : str
        Human-readable name (e.g. ``"auth.py"`` or ``"search results"``).
    token_estimate : int
        Estimated token count of the stored content.
    created_at : float
        Unix timestamp of when the artifact was created.
    metadata : dict[str, Any]
        Optional metadata attached to the artifact.
    """

    id: str
    label: str
    token_estimate: int
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def reference(self) -> str:
        """Formatted string suitable for context injection.

        Returns
        -------
        str
            A compact handle string like
            ``"[Artifact: auth.py (handle=abc123, ~2500 tokens)]"``.
        """
        label_part = f" {self.label} " if self.label else " "
        return (
            f"{ARTIFACT_HANDLE_PREFIX}{label_part}"
            f"(handle={self.id}, ~{self.token_estimate} tokens)]"
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class ArtifactStore:
    """Storage backend for artifact content with handle-based retrieval.

    By default content is kept in memory.  When *storage_dir* is provided
    artifacts are also persisted to disk so they survive process restarts.

    Parameters
    ----------
    storage_dir : str | Path | None
        Optional directory for file-backed persistence.  Each artifact is
        stored as ``<handle_id>.json``.  The directory is created if it
        does not exist.
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self._content: dict[str, str] = {}
        self._handles: dict[str, ArtifactHandle] = {}
        self._storage_dir: Path | None = None

        if storage_dir is not None:
            self._storage_dir = Path(storage_dir)
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    # -- public API ---------------------------------------------------------

    def put(
        self,
        content: str,
        label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactHandle:
        """Store *content* and return a lightweight handle.

        Parameters
        ----------
        content : str
            The full text to store externally.
        label : str
            Human-readable name shown in the handle reference.
        metadata : dict[str, Any] | None
            Optional key-value metadata to attach.

        Returns
        -------
        ArtifactHandle
            A frozen handle containing the id, label, and token estimate.
        """
        handle_id = self._make_id(content)
        token_est = estimate_tokens(content)

        handle = ArtifactHandle(
            id=handle_id,
            label=label,
            token_estimate=token_est,
            created_at=time.time(),
            metadata=metadata or {},
        )

        self._content[handle_id] = content
        self._handles[handle_id] = handle

        if self._storage_dir is not None:
            self._persist(handle_id)

        logger.debug(
            "ArtifactStore: stored %r (~%d tokens, id=%s)",
            label,
            token_est,
            handle_id,
        )
        return handle

    def get(self, handle_id: str) -> str | None:
        """Retrieve stored content by handle ID.

        Parameters
        ----------
        handle_id : str
            The artifact identifier returned by :meth:`put`.

        Returns
        -------
        str | None
            The original content, or ``None`` if the ID is unknown.
        """
        return self._content.get(handle_id)

    def delete(self, handle_id: str) -> bool:
        """Remove an artifact from the store.

        Parameters
        ----------
        handle_id : str
            The artifact identifier to delete.

        Returns
        -------
        bool
            ``True`` if the artifact existed and was removed.
        """
        if handle_id not in self._content:
            return False

        del self._content[handle_id]
        del self._handles[handle_id]

        if self._storage_dir is not None:
            disk_path = self._storage_dir / f"{handle_id}.json"
            disk_path.unlink(missing_ok=True)

        logger.debug("ArtifactStore: deleted id=%s", handle_id)
        return True

    def list_handles(self) -> list[ArtifactHandle]:
        """Return all handles in the store, ordered by creation time.

        Returns
        -------
        list[ArtifactHandle]
            Handles sorted oldest-first.
        """
        return sorted(self._handles.values(), key=lambda h: h.created_at)

    @property
    def total_stored_tokens(self) -> int:
        """Sum of estimated tokens across all stored artifacts."""
        return sum(h.token_estimate for h in self._handles.values())

    def clear(self) -> None:
        """Remove all artifacts from the store (including disk)."""
        if self._storage_dir is not None:
            for handle_id in list(self._content):
                disk_path = self._storage_dir / f"{handle_id}.json"
                disk_path.unlink(missing_ok=True)

        self._content.clear()
        self._handles.clear()
        logger.debug("ArtifactStore: cleared all artifacts")

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _make_id(content: str) -> str:
        """Derive a short, deterministic hex ID from content."""
        digest = hashlib.sha256(content.encode()).hexdigest()
        return digest[:_HASH_LENGTH]

    def _persist(self, handle_id: str) -> None:
        """Write a single artifact to disk as JSON."""
        assert self._storage_dir is not None
        handle = self._handles[handle_id]
        payload = {
            "id": handle.id,
            "label": handle.label,
            "token_estimate": handle.token_estimate,
            "created_at": handle.created_at,
            "metadata": handle.metadata,
            "content": self._content[handle_id],
        }
        disk_path = self._storage_dir / f"{handle_id}.json"
        disk_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _load_from_disk(self) -> None:
        """Restore artifacts from *storage_dir* on startup."""
        assert self._storage_dir is not None
        for path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                handle = ArtifactHandle(
                    id=data["id"],
                    label=data["label"],
                    token_estimate=data["token_estimate"],
                    created_at=data["created_at"],
                    metadata=data.get("metadata", {}),
                )
                self._handles[handle.id] = handle
                self._content[handle.id] = data["content"]
            except (json.JSONDecodeError, KeyError):
                logger.warning(
                    "ArtifactStore: skipping corrupt file %s", path.name
                )


# ---------------------------------------------------------------------------
# Message-level helpers
# ---------------------------------------------------------------------------


def replace_large_content(
    messages: list[dict[str, Any]],
    store: ArtifactStore,
    min_tokens: int = ARTIFACT_MIN_TOKENS,
) -> tuple[list[dict[str, Any]], int]:
    """Scan messages and replace large content blocks with artifact handles.

    Content blocks whose estimated token count meets or exceeds *min_tokens*
    are stored in *store* and replaced with the compact handle reference.

    Parameters
    ----------
    messages : list[dict]
        Conversation messages (each with ``role`` and ``content`` keys).
        The list is **not** mutated; a deep copy is returned.
    store : ArtifactStore
        The artifact store to hold extracted content.
    min_tokens : int
        Minimum estimated token count to trigger replacement.

    Returns
    -------
    tuple[list[dict], int]
        A pair of (modified messages, number of artifacts created).
    """
    result = copy.deepcopy(messages)
    created = 0

    for msg in result:
        content = msg.get("content")
        if content is None:
            continue

        if isinstance(content, str):
            tokens = estimate_tokens(content)
            if tokens >= min_tokens:
                label = _derive_label(msg)
                handle = store.put(content, label=label)
                msg["content"] = handle.reference
                created += 1

        elif isinstance(content, list):
            for _i, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                text = block.get("text") or block.get("content", "")
                if not isinstance(text, str) or not text:
                    continue
                tokens = estimate_tokens(text)
                if tokens < min_tokens:
                    continue
                label = _derive_label(msg, block)
                handle = store.put(text, label=label)
                # Replace the text field that held the large content
                if "text" in block:
                    block["text"] = handle.reference
                elif "content" in block and isinstance(block["content"], str):
                    block["content"] = handle.reference
                created += 1

    if created:
        logger.info(
            "replace_large_content: created %d artifact(s), "
            "store now holds ~%d tokens externally",
            created,
            store.total_stored_tokens,
        )
    return result, created


def restore_artifacts(
    messages: list[dict[str, Any]],
    store: ArtifactStore,
) -> list[dict[str, Any]]:
    """Replace artifact handle references with their original content.

    Parameters
    ----------
    messages : list[dict]
        Conversation messages that may contain handle references.
        The list is **not** mutated; a deep copy is returned.
    store : ArtifactStore
        The artifact store containing the original content.

    Returns
    -------
    list[dict]
        Messages with handle references expanded back to full content.
    """
    result = copy.deepcopy(messages)

    for msg in result:
        content = msg.get("content")
        if content is None:
            continue

        if isinstance(content, str):
            msg["content"] = _expand_handles(content, store)

        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                for key in ("text", "content"):
                    val = block.get(key)
                    if isinstance(val, str) and ARTIFACT_HANDLE_PREFIX in val:
                        block[key] = _expand_handles(val, store)

    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _expand_handles(text: str, store: ArtifactStore) -> str:
    """Replace all handle references in *text* with stored content."""

    def _replacer(match: re.Match[str]) -> str:
        handle_id = match.group("id")
        original = store.get(handle_id)
        if original is not None:
            return original
        # Handle not found — leave the reference intact
        logger.warning(
            "restore_artifacts: handle %s not found in store", handle_id
        )
        return match.group(0)

    return ARTIFACT_HANDLE_PATTERN.sub(_replacer, text)


def _derive_label(msg: dict[str, Any], block: dict[str, Any] | None = None) -> str:
    """Best-effort label derivation from a message or content block.

    Tries ``tool_use_id``, ``name``, or role as a fallback.
    """
    if block is not None:
        for key in ("name", "tool_use_id", "type"):
            val = block.get(key)
            if val:
                return str(val)
    return str(msg.get("role", "content"))
