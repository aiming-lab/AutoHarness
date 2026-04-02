"""CrewAI Integration — task guard with AutoHarness governance.

CrewAI uses LangChain under the hood, so this module provides a thin wrapper
around the LangChain ``AutoHarnessCallback`` that adapts it for CrewAI's
task-based workflow.

Usage::

    from autoharness.integrations.crewai import AutoHarnessCrewAIGuard

    guard = AutoHarnessCrewAIGuard("constitution.yaml")

    # Option 1: Pass the callback to Crew
    crew = Crew(
        agents=[...],
        tasks=[...],
        callbacks=[guard.callback],
    )

    # Option 2: Use step_callback for per-step governance
    crew = Crew(
        agents=[...],
        tasks=[...],
        step_callback=guard.step_callback,
    )

    # After execution, inspect results
    print(guard.get_audit_summary())

Requirements:
    pip install langchain-core  (crewai depends on langchain, but we only
    need langchain-core for the callback handler)

If crewai is not installed, this module still works — it only depends on
langchain-core via the AutoHarnessCallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from autoharness.core.constitution import Constitution
from autoharness.core.pipeline import ToolGovernancePipeline
from autoharness.integrations.langchain import (
    AutoHarnessCallback,
    _check_langchain_available,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional CrewAI imports (for type annotations only)
# ---------------------------------------------------------------------------

_CREWAI_AVAILABLE = False
try:
    from crewai import Agent as CrewAgent  # noqa: F401
    from crewai import Task as CrewTask  # noqa: F401

    _CREWAI_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# AutoHarnessCrewAIGuard
# ---------------------------------------------------------------------------


class AutoHarnessCrewAIGuard:
    """CrewAI task guard with AutoHarness governance.

    Wraps the LangChain ``AutoHarnessCallback`` and provides CrewAI-specific
    convenience methods for integrating governance into Crew workflows.

    Parameters
    ----------
    constitution : str | Path | dict | Constitution | None
        Path to a YAML constitution file, a dict, a ``Constitution`` instance,
        or ``None`` to use the default constitution.
    project_dir : str | None
        Project root directory for path-scoping rules. Defaults to cwd.
    session_id : str | None
        Explicit session ID for the audit trail. Auto-generated if omitted.
    raise_on_block : bool
        If ``True`` (default), blocked tool calls raise exceptions that
        CrewAI will surface as task failures. If ``False``, blocks are
        logged but execution continues (advisory mode).
    on_blocked : callable | None
        Optional callback invoked with ``(tool_name, decision)`` when a
        tool call is blocked.

    Usage::

        from autoharness.integrations.crewai import AutoHarnessCrewAIGuard

        guard = AutoHarnessCrewAIGuard("constitution.yaml")

        crew = Crew(
            agents=[researcher, writer],
            tasks=[research_task, write_task],
            callbacks=[guard.callback],
        )

        result = crew.kickoff()
        print(guard.get_audit_summary())
    """

    def __init__(
        self,
        constitution: str | Path | dict[str, Any] | Constitution | None = None,
        *,
        project_dir: str | None = None,
        session_id: str | None = None,
        raise_on_block: bool = True,
        on_blocked: Any = None,
    ) -> None:
        _check_langchain_available()

        self._callback = AutoHarnessCallback(
            constitution=constitution,
            project_dir=project_dir,
            session_id=session_id,
            raise_on_block=raise_on_block,
            on_blocked=on_blocked,
        )

    # ------------------------------------------------------------------
    # Primary interface: the LangChain callback
    # ------------------------------------------------------------------

    @property
    def callback(self) -> AutoHarnessCallback:
        """The underlying LangChain callback handler.

        Pass this to ``Crew(callbacks=[guard.callback])`` or to individual
        ``Agent(callbacks=[guard.callback])``.
        """
        return self._callback

    # ------------------------------------------------------------------
    # CrewAI step_callback interface
    # ------------------------------------------------------------------

    def step_callback(self, step_output: Any) -> None:
        """CrewAI step callback for per-step governance logging.

        Can be passed as ``Crew(step_callback=guard.step_callback)`` to
        receive notifications after each agent step. This is complementary
        to the ``callback`` — the LangChain callback handles pre-execution
        blocking, while this logs step-level metadata.

        Parameters
        ----------
        step_output : Any
            The step output object from CrewAI. Structure varies by CrewAI
            version but typically contains agent output, tool calls, etc.
        """
        # Extract what we can from the step output
        tool_name = None
        tool_input = None

        if hasattr(step_output, "tool"):
            tool_name = step_output.tool
        if hasattr(step_output, "tool_input"):
            tool_input = step_output.tool_input

        if tool_name:
            logger.debug(
                "AutoHarness CrewAI step: tool=%s, input=%s",
                tool_name,
                str(tool_input)[:100] if tool_input else "(none)",
            )

    # ------------------------------------------------------------------
    # Task-level governance
    # ------------------------------------------------------------------

    def guard_task(self, task: Any) -> Any:
        """Attach AutoHarness governance to a specific CrewAI Task.

        Adds the callback to the task's callback list so governance is
        applied to all tool calls made while executing this task.

        Parameters
        ----------
        task : crewai.Task
            The CrewAI task to guard.

        Returns
        -------
        crewai.Task
            The same task, with the AutoHarness callback attached.
        """
        if hasattr(task, "callbacks") and task.callbacks is None:
            task.callbacks = [self._callback]
        elif hasattr(task, "callbacks") and isinstance(task.callbacks, list):
            if self._callback not in task.callbacks:
                task.callbacks.append(self._callback)
        else:
            logger.warning(
                "AutoHarness: task object has no 'callbacks' attribute; "
                "governance may not be applied. Pass the callback to Crew() instead."
            )
        return task

    def guard_agent(self, agent: Any) -> Any:
        """Attach AutoHarness governance to a specific CrewAI Agent.

        Parameters
        ----------
        agent : crewai.Agent
            The CrewAI agent to guard.

        Returns
        -------
        crewai.Agent
            The same agent, with the AutoHarness callback attached.
        """
        if hasattr(agent, "callbacks") and agent.callbacks is None:
            agent.callbacks = [self._callback]
        elif hasattr(agent, "callbacks") and isinstance(agent.callbacks, list):
            if self._callback not in agent.callbacks:
                agent.callbacks.append(self._callback)
        else:
            logger.warning(
                "AutoHarness: agent object has no 'callbacks' attribute; "
                "governance may not be applied. Pass the callback to Crew() instead."
            )
        return agent

    # ------------------------------------------------------------------
    # Query methods (delegated to callback)
    # ------------------------------------------------------------------

    def get_audit_summary(self) -> dict[str, Any]:
        """Return a summary of governance activity for this session.

        Returns
        -------
        dict
            Governance activity summary with keys: session_id, allowed,
            blocked, errors, and pipeline_summary.
        """
        return self._callback.get_audit_summary()

    def get_prompt_addendum(self) -> str:
        """Return the governance prompt addendum for system prompt injection.

        This can be appended to agent backstories or task descriptions to
        inform the LLM about active governance rules.

        Returns
        -------
        str
            Governance rules formatted for prompt injection.
        """
        return self._callback.get_prompt_addendum()

    @property
    def pipeline(self) -> ToolGovernancePipeline:
        """Direct access to the governance pipeline."""
        return self._callback.pipeline

    @property
    def constitution(self) -> Constitution:
        """The resolved constitution."""
        return self._callback.constitution

    def reset_counters(self) -> None:
        """Reset session counters (allowed/blocked/errors) to zero."""
        self._callback.reset_counters()

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        summary = self.get_audit_summary()
        return (
            f"<AutoHarnessCrewAIGuard "
            f"allowed={summary['allowed']} "
            f"blocked={summary['blocked']} "
            f"errors={summary['errors']}>"
        )
