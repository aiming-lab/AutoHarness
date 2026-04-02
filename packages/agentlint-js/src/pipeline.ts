/**
 * Tool Governance Pipeline — the 8-step process every tool call passes through.
 *
 * This is the central orchestration layer. It wires together:
 *   RiskClassifier -> HookRegistry -> PermissionEngine -> AuditEngine
 *
 * Steps:
 *   1. Parse — validate structure
 *   2. Validate — check required fields
 *   3. Classify Risk — regex-based risk assessment
 *   4. PreToolUse Hooks — secret scanner, path guard, etc.
 *   5. Permission Decision — merge risk + hooks + rules
 *   6. Execute — call the actual tool (via callback)
 *   7. PostToolUse Hooks — output sanitization
 *   8. Audit — log everything
 */

import { randomUUID } from "node:crypto";
import { AuditEngine } from "./audit.js";
import { Constitution } from "./constitution.js";
import { HookRegistry } from "./hooks.js";
import { PermissionEngine } from "./permissions.js";
import { RiskClassifier } from "./risk.js";
import type {
  HookResult,
  PermissionDecision,
  PermissionDefaults,
  RiskAssessment,
  ToolCall,
  ToolResult,
} from "./types.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ToolExecutor = (toolCall: ToolCall) => unknown;
export type BlockCallback = (toolCall: ToolCall, decision: PermissionDecision) => void;

// ---------------------------------------------------------------------------
// ToolGovernancePipeline
// ---------------------------------------------------------------------------

export class ToolGovernancePipeline {
  private readonly _sessionId: string;
  private readonly _projectDir: string;
  private _toolExecutor: ToolExecutor | null = null;
  private _onBlocked: BlockCallback | null = null;

  private readonly _riskClassifier: RiskClassifier;
  private readonly _permissionEngine: PermissionEngine;
  private readonly _hookRegistry: HookRegistry;
  private readonly _auditEngine: AuditEngine;
  private readonly _riskThresholds: Record<string, string>;
  private _constitution: unknown;

  constructor(
    constitution?: Constitution | Record<string, unknown> | null,
    options?: {
      projectDir?: string;
      sessionId?: string;
    },
  ) {
    this._sessionId = options?.sessionId ?? randomUUID().slice(0, 12);
    this._projectDir = options?.projectDir ?? process.cwd();

    // Extract configuration from constitution
    const config = this._extractConfig(constitution);

    // Initialize sub-engines
    this._riskClassifier = new RiskClassifier(
      this._getCustomRules(config),
      this._getRiskMode(config),
    );

    const toolsPermissions = this._getToolPermissions(config);
    const defaults = this._getPermissionDefaults(config);
    this._permissionEngine = new PermissionEngine(
      defaults,
      toolsPermissions as Record<string, Record<string, unknown>> | null,
    );

    const hookProfile = this._getHookProfile(config);
    this._hookRegistry = new HookRegistry(hookProfile, this._projectDir);

    this._riskThresholds = this._getRiskThresholds(config);

    const auditConfig = this._getAuditConfig(config);
    this._auditEngine = new AuditEngine(
      (auditConfig["output"] as string) ?? ".autoharness/audit.jsonl",
      (auditConfig["enabled"] as boolean) ?? true,
      (auditConfig["retentionDays"] as number) ?? 30,
    );
  }

  // ------------------------------------------------------------------
  // Main entry points
  // ------------------------------------------------------------------

  /** Run the full 8-step governance pipeline. */
  process(toolCall: ToolCall): ToolResult {
    const startTime = performance.now();
    const context = {
      session_id: this._sessionId,
      project_dir: this._projectDir,
    };

    try {
      // Step 1-2: Parse and validate
      this._validateToolCall(toolCall);

      // Step 3: Classify Risk
      const risk = this._riskClassifier.classify(toolCall);

      // Step 4: PreToolUse Hooks
      const preHookResults = this._hookRegistry.runPreHooks(toolCall, risk, context);

      // Step 5: Check for hook denials (short-circuit)
      const hookDenial = this._findHookDenial(preHookResults);
      if (hookDenial) {
        const decision: PermissionDecision = {
          action: "deny",
          reason: hookDenial.reason ?? "Blocked by pre-hook",
          source: "hook",
          riskLevel: risk.level,
        };
        return this._handleBlock(toolCall, risk, preHookResults, decision, startTime);
      }

      // Step 6: Permission Decision
      const decision = this._makePermissionDecision(toolCall, risk, preHookResults);

      if (decision.action === "deny") {
        return this._handleBlock(toolCall, risk, preHookResults, decision, startTime);
      }

      if (decision.action === "ask") {
        const denyDecision: PermissionDecision = {
          action: "deny",
          reason: `Requires confirmation: ${decision.reason}`,
          source: decision.source,
          riskLevel: decision.riskLevel,
        };
        return this._handleBlock(toolCall, risk, preHookResults, denyDecision, startTime);
      }

      // Step 7: Execute
      const execResult = this._execute(toolCall, startTime);

      // Step 8: PostToolUse Hooks
      const [finalResult, postHookResults] = this._hookRegistry.runPostHooks(
        toolCall,
        execResult,
        context,
      );

      // Step 9: Audit
      this._auditEngine.log({
        toolCall,
        risk,
        preHooks: preHookResults,
        permission: decision,
        result: finalResult,
        postHooks: postHookResults,
        sessionId: this._sessionId,
      });

      return finalResult;
    } catch (e) {
      const duration = performance.now() - startTime;
      const errorResult: ToolResult = {
        toolName: toolCall.toolName,
        status: "error",
        error: String(e),
        durationMs: duration,
        sanitized: false,
      };
      try {
        this._auditEngine.logError(toolCall, e as Error, this._sessionId);
      } catch {
        // Swallow audit errors
      }
      return errorResult;
    }
  }

