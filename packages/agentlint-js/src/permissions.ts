/**
 * Permission Engine for AutoHarness.
 *
 * A 3-level permission model (tool -> path -> operation) inspired by
 * multi-layer permission systems. Evaluates tool calls against
 * constitution rules and returns ALLOW / DENY / ASK decisions.
 *
 * Decision priority (highest wins):
 *   1. Explicit deny (constitution deny_paths/deny_patterns) -> ABSOLUTE DENY
 *   2. Hook deny -> ABSOLUTE DENY
 *   3. ask_patterns match -> ASK
 *   4. Risk >= threshold -> action based on threshold config
 *   5. Hook allow (CANNOT override denies above!) -> ALLOW
 *   6. Explicit allow_patterns/allow_paths -> ALLOW
 *   7. Tool default policy -> per-policy behavior
 *   8. Global default (unknown_tool) -> usually ASK
 */

import * as path from "node:path";
import type {
  HookResult,
  PermissionDecision,
  PermissionDefaults,
  RiskAssessment,
  ToolCall,
  ToolPermission,
} from "./types.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PATH_KEYS = ["file_path", "path", "filename", "file"] as const;
const BASH_TOOLS = new Set(["bash", "shell", "terminal", "execute", "run"]);

// ---------------------------------------------------------------------------
// Minimatch-like glob matching (simplified fnmatch)
// ---------------------------------------------------------------------------

