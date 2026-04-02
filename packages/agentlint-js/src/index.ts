/**
 * AutoHarness — AI agent behavioral governance middleware for Node.js
 *
 * Provides two ways to use AutoHarness governance:
 *
 * 1. **Client wrapping** — transparently intercept tool calls from Anthropic or
 *    OpenAI clients:
 *
 *    ```ts
 *    import Anthropic from "@anthropic-ai/sdk";
 *    import { AutoHarness } from "autoharness";
 *
 *    const client = AutoHarness.wrap(new Anthropic(), { constitution: "constitution.yaml" });
 *    ```
 *
 * 2. **Standalone linting** — check a single tool call without wrapping:
 *
 *    ```ts
 *    import { lintToolCall } from "autoharness";
 *
 *    const result = lintToolCall("Bash", { command: "rm -rf /" });
 *    console.log(result.status); // "blocked"
 *    ```
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { randomUUID } from "node:crypto";
import { Constitution } from "./constitution.js";
import { ToolGovernancePipeline } from "./pipeline.js";
import type {
  PermissionDecision,
  ToolCall,
  ToolResult,
} from "./types.js";

// Re-export everything consumers need
export { Constitution, ConstitutionError } from "./constitution.js";
export { RiskClassifier } from "./risk.js";
export { PermissionEngine } from "./permissions.js";
export { HookRegistry, hook } from "./hooks.js";
export { AuditEngine } from "./audit.js";
export { ToolGovernancePipeline } from "./pipeline.js";
export {
  RiskLevel,
  HookAction,
  Enforcement,
  RuleSeverity,
  HookProfile,
  ToolCallSchema,
  ToolResultSchema,
  RiskAssessmentSchema,
  HookResultSchema,
  PermissionDecisionSchema,
  AuditRecordSchema,
  RuleSchema,
  ToolPermissionSchema,
  PermissionDefaultsSchema,
  ConstitutionConfigSchema,
  hashToolInput,
  hashToolInputSync,
} from "./types.js";
export type {
  ToolCall,
  ToolResult,
  RiskAssessment,
  HookResult,
  PermissionDecision,
  AuditRecord,
  Rule,
  ToolPermission,
  PermissionDefaults,
  ConstitutionConfig,
  RiskPattern,
} from "./types.js";
export type { PreHookFn, PostHookFn, BlockHookFn } from "./hooks.js";
export type { ToolExecutor, BlockCallback } from "./pipeline.js";
export { BUILTIN_RULES, SAFE_COMMAND_PREFIXES } from "./rules/builtin.js";

// ---------------------------------------------------------------------------
// Prompt addendum
// ---------------------------------------------------------------------------

const PROMPT_ADDENDUM_MARKER = "<!-- autoharness:governance -->";

function buildPromptAddendum(constitution: Constitution): string {
  const rulesLines: string[] = [];
  for (const rule of constitution.rules) {
    const tag = rule.severity ? `[${rule.severity.toUpperCase()}]` : "";
    rulesLines.push(`- ${tag} ${rule.description}`);
  }
  if (rulesLines.length === 0) {
    rulesLines.push("- Default safety rules are active.");
  }

  return `${PROMPT_ADDENDUM_MARKER}
[AutoHarness Governance Active]
The following behavioral rules are enforced. Tool calls that violate these rules
will be blocked or require confirmation before execution:
${rulesLines.join("\n")}
Do not attempt to circumvent these rules.`;
}

// ---------------------------------------------------------------------------
// Constitution resolver
// ---------------------------------------------------------------------------

function resolveConstitution(
  constitution: string | Record<string, unknown> | Constitution | null | undefined,
  projectDir?: string,
): Constitution {
  if (!constitution) {
    // Auto-discovery
    const searchDir = projectDir ?? process.cwd();
    const candidates = [
      "constitution.yaml",
      "constitution.yml",
      ".autoharness/constitution.yaml",
      ".autoharness/constitution.yml",
      "autoharness.yaml",
      "autoharness.yml",
    ];
    for (const candidate of candidates) {
      const candidatePath = path.join(searchDir, candidate);
      if (fs.existsSync(candidatePath)) {
        return Constitution.load(candidatePath);
      }
    }
    return Constitution.default();
  }

  if (constitution instanceof Constitution) return constitution;

  if (typeof constitution === "object") {
    return Constitution.fromDict(constitution);
  }

  if (typeof constitution === "string") {
    return Constitution.load(constitution);
  }

  throw new TypeError(
    `constitution must be a path (string), object, Constitution, or null; got ${typeof constitution}`,
  );
}

// ---------------------------------------------------------------------------
// Client type detection
// ---------------------------------------------------------------------------

function detectClientType(client: unknown): "anthropic" | "openai" {
  if (!client || typeof client !== "object") {
    throw new TypeError("Client must be an object");
  }

  const obj = client as Record<string, unknown>;
  const constructor = obj.constructor;
  const className = constructor?.name ?? "";
  const moduleName = String(
    (constructor as unknown as Record<string, unknown>)?.["__module__"] ?? "",
  );

  if (
    className === "Anthropic" ||
    className === "AsyncAnthropic" ||
    moduleName.includes("anthropic") ||
    "messages" in client
  ) {
    return "anthropic";
  }

  if (
    className === "OpenAI" ||
    className === "AsyncOpenAI" ||
    moduleName.includes("openai") ||
    "chat" in client
  ) {
    return "openai";
  }

  throw new TypeError(
    `Unsupported client type: ${className}. AutoHarness supports Anthropic and OpenAI clients.`,
  );
}

// ---------------------------------------------------------------------------
// Anthropic wrapper
// ---------------------------------------------------------------------------

class GovernedMessagesAPI {
  private _original: Record<string, unknown>;
  private _pipeline: ToolGovernancePipeline;
  private _promptAddendum: string;

  constructor(
    originalMessages: unknown,
    pipeline: ToolGovernancePipeline,
    promptAddendum: string,
  ) {
    this._original = originalMessages as Record<string, unknown>;
    this._pipeline = pipeline;
    this._promptAddendum = promptAddendum;
  }

  async create(kwargs: Record<string, unknown>): Promise<unknown> {
    // Step 1: Inject prompt addendum
    kwargs = this._injectSystemPrompt(kwargs);

    // Step 2: Call original API
    const createFn = this._original["create"] as Function;
    const response = await createFn.call(this._original, kwargs);

    // Step 3: Govern tool_use blocks
    return this._governResponse(response);
  }

  private _injectSystemPrompt(
    kwargs: Record<string, unknown>,
  ): Record<string, unknown> {
    kwargs = { ...kwargs };
    const system = kwargs["system"];

    if (typeof system === "string") {
      if (!system.includes(PROMPT_ADDENDUM_MARKER)) {
        const sep = system.trim() ? "\n\n" : "";
        kwargs["system"] = system + sep + this._promptAddendum;
      }
    }

    return kwargs;
  }

  private _governResponse(response: unknown): unknown {
    if (!response || typeof response !== "object") return response;

    const resp = response as Record<string, unknown>;
    const content = resp["content"];
    if (!Array.isArray(content)) return response;

    for (const block of content) {
      if (!block || typeof block !== "object") continue;
      const b = block as Record<string, unknown>;
      if (b["type"] !== "tool_use") continue;

      const toolName = (b["name"] as string) ?? "unknown";
      const toolInput = (b["input"] as Record<string, unknown>) ?? {};

      const tc: ToolCall = {
        toolName,
        toolInput,
        metadata: { tool_use_id: b["id"], provider: "anthropic" },
        timestamp: new Date(),
      };

      const decision = this._pipeline.evaluate(tc);

      if (decision.action === "deny") {
        (b as Record<string, unknown>)["_autoharness_blocked"] = true;
        (b as Record<string, unknown>)["_autoharness_reason"] = decision.reason;
      } else if (decision.action === "ask") {
        (b as Record<string, unknown>)["_autoharness_ask"] = true;
        (b as Record<string, unknown>)["_autoharness_reason"] = decision.reason;
      }
    }

    return response;
  }
}

class AnthropicWrapper {
  private _client: unknown;
  private _pipeline: ToolGovernancePipeline;
  private _messages: GovernedMessagesAPI;

  constructor(
    client: unknown,
    pipeline: ToolGovernancePipeline,
    promptAddendum: string,
  ) {
    this._client = client;
    this._pipeline = pipeline;
    this._messages = new GovernedMessagesAPI(
      (client as Record<string, unknown>)["messages"],
      pipeline,
      promptAddendum,
    );
  }

  get messages(): GovernedMessagesAPI {
    return this._messages;
  }

  get pipeline(): ToolGovernancePipeline {
    return this._pipeline;
  }
}

// ---------------------------------------------------------------------------
// OpenAI wrapper
// ---------------------------------------------------------------------------

class GovernedCompletionsAPI {
  private _original: Record<string, unknown>;
  private _pipeline: ToolGovernancePipeline;
  private _promptAddendum: string;

  constructor(
    originalCompletions: unknown,
    pipeline: ToolGovernancePipeline,
    promptAddendum: string,
  ) {
    this._original = originalCompletions as Record<string, unknown>;
    this._pipeline = pipeline;
    this._promptAddendum = promptAddendum;
  }

  async create(kwargs: Record<string, unknown>): Promise<unknown> {
    kwargs = this._injectSystemPrompt(kwargs);
    const createFn = this._original["create"] as Function;
    const response = await createFn.call(this._original, kwargs);
    return this._governResponse(response);
  }

  private _injectSystemPrompt(
    kwargs: Record<string, unknown>,
  ): Record<string, unknown> {
    kwargs = { ...kwargs };
    const messages = kwargs["messages"];
    if (!Array.isArray(messages) || messages.length === 0) return kwargs;

    const msgs = [...messages];

    // Find first system message
    for (let i = 0; i < msgs.length; i++) {
      const msg = msgs[i] as Record<string, unknown>;
      if (msg["role"] === "system") {
        const content = msg["content"];
        if (
          typeof content === "string" &&
          !content.includes(PROMPT_ADDENDUM_MARKER)
        ) {
          msgs[i] = { ...msg, content: content + "\n\n" + this._promptAddendum };
          kwargs["messages"] = msgs;
          return kwargs;
        }
        return kwargs;
      }
    }

    // No system message — prepend one
    msgs.unshift({ role: "system", content: this._promptAddendum });
    kwargs["messages"] = msgs;
    return kwargs;
  }

  private _governResponse(response: unknown): unknown {
    if (!response || typeof response !== "object") return response;

    const resp = response as Record<string, unknown>;
    const choices = resp["choices"] as Array<Record<string, unknown>> | undefined;
    if (!choices?.length) return response;

    const message = choices[0]?.["message"] as Record<string, unknown> | undefined;
    if (!message) return response;

    const toolCalls = message["tool_calls"] as Array<Record<string, unknown>> | undefined;
    if (!toolCalls) return response;

    for (const tcObj of toolCalls) {
      const func = tcObj["function"] as Record<string, unknown> | undefined;
      if (!func) continue;

      const toolName = (func["name"] as string) ?? "unknown";
      let toolInput: Record<string, unknown> = {};
      try {
        toolInput = JSON.parse((func["arguments"] as string) ?? "{}");
      } catch {
        // Keep empty
      }

      const tc: ToolCall = {
        toolName,
        toolInput,
        metadata: { tool_call_id: tcObj["id"], provider: "openai" },
        timestamp: new Date(),
      };

      const decision = this._pipeline.evaluate(tc);

      if (decision.action === "deny") {
        (tcObj as Record<string, unknown>)["_autoharness_blocked"] = true;
        (tcObj as Record<string, unknown>)["_autoharness_reason"] = decision.reason;
      } else if (decision.action === "ask") {
        (tcObj as Record<string, unknown>)["_autoharness_ask"] = true;
        (tcObj as Record<string, unknown>)["_autoharness_reason"] = decision.reason;
      }
    }

    return response;
  }
}

class GovernedChatAPI {
  private _completions: GovernedCompletionsAPI;

  constructor(
    originalChat: unknown,
    pipeline: ToolGovernancePipeline,
    promptAddendum: string,
  ) {
    const chat = originalChat as Record<string, unknown>;
    this._completions = new GovernedCompletionsAPI(
      chat["completions"],
      pipeline,
      promptAddendum,
    );
  }

  get completions(): GovernedCompletionsAPI {
    return this._completions;
  }
}

class OpenAIWrapper {
  private _client: unknown;
  private _pipeline: ToolGovernancePipeline;
  private _chat: GovernedChatAPI;

  constructor(
    client: unknown,
    pipeline: ToolGovernancePipeline,
    promptAddendum: string,
  ) {
    this._client = client;
    this._pipeline = pipeline;
    this._chat = new GovernedChatAPI(
      (client as Record<string, unknown>)["chat"],
      pipeline,
      promptAddendum,
    );
  }

  get chat(): GovernedChatAPI {
    return this._chat;
  }

  get pipeline(): ToolGovernancePipeline {
    return this._pipeline;
  }
}

// ---------------------------------------------------------------------------
// AutoHarness — main entry point
// ---------------------------------------------------------------------------

export interface WrapOptions {
  /** Path to YAML file, plain object, Constitution instance, or null for auto-discovery. */
  constitution?: string | Record<string, unknown> | Constitution | null;
  /** Custom hook functions. */
  hooks?: Function[];
  /** Project root directory for path scoping. */
  projectDir?: string;
  /** Session ID for audit trail. */
  sessionId?: string;
}

