"""Policy Engine Integrations — delegate permission decisions to OPA or Cedar.

Enterprise deployments often have a centralized policy engine (Open Policy Agent,
AWS Cedar/Verified Permissions) that encodes organization-wide access rules.
AutoHarness can delegate its permission decisions to these engines, using local
constitution rules as a fallback when the engine is unavailable.

Architecture:
    ToolCall + RiskAssessment + context
        -> PolicyEngineAdapter.evaluate()
            -> OPA REST API  or  Cedar/AVP API
        -> PermissionDecision

Fallback behavior:
    If the policy engine is unreachable (connection error, timeout), the adapter
    falls back to a configurable local decision (default: "deny" for safety).
    This ensures the governance pipeline never hangs or silently allows calls
    when the policy engine is down.

Usage::

    from autoharness.integrations.policy_engines import OPAIntegration, CedarIntegration

    # OPA
    opa = OPAIntegration(url="http://localhost:8181")
    decision = opa.evaluate(tool_call, risk, context)

    # Cedar (AWS Verified Permissions)
    cedar = CedarIntegration(policy_store_id="ps-xxx", region="us-east-1")
    decision = cedar.evaluate(tool_call, risk, context)

    # Pipeline integration
    pipeline = ToolGovernancePipeline(constitution, policy_engine=opa)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Literal

from autoharness.core.types import (
    PermissionDecision,
    RiskAssessment,
    ToolCall,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class PolicyEngineAdapter(ABC):
    """Abstract base for external policy engine integrations.

    All policy engine adapters must implement ``evaluate()`` which maps an
    AutoHarness ``(ToolCall, RiskAssessment, context)`` triple to a
    ``PermissionDecision``.

    Subclasses should handle connection failures gracefully and fall back
    to the ``fallback_action`` specified at construction time.
    """

    def __init__(
        self,
        *,
        fallback_action: Literal["allow", "deny", "ask"] = "deny",
        timeout_seconds: float = 5.0,
    ) -> None:
        self._fallback_action = fallback_action
        self._timeout_seconds = timeout_seconds

    @abstractmethod
    def evaluate(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> PermissionDecision:
        """Evaluate a tool call against the external policy engine.

        Parameters
        ----------
        tool_call : ToolCall
            The tool call being governed.
        risk : RiskAssessment
            The risk classification from the local classifier.
        context : dict
            Session context (session_id, project_dir, agent_role, etc.).

        Returns
        -------
        PermissionDecision
            The authorization decision from the policy engine, or a fallback
            decision if the engine is unreachable.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check whether the policy engine is reachable.

        Returns True if the engine responds, False otherwise.
        """
        ...

    def _make_fallback_decision(self, reason: str) -> PermissionDecision:
        """Create a fallback decision when the policy engine is unavailable."""
        return PermissionDecision(
            action=self._fallback_action,
            reason=f"Policy engine unavailable — fallback to '{self._fallback_action}': {reason}",
            source="policy_engine_fallback",
        )

    def _build_input_payload(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a normalized input dict for the policy engine.

        This shared structure is used by both OPA and Cedar integrations.
        """
        return {
            "tool_name": tool_call.tool_name,
            "tool_input": tool_call.tool_input,
            "risk_level": risk.level.value,
            "risk_reason": risk.reason,
            "risk_confidence": risk.confidence,
            "session_id": context.get("session_id", ""),
            "agent_role": context.get("agent_role", ""),
            "project_dir": context.get("project_dir", ""),
            "timestamp": tool_call.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# OPA Integration
# ---------------------------------------------------------------------------


class OPAIntegration(PolicyEngineAdapter):
    """Delegate permission decisions to Open Policy Agent.

    OPA is queried via its REST Data API (POST ``/v1/data/{policy_path}``).
    The input document contains the tool call, risk assessment, and session
    context. The OPA policy returns a JSON result with ``allow``, ``deny``,
    or ``ask`` plus an optional ``reason``.

    Expected OPA policy output format::

        {
            "result": {
                "decision": "allow" | "deny" | "ask",
                "reason": "Human-readable explanation"
            }
        }

    Parameters
    ----------
    url : str
        Base URL of the OPA server (e.g., ``"http://localhost:8181"``).
    policy_path : str
        OPA data path for the policy (default: ``"autoharness/allow"``).
        The full URL becomes ``{url}/v1/data/{policy_path}``.
    fallback_action : str
        Action when OPA is unreachable. Default ``"deny"`` (fail-closed).
    timeout_seconds : float
        HTTP request timeout. Default 5.0 seconds.
    auth_token : str | None
        Optional bearer token for OPA authentication.
    custom_headers : dict | None
        Additional HTTP headers to include in OPA requests.

    Usage::

        opa = OPAIntegration(url="http://localhost:8181")
        decision = opa.evaluate(tool_call, risk, {"session_id": "abc"})
    """

    def __init__(
        self,
        url: str,
        policy_path: str = "autoharness/allow",
        *,
        fallback_action: Literal["allow", "deny", "ask"] = "deny",
        timeout_seconds: float = 5.0,
        auth_token: str | None = None,
        custom_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            fallback_action=fallback_action,
            timeout_seconds=timeout_seconds,
        )
        # Normalize URL (strip trailing slash)
        self._url = url.rstrip("/")
        self._policy_path = policy_path.strip("/")
        self._auth_token = auth_token
        self._custom_headers = custom_headers or {}

    @property
    def endpoint(self) -> str:
        """Full OPA data API endpoint URL."""
        return f"{self._url}/v1/data/{self._policy_path}"

    def evaluate(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> PermissionDecision:
        """Query OPA for a permission decision.

        Sends a POST request to the OPA Data API with the tool call context
        as input. Parses the response to extract a decision.

        Falls back to the configured fallback action on any connection error,
        timeout, or malformed response.
        """
        try:
            import urllib.error
            import urllib.request

            payload = json.dumps({
                "input": self._build_input_payload(tool_call, risk, context),
            }).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                **self._custom_headers,
            }
            if self._auth_token:
                headers["Authorization"] = f"Bearer {self._auth_token}"

            req = urllib.request.Request(
                self.endpoint,
                data=payload,
                headers=headers,
                method="POST",
            )

            timeout = self._timeout_seconds
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            return self._parse_opa_response(body)

        except ImportError:
            logger.error("urllib not available — cannot query OPA")
            return self._make_fallback_decision("urllib not available")
        except urllib.error.URLError as e:
            logger.warning("OPA connection error: %s", e)
            return self._make_fallback_decision(f"Connection error: {e}")
        except TimeoutError:
            logger.warning("OPA request timed out after %ss", self._timeout_seconds)
            return self._make_fallback_decision("Request timed out")
        except json.JSONDecodeError as e:
            logger.warning("OPA returned invalid JSON: %s", e)
            return self._make_fallback_decision(f"Invalid JSON response: {e}")
        except Exception as e:
            logger.warning("Unexpected error querying OPA: %s", e)
            return self._make_fallback_decision(f"Unexpected error: {e}")

    def _parse_opa_response(self, body: dict[str, Any]) -> PermissionDecision:
        """Parse OPA response into a PermissionDecision.

        Expected structure::

            {"result": {"decision": "allow", "reason": "..."}}

        Also handles boolean result (``{"result": true}`` -> allow).
        """
        result = body.get("result")

        if result is None:
            logger.warning("OPA response missing 'result' field: %s", body)
            return self._make_fallback_decision("OPA response missing 'result' field")

        # Handle boolean result (simple allow/deny policies)
        if isinstance(result, bool):
            action: Literal["allow", "deny"] = "allow" if result else "deny"
            return PermissionDecision(
                action=action,
                reason=f"OPA policy returned {result}",
                source="opa",
            )

        # Handle structured result
        if isinstance(result, dict):
            decision_str = result.get("decision", "").lower()
            reason = result.get("reason", "OPA policy decision")

            if decision_str in ("allow", "deny", "ask"):
                return PermissionDecision(
                    action=decision_str,
                    reason=reason,
                    source="opa",
                )
            else:
                logger.warning("OPA returned unknown decision: %r", decision_str)
                return self._make_fallback_decision(
                    f"Unknown OPA decision: {decision_str!r}"
                )

        # Unrecognized result shape
        logger.warning("OPA response has unexpected result type: %s", type(result))
        return self._make_fallback_decision(
            f"Unexpected result type: {type(result).__name__}"
        )

    def health_check(self) -> bool:
        """Check OPA health via GET /health endpoint."""
        try:
            import urllib.error
            import urllib.request

            url = f"{self._url}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self._timeout_seconds) as resp:
                return bool(resp.status == 200)
        except Exception:
            return False

    def __repr__(self) -> str:
        return (
            f"<OPAIntegration endpoint={self.endpoint!r} "
            f"fallback={self._fallback_action!r}>"
        )


# ---------------------------------------------------------------------------
# Cedar Integration (AWS Verified Permissions)
# ---------------------------------------------------------------------------


class CedarIntegration(PolicyEngineAdapter):
    """Delegate permission decisions to AWS Cedar / Verified Permissions.

    Cedar is Amazon's authorization policy language. This integration uses
    the AWS Verified Permissions (AVP) ``is_authorized`` API to evaluate
    tool calls against Cedar policies stored in a policy store.

    The integration maps AutoHarness concepts to Cedar's entity model:
      - **Principal**: ``AutoHarness::Agent::{agent_role}``
      - **Action**: ``AutoHarness::Action::"{tool_name}"``
      - **Resource**: ``AutoHarness::ToolCall::{session_id}``
      - **Context**: risk_level, tool_input keys, project_dir

    Parameters
    ----------
    policy_store_id : str
        AWS Verified Permissions policy store ID (e.g., ``"ps-abc123"``).
    region : str
        AWS region (default: ``"us-east-1"``).
    fallback_action : str
        Action when Cedar/AVP is unreachable. Default ``"deny"``.
    timeout_seconds : float
        API request timeout. Default 5.0 seconds.
    aws_profile : str | None
        AWS profile name to use. If None, uses default credential chain.

    Usage::

        cedar = CedarIntegration(policy_store_id="ps-xxx", region="us-east-1")
        decision = cedar.evaluate(tool_call, risk, {"agent_role": "coder"})
    """

    def __init__(
        self,
        policy_store_id: str,
        region: str = "us-east-1",
        *,
        fallback_action: Literal["allow", "deny", "ask"] = "deny",
        timeout_seconds: float = 5.0,
        aws_profile: str | None = None,
    ) -> None:
        super().__init__(
            fallback_action=fallback_action,
            timeout_seconds=timeout_seconds,
        )
        self._policy_store_id = policy_store_id
        self._region = region
        self._aws_profile = aws_profile
        self._client = None  # Lazy-initialized boto3 client

    def _get_client(self) -> Any:
        """Lazily initialize the AVP boto3 client."""
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config

            config = Config(
                region_name=self._region,
                connect_timeout=self._timeout_seconds,
                read_timeout=self._timeout_seconds,
                retries={"max_attempts": 1},
            )

            session_kwargs: dict[str, Any] = {}
            if self._aws_profile:
                session_kwargs["profile_name"] = self._aws_profile

            session = boto3.Session(**session_kwargs)
            self._client = session.client("verifiedpermissions", config=config)
            return self._client

        except ImportError:
            raise ImportError(
                "boto3 is required for Cedar integration. "
                "Install it with: pip install autoharness[aws] or pip install boto3"
            ) from None

    def evaluate(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> PermissionDecision:
        """Query AWS Verified Permissions for a Cedar policy decision.

        Maps the tool call to Cedar entity model and calls ``is_authorized``.
        Falls back to local decision on any AWS error.
        """
        try:
            client = self._get_client()

            agent_role = context.get("agent_role", "default")
            session_id = context.get("session_id", "unknown")

            # Build Cedar authorization request
            request = {
                "policyStoreId": self._policy_store_id,
                "principal": {
                    "entityType": "AutoHarness::Agent",
                    "entityId": agent_role,
                },
                "action": {
                    "actionType": "AutoHarness::Action",
                    "actionId": tool_call.tool_name,
                },
                "resource": {
                    "entityType": "AutoHarness::ToolCall",
                    "entityId": session_id,
                },
                "context": {
                    "contextMap": self._build_cedar_context(tool_call, risk, context),
                },
            }

            response = client.is_authorized(**request)
            return self._parse_cedar_response(response)

        except ImportError as e:
            logger.error("Cedar dependency missing: %s", e)
            return self._make_fallback_decision(str(e))
        except Exception as e:
            error_name = type(e).__name__
            logger.warning("Cedar/AVP error (%s): %s", error_name, e)
            return self._make_fallback_decision(f"{error_name}: {e}")

    def _build_cedar_context(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Build the Cedar context map from tool call data.

        Cedar context values must be typed: {"string": "val"}, {"long": 42},
        {"boolean": true}.
        """
        cedar_ctx: dict[str, dict[str, Any]] = {
            "risk_level": {"string": risk.level.value},
            "risk_confidence": {"string": str(risk.confidence)},
            "tool_name": {"string": tool_call.tool_name},
        }

        if risk.reason:
            cedar_ctx["risk_reason"] = {"string": risk.reason}

        if context.get("project_dir"):
            cedar_ctx["project_dir"] = {"string": context["project_dir"]}

        # Add selected tool input keys (strings only, no secrets)
        for key, value in tool_call.tool_input.items():
            if isinstance(value, str) and len(value) < 256:
                cedar_ctx[f"input_{key}"] = {"string": value}
            elif isinstance(value, bool):
                cedar_ctx[f"input_{key}"] = {"boolean": value}
            elif isinstance(value, int):
                cedar_ctx[f"input_{key}"] = {"long": value}

        return cedar_ctx

    def _parse_cedar_response(self, response: dict[str, Any]) -> PermissionDecision:
        """Parse AVP ``is_authorized`` response into a PermissionDecision.

        AVP response shape::

            {
                "decision": "ALLOW" | "DENY",
                "determiningPolicies": [...],
                "errors": [...]
            }
        """
        decision = response.get("decision", "DENY")

        # Collect determining policy IDs for the reason
        policies = response.get("determiningPolicies", [])
        policy_ids = [p.get("policyId", "unknown") for p in policies]

        errors = response.get("errors", [])
        if errors:
            error_msgs = [e.get("errorDescription", str(e)) for e in errors]
            logger.warning("Cedar evaluation errors: %s", error_msgs)

        if decision == "ALLOW":
            reason = "Cedar policy allowed"
            if policy_ids:
                reason += f" (policies: {', '.join(policy_ids)})"
            return PermissionDecision(
                action="allow",
                reason=reason,
                source="cedar",
            )
        else:
            reason = "Cedar policy denied"
            if policy_ids:
                reason += f" (policies: {', '.join(policy_ids)})"
            if errors:
                reason += f" (errors: {len(errors)})"
            return PermissionDecision(
                action="deny",
                reason=reason,
                source="cedar",
            )

    def health_check(self) -> bool:
        """Check Cedar/AVP connectivity by listing policies (limit 1)."""
        try:
            client = self._get_client()
            client.list_policies(
                policyStoreId=self._policy_store_id,
                maxResults=1,
            )
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        return (
            f"<CedarIntegration policy_store={self._policy_store_id!r} "
            f"region={self._region!r} fallback={self._fallback_action!r}>"
        )


# ---------------------------------------------------------------------------
# Composite adapter (chain multiple engines with priority)
# ---------------------------------------------------------------------------


class PolicyEngineChain(PolicyEngineAdapter):
    """Chain multiple policy engines with priority ordering.

    Engines are evaluated in order. The first engine that returns a
    non-fallback decision wins. If all engines fail or return fallback
    decisions, the chain's own fallback action is used.

    This is useful for multi-layer governance: e.g., check Cedar first
    (organization policy), then OPA (team policy), then local rules.

    Parameters
    ----------
    engines : list[PolicyEngineAdapter]
        Ordered list of policy engines to query.
    fallback_action : str
        Action when all engines fail. Default ``"deny"``.

    Usage::

        chain = PolicyEngineChain([
            CedarIntegration(policy_store_id="ps-org"),
            OPAIntegration(url="http://opa.team.internal:8181"),
        ])
        decision = chain.evaluate(tool_call, risk, context)
    """

    def __init__(
        self,
        engines: list[PolicyEngineAdapter],
        *,
        fallback_action: Literal["allow", "deny", "ask"] = "deny",
    ) -> None:
        super().__init__(fallback_action=fallback_action)
        if not engines:
            raise ValueError("PolicyEngineChain requires at least one engine")
        self._engines = list(engines)

    def evaluate(
        self,
        tool_call: ToolCall,
        risk: RiskAssessment,
        context: dict[str, Any],
    ) -> PermissionDecision:
        """Evaluate through the chain of engines.

        Returns the first non-fallback decision. If all engines produce
        fallback decisions, returns this chain's fallback.
        """
        for engine in self._engines:
            try:
                decision = engine.evaluate(tool_call, risk, context)
                # If the source is not a fallback, use it
                if decision.source != "policy_engine_fallback":
                    logger.debug(
                        "PolicyEngineChain: %s decided %s via %s",
                        type(engine).__name__,
                        decision.action,
                        decision.source,
                    )
                    return decision
                else:
                    logger.debug(
                        "PolicyEngineChain: %s fell back, trying next",
                        type(engine).__name__,
                    )
            except Exception as e:
                logger.warning(
                    "PolicyEngineChain: %s raised %s, trying next",
                    type(engine).__name__,
                    e,
                )

        return self._make_fallback_decision(
            "All engines in chain failed or returned fallback"
        )

    def health_check(self) -> bool:
        """Returns True if at least one engine in the chain is healthy."""
        return any(engine.health_check() for engine in self._engines)

    def __repr__(self) -> str:
        engine_names = [type(e).__name__ for e in self._engines]
        return f"<PolicyEngineChain engines={engine_names}>"
