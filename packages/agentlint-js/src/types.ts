/**
 * AutoHarness Core Types
 *
 * Foundational data models for AutoHarness — an AI agent behavioral governance
 * middleware. All models use Zod for strict validation (mirroring Python's Pydantic).
 *
 * Data flow: ToolCall -> RiskAssessment -> HookResult -> PermissionDecision -> AuditRecord
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enumerations
// ---------------------------------------------------------------------------

export const RiskLevel = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
} as const;
export type RiskLevel = (typeof RiskLevel)[keyof typeof RiskLevel];

export const HookAction = {
  allow: "allow",
  deny: "deny",
  ask: "ask",
  sanitize: "sanitize",
  modify: "modify",
} as const;
export type HookAction = (typeof HookAction)[keyof typeof HookAction];

export const Enforcement = {
  prompt: "prompt",
  hook: "hook",
  both: "both",
} as const;
export type Enforcement = (typeof Enforcement)[keyof typeof Enforcement];

export const RuleSeverity = {
  info: "info",
  warning: "warning",
  error: "error",
} as const;
export type RuleSeverity = (typeof RuleSeverity)[keyof typeof RuleSeverity];

export const HookProfile = {
  minimal: "minimal",
  standard: "standard",
  strict: "strict",
} as const;
export type HookProfile = (typeof HookProfile)[keyof typeof HookProfile];

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

export const ToolCallSchema = z.object({
  toolName: z.string().min(1, "toolName must be a non-empty string"),
  toolInput: z.record(z.unknown()),
  metadata: z.record(z.unknown()).default({}),
  sessionId: z.string().nullish(),
  timestamp: z.date().default(() => new Date()),
});
export type ToolCall = z.infer<typeof ToolCallSchema>;

export const ToolResultSchema = z.object({
  toolName: z.string(),
  status: z.enum(["success", "blocked", "error"]),
  output: z.unknown().default(null),
  error: z.string().nullish(),
  durationMs: z.number().min(0).default(0),
  sanitized: z.boolean().default(false),
  blockedReason: z.string().nullish(),
});
export type ToolResult = z.infer<typeof ToolResultSchema>;

export const RiskAssessmentSchema = z.object({
  level: z.enum(["low", "medium", "high", "critical"]),
  classifier: z.enum(["rules", "llm", "hybrid"]),
  matchedRule: z.string().nullish(),
  reason: z.string().nullish(),
  confidence: z.number().min(0).max(1).optional().default(1.0),
});

/** Risk classification result for a tool call. */
export interface RiskAssessment {
  level: RiskLevel;
  classifier: "rules" | "llm" | "hybrid";
  matchedRule?: string | null;
  reason?: string | null;
  confidence?: number;
}

export const HookResultSchema = z.object({
  action: z.enum(["allow", "deny", "ask", "sanitize", "modify"]).optional().default("allow"),
  reason: z.string().nullish(),
  severity: z.enum(["info", "warning", "error"]).optional().default("info"),
  modifiedInput: z.record(z.unknown()).nullish(),
  sanitizedOutput: z.string().nullish(),
});

/** Return value from a pre- or post-hook execution. */
export interface HookResult {
  action?: HookAction;
  reason?: string | null;
  severity?: "info" | "warning" | "error";
  modifiedInput?: Record<string, unknown> | null;
  sanitizedOutput?: string | null;
}

export const PermissionDecisionSchema = z.object({
  action: z.enum(["allow", "deny", "ask"]),
  reason: z.string(),
  source: z.string(),
  riskLevel: z.enum(["low", "medium", "high", "critical"]).nullish(),
});
export type PermissionDecision = z.infer<typeof PermissionDecisionSchema>;

export const AuditRecordSchema = z.object({
  timestamp: z.date(),
  sessionId: z.string(),
  eventType: z.enum([
    "tool_call",
    "tool_blocked",
    "tool_error",
    "hook_fired",
    "permission_check",
  ]),
  toolName: z.string(),
  toolInputHash: z.string().regex(/^[0-9a-f]{64}$/, "Must be a 64-char hex SHA-256 digest"),
  risk: RiskAssessmentSchema.nullish(),
  hooksPre: z.array(z.record(z.unknown())).default([]),
  hooksPost: z.array(z.record(z.unknown())).default([]),
  permission: PermissionDecisionSchema,
  execution: z.record(z.unknown()).optional(),
});

