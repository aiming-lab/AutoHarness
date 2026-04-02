/**
 * Constitution Engine — loads, validates, merges, and provides access to governance config.
 *
 * The Constitution is the central configuration object for AutoHarness. It defines:
 * - Identity metadata
 * - Governance rules
 * - Tool permissions
 * - Risk assessment configuration
 * - Hook profiles
 * - Audit settings
 *
 * A constitution can be loaded from YAML files, dicts, or YAML strings.
 * Multiple constitutions can be merged (project + user + defaults).
 */

import * as fs from "node:fs";
import * as yaml from "js-yaml";
import {
  ConstitutionConfigSchema,
  type ConstitutionConfig,
  type Rule,
  type ToolPermission,
} from "./types.js";

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

export class ConstitutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConstitutionError";
  }
}

// ---------------------------------------------------------------------------
// Constitution
// ---------------------------------------------------------------------------

export class Constitution {
  private readonly _config: ConstitutionConfig;

  constructor(config: ConstitutionConfig) {
    this._config = config;
  }

  // ------------------------------------------------------------------
  // Factory methods
  // ------------------------------------------------------------------

  /** Load a constitution from a YAML file on disk. */
  static load(filePath: string): Constitution {
    if (!fs.existsSync(filePath)) {
      throw new Error(`Constitution file not found: ${filePath}`);
    }

    let raw: string;
    try {
      raw = fs.readFileSync(filePath, "utf-8");
    } catch (e) {
      throw new ConstitutionError(`Cannot read constitution file ${filePath}: ${e}`);
    }

    return Constitution.fromYaml(raw);
  }

  /** Load a constitution from a YAML string. */
  static fromYaml(yamlStr: string): Constitution {
    let data: unknown;
    try {
      data = yaml.load(yamlStr);
    } catch (e) {
      throw new ConstitutionError(`Invalid YAML in constitution: ${e}`);
    }

    if (data == null) data = {};

    if (typeof data !== "object" || Array.isArray(data)) {
      throw new ConstitutionError(
        `Constitution YAML must be a mapping, got ${typeof data}`,
      );
    }

    return Constitution.fromDict(data as Record<string, unknown>);
  }

  /** Load a constitution from a plain object. */
  static fromDict(data: Record<string, unknown>): Constitution {
    const result = ConstitutionConfigSchema.safeParse(data);
    if (!result.success) {
      throw new ConstitutionError(
        `Constitution validation failed:\n${result.error.message}`,
      );
    }
    return new Constitution(result.data);
  }

  /** Create a sensible zero-config default constitution. */
  static default(): Constitution {
    const defaultRules: Rule[] = [
      {
        id: "no-over-engineering",
        description: "Prefer simple, minimal solutions over complex abstractions",
        severity: "warning",
        enforcement: "prompt",
        patterns: [],
        triggers: [],
        checks: [],
      },
      {
        id: "confirm-destructive-ops",
        description:
          "Destructive operations (delete, drop, reset --hard, push --force) must be confirmed before execution",
        severity: "error",
        enforcement: "hook",
        patterns: [],
        triggers: [],
        checks: [],
      },
      {
        id: "no-config-weakening",
        description:
          "Do not disable safety features, skip hooks, or weaken security settings (e.g., --no-verify, --insecure, disable_ssl)",
        severity: "error",
        enforcement: "hook",
        patterns: [],
        triggers: [],
        checks: [],
      },
      {
        id: "no-secret-exposure",
        description: "Never commit, log, or transmit secrets, API keys, or credentials",
        severity: "error",
        enforcement: "hook",
        patterns: [],
        triggers: [],
        checks: [],
      },
      {
        id: "sensitive-path-guard",
        description: "Warn before reading or modifying sensitive paths",
        severity: "warning",
        enforcement: "prompt",
        patterns: [],
        triggers: [],
        checks: [],
      },
    ];

    const permissions = {
      defaults: { unknownTool: "ask", unknownPath: "deny", onError: "deny" },
      tools: {
        bash: {
          policy: "restricted",
          denyPatterns: [
            String.raw`rm\s+-rf\s+/`,
            String.raw`rm\s+-rf\s+~`,
            String.raw`rm\s+-rf\s+\$HOME`,
            String.raw`mkfs\.`,
            String.raw`dd\s+if=.*of=/dev/`,
            String.raw`:\(\)\s*\{\s*:\|:\s*&\s*\}\s*;`,
            String.raw`chmod\s+-R\s+777\s+/`,
            String.raw`curl\s+.*\|\s*(ba)?sh`,
            String.raw`wget\s+.*\|\s*(ba)?sh`,
            String.raw`git\s+push\s+.*--force\s+.*main`,
            String.raw`git\s+push\s+.*--force\s+.*master`,
            String.raw`git\s+reset\s+--hard`,
          ],
          denyPaths: [],
          askPatterns: [],
          allowPatterns: [],
          askPaths: [],
          allowPaths: [],
          allowDomains: [],
        },
        file_write: {
          policy: "restricted",
          denyPatterns: [
            String.raw`\.env$`,
            String.raw`\.env\.`,
            String.raw`\.ssh/`,
            String.raw`credentials\.json`,
            String.raw`\.aws/credentials`,
            String.raw`\.netrc`,
            String.raw`id_rsa`,
            String.raw`\.pem$`,
          ],
          denyPaths: [],
          askPatterns: [],
          allowPatterns: [],
          askPaths: [],
          allowPaths: [],
          allowDomains: [],
        },
      },
    };

    const config: ConstitutionConfig = {
      version: "1.0",
      identity: {
        name: "autoharness-default",
        description: "Default AutoHarness constitution with essential safety rules",
        boundaries: [],
      },
      rules: defaultRules,
      permissions,
      risk: {
        classifier: "rules",
        thresholds: { low: "allow", medium: "ask", high: "deny", critical: "deny" },
        customRules: [],
      },
      hooks: { profile: "standard", pre: [], post: [] },
      audit: {
        enabled: true,
        format: "jsonl",
        output: "./audit.jsonl",
        retentionDays: 90,
        include: [
          "tool_call",
          "tool_blocked",
          "tool_error",
          "hook_fired",
          "permission_check",
        ],
      },
    };

    return new Constitution(config);
  }