export class AutoHarness {
  /**
   * Wrap an LLM client with governance middleware.
   *
   * Returns a wrapped client that intercepts tool_use and applies governance.
   */
  static wrap(
    client: unknown,
    options: WrapOptions = {},
  ): AnthropicWrapper | OpenAIWrapper {
    const clientType = detectClientType(client);
    const resolved = resolveConstitution(options.constitution, options.projectDir);

    const pipeline = new ToolGovernancePipeline(resolved, {
      projectDir: options.projectDir,
      sessionId: options.sessionId,
    });

    // Register custom hooks
    if (options.hooks?.length) {
      for (const hookFn of options.hooks) {
        const hookObj = hookFn as unknown as Record<string, unknown>;
        const event =
          (hookObj["_hook_event"] as string) ?? "pre_tool_use";
        const name =
          (hookObj["_hook_name"] as string) ?? hookFn.name;
        pipeline.hookRegistry.register(
          event as "pre_tool_use" | "post_tool_use" | "on_block",
          hookFn as (...args: unknown[]) => unknown,
          name,
        );
      }
    }

    const addendum = buildPromptAddendum(resolved);

    if (clientType === "anthropic") {
      return new AnthropicWrapper(client, pipeline, addendum);
    }
    return new OpenAIWrapper(client, pipeline, addendum);
  }