/** Complete audit trail entry for a single governed tool call. */
export interface AuditRecord {
  timestamp: Date;
  sessionId: string;
  eventType: "tool_call" | "tool_blocked" | "tool_error" | "hook_fired" | "permission_check";
  toolName: string;
  toolInputHash: string;
  risk?: RiskAssessment | null;
  hooksPre?: Array<Record<string, unknown>>;
  hooksPost?: Array<Record<string, unknown>>;
  permission: PermissionDecision;
  execution?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Constitution configuration models
// ---------------------------------------------------------------------------

export const RuleSchema = z.object({
  id: z.string().min(1, "Rule id must be a non-empty string"),
  description: z.string(),
  severity: z.enum(["info", "warning", "error"]).default("error"),
  enforcement: z.enum(["prompt", "hook", "both"]).default("both"),
  patterns: z.array(z.record(z.unknown())).default([]),
  triggers: z.array(z.record(z.unknown())).default([]),
  checks: z.array(z.string()).default([]),
});
export type Rule = z.infer<typeof RuleSchema>;

export const ToolPermissionSchema = z.object({
  policy: z.enum(["allow", "restricted", "deny"]),
  denyPatterns: z.array(z.string()).default([]),
  askPatterns: z.array(z.string()).default([]),
  allowPatterns: z.array(z.string()).default([]),
  denyPaths: z.array(z.string()).default([]),
  askPaths: z.array(z.string()).default([]),
  allowPaths: z.array(z.string()).default([]),
  scope: z.string().nullish(),
  allowDomains: z.array(z.string()).default([]),
});
export type ToolPermission = z.infer<typeof ToolPermissionSchema>;

export const PermissionDefaultsSchema = z.object({
  unknownTool: z.enum(["allow", "ask", "deny"]).default("ask"),
  unknownPath: z.enum(["allow", "ask", "deny"]).default("deny"),
  onError: z.enum(["allow", "ask", "deny"]).default("deny"),
});
export type PermissionDefaults = z.infer<typeof PermissionDefaultsSchema>;

const VALID_THRESHOLD_ACTIONS = ["allow", "ask", "deny", "flag"] as const;

export const ConstitutionConfigSchema = z.object({
  version: z.string().default("1.0"),
  identity: z
    .record(z.unknown())
    .default(() => ({
      name: "autoharness",
      description: "AI agent behavioral governance middleware",
      boundaries: [],
    })),
  rules: z.array(RuleSchema).default([]),
  permissions: z
    .record(z.unknown())
    .default(() => ({
      defaults: { unknownTool: "ask", unknownPath: "deny", onError: "deny" },
      tools: {},
    })),
  risk: z
    .record(z.unknown())
    .default(() => ({
      classifier: "rules",
      thresholds: { low: "allow", medium: "ask", high: "deny", critical: "deny" },
      customRules: [],
    })),
  hooks: z
    .record(z.unknown())
    .default(() => ({
      profile: "standard",
      pre: [],
      post: [],
    })),
  audit: z
    .record(z.unknown())
    .default(() => ({
      enabled: true,
      format: "jsonl",
      output: "./audit.jsonl",
      retentionDays: 90,
      include: ["tool_call", "tool_blocked", "tool_error", "hook_fired", "permission_check"],
    })),
});
export type ConstitutionConfig = z.infer<typeof ConstitutionConfigSchema>;

// ---------------------------------------------------------------------------
// Risk pattern type (used by builtin rules)
// ---------------------------------------------------------------------------

export interface RiskPattern {
  pattern: string;
  description: string;
  category: string;
}

// ---------------------------------------------------------------------------
// Helper: hash tool input
// ---------------------------------------------------------------------------

export async function hashToolInput(toolInput: Record<string, unknown>): Promise<string> {
  const canonical = JSON.stringify(toolInput, Object.keys(toolInput).sort());
  const encoder = new TextEncoder();
  const data = encoder.encode(canonical);

  // Use Node.js crypto if available, otherwise Web Crypto
  if (typeof globalThis.crypto?.subtle !== "undefined") {
    const hashBuffer = await globalThis.crypto.subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(hashBuffer))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  // Fallback: Node.js crypto module
  const { createHash } = await import("node:crypto");
  return createHash("sha256").update(canonical).digest("hex");
}

/** Synchronous hash using Node.js crypto (preferred in Node environment). */
export function hashToolInputSync(toolInput: Record<string, unknown>): string {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { createHash } = require("node:crypto") as typeof import("node:crypto");
  const canonical = JSON.stringify(toolInput, Object.keys(toolInput).sort());
  return createHash("sha256").update(canonical).digest("hex");
}