function globMatch(filepath: string, pattern: string): boolean {
  // Convert glob pattern to regex
  const regexStr = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".");
  try {
    return new RegExp(`^${regexStr}$`).test(filepath);
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// PermissionEngine
// ---------------------------------------------------------------------------

export class PermissionEngine {
  private readonly _defaults: PermissionDefaults;
  private readonly _tools: Map<string, ToolPermission>;
  private readonly _projectDir: string;
  private readonly _compiled: Map<
    string,
    { deny: RegExp[]; ask: RegExp[]; allow: RegExp[] }
  >;

  constructor(
    defaults?: PermissionDefaults | null,
    tools?: Record<string, ToolPermission | Record<string, unknown>> | null,
    projectDir?: string,
  ) {
    this._defaults = defaults ?? {
      unknownTool: "ask",
      unknownPath: "deny",
      onError: "deny",
    };

    this._tools = new Map();
    this._compiled = new Map();

    if (tools) {
      for (const [name, tp] of Object.entries(tools)) {
        const normalized = this._normalizeToolPermission(tp);
        if (normalized) {
          this._tools.set(name, normalized);
          this._compiled.set(name, {
            deny: this._compilePatterns(normalized.denyPatterns ?? []),
            ask: this._compilePatterns(normalized.askPatterns ?? []),
            allow: this._compilePatterns(normalized.allowPatterns ?? []),
          });
        }
      }
    }

    this._projectDir = projectDir ?? process.cwd();
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  /** Return the final permission decision for a tool call. */
  decide(
    toolCall: ToolCall,
    risk: RiskAssessment,
    hookResults: HookResult[],
  ): PermissionDecision {
    const toolName = toolCall.toolName;

    // Priority 1: Explicit constitution denies (path + operation)
    const filePath = this._extractPath(toolCall);
    const command = this._extractCommand(toolCall);

    const pathDecision = filePath ? this.checkPathLevel(toolName, filePath) : null;
    const opDecision = command ? this.checkOperationLevel(toolName, command) : null;

    if (pathDecision?.action === "deny") return pathDecision;
    if (opDecision?.action === "deny") return opDecision;

    // Priority 2: Hook deny
    for (const hr of hookResults) {
      if (hr.action === "deny") {
        return {
          action: "deny",
          reason: hr.reason ?? "Blocked by hook",
          source: "hook",
        };
      }
    }

    // Tool level deny check
    const toolDecision = this.checkToolLevel(toolName);
    if (toolDecision?.action === "deny") return toolDecision;

    // Priority 3: ask_patterns / ask_paths
    if (pathDecision?.action === "ask") return pathDecision;
    if (opDecision?.action === "ask") return opDecision;

    // Priority 5: Hook allow (cannot override denies above)
    const hookResolved = this._resolveHookPermission(hookResults);
    if (hookResolved.action === "allow") return hookResolved;
    if (hookResolved.action === "ask") {
      const hasHookAsk = hookResults.some((hr) => hr.action === "ask");
      if (hasHookAsk) return hookResolved;
    }

    // Priority 6: Explicit allow_paths / allow_patterns
    if (pathDecision?.action === "allow") return pathDecision;
    if (opDecision?.action === "allow") return opDecision;

    // Priority 7: Tool default policy
    const tp = this._tools.get(toolName);
    if (tp?.policy != null) {
      return {
        action: tp.policy === "allow" || tp.policy === "deny" ? tp.policy : "ask",
        reason: `Tool policy: ${tp.policy}`,
        source: "tool_policy",
      };
    }

    // Priority 8: Global default
    if (!tp) {
      return {
        action: this._defaults.unknownTool,
        reason: `Unknown tool fallback: ${this._defaults.unknownTool}`,
        source: "defaults",
      };
    }

    return {
      action: "ask",
      reason: "No specific policy matched",
      source: "defaults",
    };
  }

  // ------------------------------------------------------------------
  // Level 1: Tool
  // ------------------------------------------------------------------

  checkToolLevel(toolName: string): PermissionDecision | null {
    const tp = this._tools.get(toolName);
    if (!tp) return null;
    if (tp.policy === "deny") {
      return {
        action: "deny",
        reason: `Tool '${toolName}' is denied by policy`,
        source: "tool_policy",
      };
    }
    return null;
  }

  // ------------------------------------------------------------------
  // Level 2: Path
  // ------------------------------------------------------------------

  checkPathLevel(
    toolName: string,
    filePath: string,
  ): PermissionDecision | null {
    if (!filePath) return null;

    // Reject path traversal
    if (this._isTraversal(filePath)) {
      return {
        action: "deny",
        reason: `Path traversal detected: ${filePath}`,
        source: "path_guard",
      };
    }

    const tp = this._tools.get(toolName);
    if (!tp) return null;

    const resolved = this._expandPath(filePath);

    // Deny first
    for (const pattern of tp.denyPaths ?? []) {
      if (globMatch(resolved, this._expandPath(pattern))) {
        return {
          action: "deny",
          reason: `Path matches deny rule: ${pattern}`,
          source: "deny_paths",
        };
      }
    }

    // Ask
    for (const pattern of tp.askPaths ?? []) {
      if (globMatch(resolved, this._expandPath(pattern))) {
        return {
          action: "ask",
          reason: `Path matches ask rule: ${pattern}`,
          source: "ask_paths",
        };
      }
    }

    // Allow
    for (const pattern of tp.allowPaths ?? []) {
      if (globMatch(resolved, this._expandPath(pattern))) {
        return {
          action: "allow",
          reason: `Path matches allow rule: ${pattern}`,
          source: "allow_paths",
        };
      }
    }

    return null;
  }

  // ------------------------------------------------------------------
  // Level 3: Operation
  // ------------------------------------------------------------------

  checkOperationLevel(
    toolName: string,
    operation: string,
  ): PermissionDecision | null {
    if (!operation) return null;

    const compiled = this._compiled.get(toolName);
    if (!compiled) return null;

    for (const rx of compiled.deny) {
      if (rx.test(operation)) {
        return {
          action: "deny",
          reason: `Operation matches deny pattern: ${rx.source}`,
          source: "deny_patterns",
        };
      }
    }

    for (const rx of compiled.ask) {
      if (rx.test(operation)) {
        return {
          action: "ask",
          reason: `Operation matches ask pattern: ${rx.source}`,
          source: "ask_patterns",
        };
      }
    }

    for (const rx of compiled.allow) {
      if (rx.test(operation)) {
        return {
          action: "allow",
          reason: `Operation matches allow pattern: ${rx.source}`,
          source: "allow_patterns",
        };
      }
    }

    return null;
  }

  // ------------------------------------------------------------------
  // Hook resolution
  // ------------------------------------------------------------------

  private _resolveHookPermission(hookResults: HookResult[]): PermissionDecision {
    let hasDeny = false;
    let hasAllow = false;
    let hasAsk = false;

    for (const hr of hookResults) {
      if (hr.action === "deny") hasDeny = true;
      else if (hr.action === "allow") hasAllow = true;
      else if (hr.action === "ask") hasAsk = true;
    }

    if (hasDeny) return { action: "deny", reason: "Hook denied", source: "hook" };
    if (hasAsk) return { action: "ask", reason: "Hook requires confirmation", source: "hook" };
    if (hasAllow) return { action: "allow", reason: "Hook allowed", source: "hook" };

    return { action: "ask", reason: "default", source: "hook" };
  }

  // ------------------------------------------------------------------
  // Input extraction helpers
  // ------------------------------------------------------------------

  private _extractPath(toolCall: ToolCall): string | null {
    for (const key of PATH_KEYS) {
      const val = toolCall.toolInput[key];
      if (typeof val === "string" && val) return val;
    }

    if (BASH_TOOLS.has(toolCall.toolName)) {
      const cmd = toolCall.toolInput["command"];
      if (typeof cmd === "string") return this._pathFromCommand(cmd);
    }

    return null;
  }

  private _extractCommand(toolCall: ToolCall): string | null {
    if (BASH_TOOLS.has(toolCall.toolName)) {
      const cmd = toolCall.toolInput["command"];
      if (typeof cmd === "string" && cmd) return cmd;
    }
    return null;
  }

  // ------------------------------------------------------------------
  // Internal helpers
  // ------------------------------------------------------------------

  private _expandPath(p: string): string {
    let expanded = p.replace(/\$\{PROJECT_DIR\}/g, this._projectDir);
    if (expanded.startsWith("~")) {
      const home = process.env["HOME"] ?? process.env["USERPROFILE"] ?? "";
      expanded = home + expanded.slice(1);
    }
    return path.normalize(expanded);
  }

  private _isTraversal(p: string): boolean {
    const parts = p.split(path.sep);
    return parts.includes("..");
  }

  private _pathFromCommand(cmd: string): string | null {
    for (const token of cmd.split(/\s+/)) {
      if (
        token.startsWith("/") ||
        token.startsWith("~") ||
        token.startsWith("./")
      ) {
        const cleaned = token.replace(/[;&|]+$/, "");
        if (cleaned) return cleaned;
      }
    }
    return null;
  }

  private _compilePatterns(patterns: string[]): RegExp[] {
    const compiled: RegExp[] = [];
    for (const raw of patterns) {
      try {
        compiled.push(new RegExp(raw));
      } catch {
        // Skip invalid patterns
      }
    }
    return compiled;
  }

  private _normalizeToolPermission(
    tp: ToolPermission | Record<string, unknown>,
  ): ToolPermission | null {
    if ("policy" in tp && typeof tp.policy === "string") {
      return tp as ToolPermission;
    }
    // Default to "restricted" if no policy
    return { ...tp, policy: "restricted" } as ToolPermission;
  }
}
