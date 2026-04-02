"""Transcript persistence — JSONL-based message logging.

Provides thread-safe append-only writing and streaming/batch reading
of conversation transcripts.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TranscriptWriter:
    """Append-only JSONL writer for conversation transcripts.

    Thread-safe: multiple threads can call ``append()`` concurrently.
    Supports use as a context manager.

    Parameters
    ----------
    path : str
        Path to the JSONL file. Created if it doesn't exist;
        appended to if it does.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115

    def append(self, message: dict[str, Any]) -> None:
        """Write a message as a single JSON line.

        Parameters
        ----------
        message : dict
            The message dict to persist. Must be JSON-serializable.
        """
        line = json.dumps(message, ensure_ascii=False, default=str)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        """Flush and close the underlying file."""
        with self._lock:
            if not self._file.closed:
                self._file.flush()
                self._file.close()

    def __enter__(self) -> TranscriptWriter:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class TranscriptReader:
    """Reader for JSONL transcript files."""

    @staticmethod
    def load(path: str) -> list[dict[str, Any]]:
        """Read all messages from a JSONL transcript file.

        Parameters
        ----------
        path : str
            Path to the JSONL file.

        Returns
        -------
        list[dict]
            All messages in the file.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        messages: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "TranscriptReader: skipping malformed line %d in %s: %s",
                        line_num,
                        path,
                        exc,
                    )
        return messages

    @staticmethod
    def stream(path: str) -> Iterator[dict[str, Any]]:
        """Stream messages from a JSONL transcript file one at a time.

        Parameters
        ----------
        path : str
            Path to the JSONL file.

        Yields
        ------
        dict
            One message per iteration.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "TranscriptReader: skipping malformed line %d in %s: %s",
                        line_num,
                        path,
                        exc,
                    )