  // ------------------------------------------------------------------
  // Merging
  // ------------------------------------------------------------------

  /** Deep-merge two constitutions, with override taking priority. */
  static merge(base: Constitution, override: Constitution): Constitution {
    const baseDict = structuredClone(base._config);
    const overDict = structuredClone(override._config);

    const merged = deepMergeDicts(
      baseDict as unknown as Record<string, unknown>,
      overDict as unknown as Record<string, unknown>,
    );

    // Special: merge rules by id
    if (Array.isArray(baseDict.rules) && Array.isArray(overDict.rules)) {
      (merged as Record<string, unknown>)["rules"] = mergeByKey(
        baseDict.rules as Record<string, unknown>[],
        overDict.rules as Record<string, unknown>[],
        "id",
      );
    }

    const result = ConstitutionConfigSchema.safeParse(merged);
    if (!result.success) {
      throw new ConstitutionError(`Merged constitution is invalid: ${result.error.message}`);
    }
    return new Constitution(result.data);
  }

  // ------------------------------------------------------------------
  // Properties
  // ------------------------------------------------------------------

  get config(): ConstitutionConfig {
    return this._config;
  }

  get rules(): Rule[] {
    return this._config.rules;
  }

  get permissions(): Record<string, unknown> {
    return this._config.permissions;
  }

  get riskConfig(): Record<string, unknown> {
    return this._config.risk;
  }

  get hookConfig(): Record<string, unknown> {
    return this._config.hooks;
  }

  get auditConfig(): Record<string, unknown> {
    return this._config.audit;
  }

  get identity(): Record<string, unknown> {
    return this._config.identity;
  }

  // ------------------------------------------------------------------
  // Query methods
  // ------------------------------------------------------------------

  /** Return all rules matching the given enforcement type. */
  getRulesForEnforcement(enforcement: string): Rule[] {
    return this._config.rules.filter((r) => r.enforcement === enforcement);
  }

  /** Get the permission config for a specific tool. */
  getToolPermission(toolName: string): ToolPermission | null {
    const tools = (this._config.permissions as Record<string, unknown>)["tools"];
    if (!tools || typeof tools !== "object") return null;
    const raw = (tools as Record<string, unknown>)[toolName];
    if (!raw) return null;
    return raw as ToolPermission;
  }

  /** Run validation checks and return a list of warnings. */
  validate(): string[] {
    const issues: string[] = [];

    // Check for duplicate rule IDs
    const seenIds = new Map<string, number>();
    for (const rule of this._config.rules) {
      seenIds.set(rule.id, (seenIds.get(rule.id) ?? 0) + 1);
    }
    for (const [ruleId, count] of seenIds) {
      if (count > 1) {
        issues.push(`Duplicate rule ID '${ruleId}' appears ${count} times`);
      }
    }

    // Check for rules without descriptions
    for (const rule of this._config.rules) {
      if (!rule.description) {
        issues.push(`Rule '${rule.id}' has no description`);
      }
    }

    // Check identity
    const name = (this._config.identity as Record<string, unknown>)["name"];
    if (!name) {
      issues.push("Constitution has no identity name");
    }

    return issues;
  }
}

// ---------------------------------------------------------------------------
// Merge helpers
// ---------------------------------------------------------------------------

function deepMergeDicts(
  base: Record<string, unknown>,
  override: Record<string, unknown>,
): Record<string, unknown> {
  const result = structuredClone(base);
  for (const [key, value] of Object.entries(override)) {
    if (
      key in result &&
      typeof result[key] === "object" &&
      result[key] !== null &&
      !Array.isArray(result[key]) &&
      typeof value === "object" &&
      value !== null &&
      !Array.isArray(value)
    ) {
      result[key] = deepMergeDicts(
        result[key] as Record<string, unknown>,
        value as Record<string, unknown>,
      );
    } else {
      result[key] = structuredClone(value);
    }
  }
  return result;
}

function mergeByKey(
  baseItems: Record<string, unknown>[],
  overrideItems: Record<string, unknown>[],
  key: string,
): Record<string, unknown>[] {
  const merged = new Map<string, Record<string, unknown>>();
  for (const item of baseItems) {
    const k = String(item[key] ?? "");
    merged.set(k, structuredClone(item));
  }
  for (const item of overrideItems) {
    const k = String(item[key] ?? "");
    const existing = merged.get(k);
    if (existing) {
      merged.set(k, deepMergeDicts(existing, item));
    } else {
      merged.set(k, structuredClone(item));
    }
  }
  return Array.from(merged.values());
}
