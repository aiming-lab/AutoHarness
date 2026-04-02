/**
 * Hook Registry — manages registration and execution of pre/post tool use hooks.
 *
 * Hooks are functions that run before or after tool execution, providing
 * guardrails such as secret scanning, path guarding, risk-based gating,
 * config protection, and output sanitization.
 *
 * Profiles control which built-in hooks are active:
 *   - minimal:  secret_scanner, path_guard
 *   - standard: minimal + risk_classifier, output_sanitizer
 *   - strict:   standard + config_protector
 */

import * as path from "node:path";
import type {
  HookResult,
  PermissionDecision,
  RiskAssessment,
  ToolCall,
  ToolResult,
} from "./types.js";
import { BUILTIN_RULES } from "./rules/builtin.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PreHookFn = (
  toolCall: ToolCall,
  risk: RiskAssessment,
  context: Record<string, unknown>,
) => HookResult;

export type PostHookFn = (
  toolCall: ToolCall,
  result: ToolResult,
  context: Record<string, unknown>,
) => HookResult;

export type BlockHookFn = (
  toolCall: ToolCall,
  decision: PermissionDecision,
  context: Record<string, unknown>,
) => void;

interface NamedHook<T> {
  name: string;
  fn: T;
}

// ---------------------------------------------------------------------------
// Module-level decorator registry
// ---------------------------------------------------------------------------

type HookEvent = "pre_tool_use" | "post_tool_use" | "on_block";

const _REGISTERED_HOOKS: Record<HookEvent, Array<{ name: string; fn: Function }>> = {
  pre_tool_use: [],
  post_tool_use: [],
  on_block: [],
};

/**
 * Decorator-style registration for custom hooks.
 *
 * Usage:
 *   const myScanner = hook("pre_tool_use", "my_scanner", (toolCall, risk, ctx) => {
 *     return { action: "allow" };
 *   });
 */
export function hook<T extends Function>(
  event: HookEvent,
  name: string,
  fn: T,
): T {
  _REGISTERED_HOOKS[event].push({ name, fn });
  return fn;
}

// ---------------------------------------------------------------------------
// Compiled patterns for built-in hooks
// ---------------------------------------------------------------------------

let _secretCompiled: Array<{ description: string; regex: RegExp }> = [];
let _configCompiled: RegExp[] = [];
let _patternsInitialized = false;