  /** Pre-execution governance check only (no execution, no post-hooks). */
  evaluate(
    toolCall: ToolCall,
    context?: Record<string, unknown>,
  ): PermissionDecision {
    const ctx = context ?? {
      session_id: this._sessionId,
      project_dir: this._projectDir,
    };

    const risk = this._riskClassifier.classify(toolCall);
    const preHookResults = this._hookRegistry.runPreHooks(toolCall, risk, ctx);

    const hookDenial = this._findHookDenial(preHookResults);
    if (hookDenial) {
      return {
        action: "deny",
        reason: hookDenial.reason ?? "Blocked by pre-hook",
        source: "hook",
        riskLevel: risk.level,
      };
    }

    return this._makePermissionDecision(toolCall, risk, preHookResults);
  }

  /** Process multiple tool calls sequentially. */
  processBatch(toolCalls: ToolCall[]): ToolResult[] {
    return toolCalls.map((tc) => this.process(tc));
  }

  // ------------------------------------------------------------------
  // Configuration
  // ------------------------------------------------------------------

  /** Set the callback that actually executes tools. */
  setToolExecutor(executor: ToolExecutor): void {
    this._toolExecutor = executor;
  }

  get onBlocked(): BlockCallback | null {
    return this._onBlocked;
  }

  set onBlocked(callback: BlockCallback) {
    this._onBlocked = callback;
  }

  /** Get summary of audit records. */
  getAuditSummary(): Record<string, unknown> {
    return this._auditEngine.getSummary(this._sessionId);
  }

  /** Close the pipeline (flush audit). */
  close(): void {
    this._auditEngine.close();
  }

  // ------------------------------------------------------------------
  // Sub-engine accessors
  // ------------------------------------------------------------------

  get riskClassifier(): RiskClassifier {
    return this._riskClassifier;
  }

  get permissionEngine(): PermissionEngine {
    return this._permissionEngine;
  }

  get hookRegistry(): HookRegistry {
    return this._hookRegistry;
  }

  get auditEngine(): AuditEngine {
    return this._auditEngine;
  }

  // ------------------------------------------------------------------
  // Internal helpers
  // ------------------------------------------------------------------

  private _validateToolCall(toolCall: ToolCall): void {
    if (!toolCall.toolName) {
      throw new Error("toolName is required");
    }
    if (typeof toolCall.toolInput !== "object" || toolCall.toolInput === null) {
      throw new Error("toolInput must be an object");
    }
  }

  private _findHookDenial(hookResults: HookResult[]): HookResult | null {
    for (const hr of hookResults) {
      if (hr.action === "deny") return hr;
    }
    return null;
  }

  private _makePermissionDecision(
    toolCall: ToolCall,
    risk: RiskAssessment,
    hookResults: HookResult[],
  ): PermissionDecision {
    // Check risk thresholds
    const thresholdAction = this._riskThresholds[risk.level] ?? "allow";
    if (thresholdAction === "deny") {
      return {
        action: "deny",
        reason: `Risk level '${risk.level}' exceeds threshold` +
          (risk.reason ? `: ${risk.reason}` : ""),
        source: "risk_threshold",
        riskLevel: risk.level,
      };
    }
    if (thresholdAction === "ask") {
      return {
        action: "ask",
        reason: `Risk level '${risk.level}' requires confirmation` +
          (risk.reason ? `: ${risk.reason}` : ""),
        source: "risk_threshold",
        riskLevel: risk.level,
      };
    }

    // Check hook asks
    for (const hr of hookResults) {
      if (hr.action === "ask") {
        return {
          action: "ask",
          reason: hr.reason ?? "Hook requires confirmation",
          source: "hook",
          riskLevel: risk.level,
        };
      }
    }

    // Try permission engine
    try {
      return this._permissionEngine.decide(toolCall, risk, hookResults);
    } catch {
      // Fall through to default
    }

    // Default: allow
    return {
      action: "allow",
      reason: "All governance checks passed",
      source: "pipeline",
      riskLevel: risk.level,
    };
  }