  /**
   * Create a standalone governance pipeline without wrapping a client.
   */
  static fromConstitution(
    options: {
      constitution?: string | Record<string, unknown> | Constitution | null;
      projectDir?: string;
      sessionId?: string;
    } = {},
  ): ToolGovernancePipeline {
    const resolved = resolveConstitution(options.constitution, options.projectDir);
    return new ToolGovernancePipeline(resolved, {
      projectDir: options.projectDir,
      sessionId: options.sessionId,
    });
  }
}

// ---------------------------------------------------------------------------
// Standalone function
// ---------------------------------------------------------------------------

/**
 * One-shot governance check without wrapping a client.
 *
 * Evaluates a single tool call against the constitution and returns
 * a ToolResult indicating whether the call would be allowed, blocked, or flagged.
 *
 * @example
 * ```ts
 * const result = lintToolCall("Bash", { command: "rm -rf /" });
 * console.log(result.status); // "blocked"
 * ```
 */
export function lintToolCall(
  toolName: string,
  toolInput: Record<string, unknown>,
  options: {
    constitution?: string | Record<string, unknown> | Constitution | null;
    projectDir?: string;
    sessionId?: string;
    metadata?: Record<string, unknown>;
  } = {},
): ToolResult {
  const resolved = resolveConstitution(options.constitution, options.projectDir);
  const pipeline = new ToolGovernancePipeline(resolved, {
    projectDir: options.projectDir,
    sessionId: options.sessionId,
  });

  const tc: ToolCall = {
    toolName,
    toolInput,
    metadata: options.metadata ?? {},
    timestamp: new Date(),
  };

  let decision: PermissionDecision;
  try {
    decision = pipeline.evaluate(tc);
  } catch (e) {
    return {
      toolName,
      status: "error",
      error: `Governance evaluation failed: ${e}`,
      durationMs: 0,
      sanitized: false,
    };
  } finally {
    pipeline.close();
  }

  if (decision.action === "deny") {
    return {
      toolName,
      status: "blocked",
      blockedReason: decision.reason,
      durationMs: 0,
      sanitized: false,
    };
  }
  if (decision.action === "ask") {
    return {
      toolName,
      status: "blocked",
      blockedReason: `Requires confirmation: ${decision.reason}`,
      durationMs: 0,
      sanitized: false,
    };
  }

  return {
    toolName,
    status: "success",
    output: `Tool call '${toolName}' passed governance checks`,
    durationMs: 0,
    sanitized: false,
  };
}