function ensurePatterns(): void {
  if (_patternsInitialized) return;

  // Secrets — pull from secrets_in_content category
  const secretsByLevel = BUILTIN_RULES["secrets_in_content"] ?? {};
  for (const patterns of Object.values(secretsByLevel)) {
    if (!patterns) continue;
    for (const rp of patterns) {
      try {
        _secretCompiled.push({
          description: rp.description,
          regex: new RegExp(rp.pattern),
        });
      } catch {
        // Skip bad patterns
      }
    }
  }

  // Protected config file patterns
  const configPatterns = [
    String.raw`\.eslintrc(?:\.(?:js|cjs|mjs|json|yml|yaml))?$`,
    String.raw`\.prettierrc(?:\.(?:js|cjs|mjs|json|yml|yaml|toml))?$`,
    String.raw`prettier\.config\.(?:js|cjs|mjs)$`,
    String.raw`biome\.jsonc?$`,
    String.raw`ruff\.toml$`,
    String.raw`\.flake8$`,
    String.raw`\.pylintrc$`,
    String.raw`pyproject\.toml$`,
    String.raw`tsconfig(?:\..*)?\.json$`,
    String.raw`\.stylelintrc(?:\.(?:js|cjs|mjs|json|yml|yaml))?$`,
    String.raw`\.editorconfig$`,
    String.raw`\.rustfmt\.toml$`,
    String.raw`clippy\.toml$`,
    String.raw`\.golangci\.ya?ml$`,
    String.raw`\.rubocop\.ya?ml$`,
  ];
  for (const pat of configPatterns) {
    try {
      _configCompiled.push(new RegExp(pat));
    } catch {
      // Skip
    }
  }

  _patternsInitialized = true;
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

const PATH_TRAVERSAL_PATTERN = /(?:^|\/)\.\.(?:\/|$)/;

const PATH_KEYS = new Set([
  "file_path",
  "path",
  "file",
  "directory",
  "dir",
  "dest",
  "destination",
  "command",
]);

function extractPaths(toolCall: ToolCall): string[] {
  const paths: string[] = [];
  for (const key of PATH_KEYS) {
    const val = toolCall.toolInput[key];
    if (typeof val === "string" && val) {
      paths.push(val);
    }
  }
  // Scan all string values for path-like content
  for (const val of Object.values(toolCall.toolInput)) {
    if (
      typeof val === "string" &&
      val.includes("/") &&
      val.length < 500 &&
      !paths.includes(val)
    ) {
      paths.push(val);
    }
  }
  return paths;
}

function collectText(toolCall: ToolCall): string {
  const parts: string[] = [];
  for (const val of Object.values(toolCall.toolInput)) {
    if (typeof val === "string") {
      parts.push(val);
    } else if (typeof val === "object" && val !== null && !Array.isArray(val)) {
      for (const nested of Object.values(val as Record<string, unknown>)) {
        if (typeof nested === "string") parts.push(nested);
      }
    }
  }
  return parts.join("\n");
}

// ---------------------------------------------------------------------------
// Profile levels
// ---------------------------------------------------------------------------

const PROFILE_LEVELS: Record<string, number> = {
  minimal: 0,
  standard: 1,
  strict: 2,
};

// ---------------------------------------------------------------------------
// HookRegistry
// ---------------------------------------------------------------------------

export class HookRegistry {
  private readonly _profile: string;
  private readonly _profileLevel: number;
  private readonly _projectRoot: string;
  private readonly _preHooks: NamedHook<PreHookFn>[] = [];
  private readonly _postHooks: NamedHook<PostHookFn>[] = [];
  private readonly _blockHooks: NamedHook<BlockHookFn>[] = [];

  constructor(profile: string = "standard", projectRoot?: string) {
    if (!(profile in PROFILE_LEVELS)) {
      throw new Error(
        `Unknown profile '${profile}'. Choose from: ${Object.keys(PROFILE_LEVELS).join(", ")}`,
      );
    }
    this._profile = profile;
    this._profileLevel = PROFILE_LEVELS[profile]!;
    this._projectRoot = projectRoot
      ? path.resolve(projectRoot)
      : process.cwd();

    ensurePatterns();
    this._registerBuiltinHooks();
  }

  // ------------------------------------------------------------------
  // Built-in hook registration
  // ------------------------------------------------------------------

  private _registerBuiltinHooks(): void {
    // minimal+ hooks
    if (this._profileLevel >= 0) {
      this._preHooks.push({ name: "secret_scanner", fn: this._secretScanner.bind(this) });
      this._preHooks.push({ name: "path_guard", fn: this._pathGuard.bind(this) });
    }

    // standard+ hooks
    if (this._profileLevel >= 1) {
      this._preHooks.push({ name: "risk_classifier", fn: this._riskClassifierHook.bind(this) });
      this._postHooks.push({ name: "output_sanitizer", fn: this._outputSanitizer.bind(this) });
    }

    // strict+ hooks
    if (this._profileLevel >= 2) {
      this._preHooks.push({ name: "config_protector", fn: this._configProtector.bind(this) });
    }
  }

  // ------------------------------------------------------------------
  // Built-in pre-hooks
  // ------------------------------------------------------------------

  private _secretScanner(
    toolCall: ToolCall,
    _risk: RiskAssessment,
    _context: Record<string, unknown>,
  ): HookResult {
    const text = collectText(toolCall);
    if (!text.trim()) return { action: "allow" };

    for (const { description, regex } of _secretCompiled) {
      regex.lastIndex = 0;
      if (regex.test(text)) {
        return {
          action: "deny",
          reason: `Secret detected in tool input: ${description}`,
          severity: "error",
        };
      }
    }

    return { action: "allow" };
  }

  private _pathGuard(
    toolCall: ToolCall,
    _risk: RiskAssessment,
    _context: Record<string, unknown>,
  ): HookResult {
    const paths = extractPaths(toolCall);
    if (paths.length === 0) return { action: "allow" };

    for (const rawPath of paths) {
      // Check for explicit traversal patterns
      if (PATH_TRAVERSAL_PATTERN.test(rawPath)) {
        return {
          action: "deny",
          reason: `Path traversal detected: '${rawPath}'`,
          severity: "error",
        };
      }

      // Resolve and check containment
      try {
        const resolved = path.resolve(rawPath);
        if (
          !resolved.startsWith(this._projectRoot + path.sep) &&
          resolved !== this._projectRoot
        ) {
          // Allow common safe system paths
          const safePrefixes = ["/tmp", "/var/tmp", "/dev/null", "/dev/stderr", "/dev/stdout"];
          if (!safePrefixes.some((p) => resolved.startsWith(p))) {
            return {
              action: "deny",
              reason: `Path escapes project directory: '${rawPath}' resolves to '${resolved}' (project root: '${this._projectRoot}')`,
              severity: "error",
            };
          }
        }
      } catch {
        // Can't resolve — skip rather than false-positive
      }
    }

    return { action: "allow" };
  }

  private _riskClassifierHook(
    _toolCall: ToolCall,
    risk: RiskAssessment,
    _context: Record<string, unknown>,
  ): HookResult {
    if (risk.level === "critical") {
      return {
        action: "deny",
        reason: `Critical risk: ${risk.reason}`,
        severity: "error",
      };
    }
    if (risk.level === "high") {
      return {
        action: "ask",
        reason: `High risk requires confirmation: ${risk.reason}`,
        severity: "warning",
      };
    }
    if (risk.level === "medium") {
      return {
        action: "allow",
        reason: `Medium risk (logged): ${risk.reason}`,
        severity: "warning",
      };
    }
    return { action: "allow", severity: "info" };
  }

  private _configProtector(
    toolCall: ToolCall,
    _risk: RiskAssessment,
    _context: Record<string, unknown>,
  ): HookResult {
    const writeTools = new Set(["file_write", "file_edit", "Edit", "Write"]);
    if (!writeTools.has(toolCall.toolName)) {
      return { action: "allow" };
    }

    const paths = extractPaths(toolCall);
    for (const rawPath of paths) {
      const basename = path.basename(rawPath);
      for (const pattern of _configCompiled) {
        pattern.lastIndex = 0;
        if (pattern.test(basename) || pattern.test(rawPath)) {
          return {
            action: "deny",
            reason: `Modification to protected config file blocked: '${basename}'. Fix the code, don't weaken the linter.`,
            severity: "error",
          };
        }
      }
    }

    return { action: "allow" };
  }

  // ------------------------------------------------------------------
  // Built-in post-hooks
  // ------------------------------------------------------------------

  private _outputSanitizer(
    _toolCall: ToolCall,
    result: ToolResult,
    _context: Record<string, unknown>,
  ): HookResult {
    const outputText = result.output != null ? String(result.output) : "";
    if (!outputText.trim()) return { action: "allow" };

    let sanitized = outputText;
    let foundAny = false;

    for (const { description, regex } of _secretCompiled) {
      const newText = sanitized.replace(regex, "[REDACTED]");
      if (newText !== sanitized) {
        foundAny = true;
        sanitized = newText;
      }
    }

    if (foundAny) {
      return {
        action: "sanitize",
        reason: "Secrets redacted from tool output",
        severity: "warning",
        sanitizedOutput: sanitized,
      };
    }

    return { action: "allow" };
  }

  // ------------------------------------------------------------------
  // Public registration API
  // ------------------------------------------------------------------

  /** Register a hook function for a given event. */
  register(
    event: HookEvent,
    hookFn: PreHookFn | PostHookFn | BlockHookFn,
    name?: string,
  ): void {
    const hookName = name ?? hookFn.name ?? "anonymous";

    if (event === "pre_tool_use") {
      this._preHooks.push({ name: hookName, fn: hookFn as PreHookFn });
    } else if (event === "post_tool_use") {
      this._postHooks.push({ name: hookName, fn: hookFn as PostHookFn });
    } else if (event === "on_block") {
      this._blockHooks.push({ name: hookName, fn: hookFn as BlockHookFn });
    } else {
      throw new Error(
        `Unknown hook event '${event}'. Choose from: pre_tool_use, post_tool_use, on_block`,
      );
    }
  }

  /** Pick up all hook()-registered functions from the module-level registry. */
  registerFromDecorators(): void {
    for (const [event, funcs] of Object.entries(_REGISTERED_HOOKS) as Array<
      [HookEvent, Array<{ name: string; fn: Function }>]
    >) {
      for (const { name, fn } of funcs) {
        this.register(event, fn as PreHookFn, name);
      }
    }
  }

  // ------------------------------------------------------------------
  // Execution
  // ------------------------------------------------------------------

  /** Run all pre_tool_use hooks. Short-circuits on first deny. */
  runPreHooks(
    toolCall: ToolCall,
    risk: RiskAssessment,
    context: Record<string, unknown>,
  ): HookResult[] {
    const results: HookResult[] = [];

    for (const { name, fn } of this._preHooks) {
      try {
        const result = fn(toolCall, risk, context);
        results.push(result);

        if (result.action === "deny") {
          break; // Short-circuit on deny
        }
      } catch (err) {
        results.push({
          action: "allow",
          reason: `Hook '${name}' raised an exception (see logs)`,
          severity: "warning",
        });
      }
    }

    return results;
  }

  /** Run all post_tool_use hooks. Returns [potentially modified result, hook results]. */
  runPostHooks(
    toolCall: ToolCall,
    result: ToolResult,
    context: Record<string, unknown>,
  ): [ToolResult, HookResult[]] {
    const hookResults: HookResult[] = [];
    let currentResult = result;

    for (const { name, fn } of this._postHooks) {
      try {
        const hr = fn(toolCall, currentResult, context);
        hookResults.push(hr);

        // If a hook requests sanitization, rebuild the ToolResult
        if (hr.action === "sanitize" && hr.sanitizedOutput != null) {
          currentResult = {
            ...currentResult,
            output: hr.sanitizedOutput,
            sanitized: true,
          };
        }
      } catch (err) {
        hookResults.push({
          action: "allow",
          reason: `Hook '${name}' raised an exception (see logs)`,
          severity: "warning",
        });
      }
    }

    return [currentResult, hookResults];
  }

  /** Notify on_block hooks that an action was blocked. */
  runBlockHooks(
    toolCall: ToolCall,
    decision: PermissionDecision,
    context: Record<string, unknown>,
  ): void {
    for (const { fn } of this._blockHooks) {
      try {
        fn(toolCall, decision, context);
      } catch {
        // Block hooks are informational — errors are swallowed
      }
    }
  }

  // ------------------------------------------------------------------
  // Introspection
  // ------------------------------------------------------------------

  get profile(): string {
    return this._profile;
  }

  get projectRoot(): string {
    return this._projectRoot;
  }

  listHooks(): Record<string, string[]> {
    return {
      pre_tool_use: this._preHooks.map((h) => h.name),
      post_tool_use: this._postHooks.map((h) => h.name),
      on_block: this._blockHooks.map((h) => h.name),
    };
  }
}