  private _execute(toolCall: ToolCall, startTime: number): ToolResult {
    if (!this._toolExecutor) {
      const duration = performance.now() - startTime;
      return {
        toolName: toolCall.toolName,
        status: "success",
        output: "[AutoHarness: tool execution passed governance — no executor set]",
        durationMs: duration,
        sanitized: false,
      };
    }

    try {
      const output = this._toolExecutor(toolCall);
      const duration = performance.now() - startTime;
      return {
        toolName: toolCall.toolName,
        status: "success",
        output,
        durationMs: duration,
        sanitized: false,
      };
    } catch (e) {
      const duration = performance.now() - startTime;
      return {
        toolName: toolCall.toolName,
        status: "error",
        error: String(e),
        durationMs: duration,
        sanitized: false,
      };
    }
  }

  private _handleBlock(
    toolCall: ToolCall,
    risk: RiskAssessment,
    hookResults: HookResult[],
    decision: PermissionDecision,
    startTime: number,
  ): ToolResult {
    const duration = performance.now() - startTime;

    // Run block hooks
    this._hookRegistry.runBlockHooks(toolCall, decision, {
      session_id: this._sessionId,
    });

    // Notify callback
    if (this._onBlocked) {
      try {
        this._onBlocked(toolCall, decision);
      } catch {
        // Swallow
      }
    }

    // Audit
    this._auditEngine.logBlock({
      toolCall,
      risk,
      preHooks: hookResults,
      permission: decision,
      sessionId: this._sessionId,
    });

    return {
      toolName: toolCall.toolName,
      status: "blocked",
      blockedReason: decision.reason,
      durationMs: duration,
      sanitized: false,
    };
  }

  // ------------------------------------------------------------------
  // Config extraction helpers
  // ------------------------------------------------------------------

  private _extractConfig(
    constitution: unknown,
  ): Record<string, unknown> {
    this._constitution = constitution;

    if (!constitution) return {};

    // If it's a Constitution object, get the config
    if (constitution instanceof Constitution) {
      return constitution.config as unknown as Record<string, unknown>;
    }

    // If it has a config property
    if (typeof constitution === "object" && constitution !== null) {
      const obj = constitution as Record<string, unknown>;
      if ("config" in obj && typeof obj["config"] === "object") {
        return obj["config"] as Record<string, unknown>;
      }
      return obj;
    }

    return {};
  }

  private _getCustomRules(
    config: Record<string, unknown>,
  ): Array<{ pattern: string; level: string; reason?: string; tool?: string }> | null {
    const risk = config["risk"];
    if (risk && typeof risk === "object") {
      const r = risk as Record<string, unknown>;
      const rules = r["customRules"] ?? r["custom_rules"];
      if (Array.isArray(rules)) return rules as Array<{ pattern: string; level: string }>;
    }
    return null;
  }

  private _getRiskMode(config: Record<string, unknown>): string {
    const risk = config["risk"];
    if (risk && typeof risk === "object") {
      return ((risk as Record<string, unknown>)["classifier"] as string) ?? "rules";
    }
    return "rules";
  }

  private _getToolPermissions(
    config: Record<string, unknown>,
  ): Record<string, unknown> | null {
    const perms = config["permissions"];
    if (perms && typeof perms === "object") {
      return ((perms as Record<string, unknown>)["tools"] as Record<string, unknown>) ?? null;
    }
    return null;
  }

  private _getPermissionDefaults(
    config: Record<string, unknown>,
  ): PermissionDefaults | null {
    const perms = config["permissions"];
    if (perms && typeof perms === "object") {
      const defaults = (perms as Record<string, unknown>)["defaults"];
      if (defaults && typeof defaults === "object") {
        return defaults as PermissionDefaults;
      }
    }
    return null;
  }

  private _getHookProfile(config: Record<string, unknown>): string {
    const hooks = config["hooks"];
    if (hooks && typeof hooks === "object") {
      return ((hooks as Record<string, unknown>)["profile"] as string) ?? "standard";
    }
    return "standard";
  }

  private _getRiskThresholds(config: Record<string, unknown>): Record<string, string> {
    const risk = config["risk"];
    if (risk && typeof risk === "object") {
      const thresholds = (risk as Record<string, unknown>)["thresholds"];
      if (thresholds && typeof thresholds === "object") {
        return thresholds as Record<string, string>;
      }
    }
    return { low: "allow", medium: "allow", high: "ask", critical: "deny" };
  }

  private _getAuditConfig(config: Record<string, unknown>): Record<string, unknown> {
    const audit = config["audit"];
    if (audit && typeof audit === "object") {
      return audit as Record<string, unknown>;
    }
    return { enabled: true, output: ".autoharness/audit.jsonl", retentionDays: 30 };
  }
}
