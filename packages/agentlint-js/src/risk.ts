/**
 * Risk Classifier engine for AutoHarness.
 *
 * Classifies tool calls by risk level using regex pattern matching against
 * built-in and custom rule sets. Designed for sub-5ms latency in rules mode.
 *
 * Modes:
 *   - "rules"  : Pure regex matching. Fast (<5ms). Default.
 *   - "llm"    : LLM-based classification (Phase 2 placeholder).
 *   - "hybrid" : Rules first, LLM for ambiguous cases (Phase 2 placeholder).
 */

import type { RiskAssessment, RiskLevel, ToolCall } from "./types.js";
import { BUILTIN_RULES, SAFE_COMMAND_PREFIXES } from "./rules/builtin.js";

// ---------------------------------------------------------------------------
// Internal compiled rule
// ---------------------------------------------------------------------------

interface CompiledRule {
  regex: RegExp;
  description: string;
  category: string;
  level: RiskLevel;
}

const LEVEL_ORDER: Record<RiskLevel, number> = {
  low: 0,
  medium: 1,
  high: 2,
  critical: 3,
};

const VALID_MODES = new Set(["rules", "llm", "hybrid"]);

// ---------------------------------------------------------------------------
// Tool name -> category mapping
// ---------------------------------------------------------------------------

const TOOL_CATEGORY_MAP: Record<string, string> = {
  bash: "bash",
  shell: "bash",
  terminal: "bash",
  write: "file_write",
  file_write: "file_write",
  edit: "file_write",
  read: "file_read",
  file_read: "file_read",
};

// ---------------------------------------------------------------------------
// RiskClassifier
// ---------------------------------------------------------------------------

export class RiskClassifier {
  private readonly _mode: string;
  private readonly _rules: Map<string, CompiledRule[]> = new Map();
  private readonly _safePrefixes: ReadonlySet<string>;

  /**
   * @param customRules Optional list of custom rule objects with keys: pattern, level, reason, tool.
   * @param mode Classification strategy — "rules", "llm", or "hybrid".
   */
  constructor(
    customRules?: Array<{
      pattern: string;
      level: string;
      reason?: string;
      tool?: string;
    }> | null,
    mode: string = "rules",
  ) {
    if (!VALID_MODES.has(mode)) {
      throw new Error(`Invalid mode '${mode}'; expected 'rules', 'llm', or 'hybrid'`);
    }
    this._mode = mode;
    this._compileBuiltinRules();

    if (customRules) {
      for (const rule of customRules) {
        this.addCustomRule(
          rule.pattern,
          rule.level,
          rule.reason ?? "",
          rule.tool ?? "*",
        );
      }
    }

    this._safePrefixes = SAFE_COMMAND_PREFIXES;
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  /** Classify a tool call and return its risk assessment. */
  classify(toolCall: ToolCall): RiskAssessment {
    const category = this._toolToCategory(toolCall.toolName);
    const text = this._extractScannableText(toolCall, category);

    // Fast path: safe command prefix
    if (category === "bash" && this._isSafeCommand(text)) {
      return {
        level: "low",
        classifier: "rules",
        reason: "Matches known-safe command prefix",
      };
    }

    // Match against category rules + wildcard
    const matches = this._matchRules(category, text);

    // Also scan all string values for secrets
    const allText = Object.values(toolCall.toolInput)
      .filter((v): v is string => typeof v === "string")
      .join("\n");

    if (allText) {
      matches.push(...this._matchRules("secrets_in_content", allText));
    }

    if (matches.length === 0) {
      return {
        level: "low",
        classifier: "rules",
        reason: "No risk patterns matched",
      };
    }

    // Return the highest severity match
    matches.sort((a, b) => LEVEL_ORDER[b.level] - LEVEL_ORDER[a.level]);
    const highest = matches[0]!;

    return {
      level: highest.level,
      classifier: "rules",
      matchedRule: highest.description,
      reason: highest.description,
    };
  }

  /** Scan arbitrary text for secrets and sensitive data. */
  classifyContent(content: string): RiskAssessment {
    if (!content) {
      return { level: "low", classifier: "rules", reason: "Empty content" };
    }

    const matches = this._matchRules("secrets_in_content", content);
    if (matches.length === 0) {
      return { level: "low", classifier: "rules", reason: "No secrets detected" };
    }

    matches.sort((a, b) => LEVEL_ORDER[b.level] - LEVEL_ORDER[a.level]);
    const highest = matches[0]!;

    return {
      level: highest.level,
      classifier: "rules",
      matchedRule: highest.description,
      reason: highest.description,
    };
  }

  /** Add a custom risk rule at runtime. */
  addCustomRule(
    pattern: string,
    level: string,
    reason: string,
    tool: string = "*",
  ): void {
    const riskLevel = level.toLowerCase() as RiskLevel;
    if (!(riskLevel in LEVEL_ORDER)) {
      throw new Error(
        `Invalid risk level '${level}'; expected one of: low, medium, high, critical`,
      );
    }

    let regex: RegExp;
    try {
      regex = new RegExp(pattern, "im");
    } catch (e) {
      throw new Error(`Invalid regex pattern '${pattern}': ${e}`);
    }

    const rule: CompiledRule = { regex, description: reason, category: tool, level: riskLevel };
    const existing = this._rules.get(tool);
    if (existing) {
      existing.push(rule);
    } else {
      this._rules.set(tool, [rule]);
    }
  }

  /** Return the set of known-safe command prefixes. */
  getSafeCommands(): Set<string> {
    return new Set(this._safePrefixes);
  }

  // ------------------------------------------------------------------
  // Internals
  // ------------------------------------------------------------------

  private _compileBuiltinRules(): void {
    for (const [category, levels] of Object.entries(BUILTIN_RULES)) {
      const compiled: CompiledRule[] = [];
      for (const [levelStr, patterns] of Object.entries(levels)) {
        if (!patterns) continue;
        const riskLevel = levelStr as RiskLevel;
        for (const rp of patterns) {
          try {
            const flags = category === "secrets_in_content" ? "im" : "m";
            const regex = new RegExp(rp.pattern, flags);
            compiled.push({
              regex,
              description: rp.description,
              category,
              level: riskLevel,
            });
          } catch {
            // Skip malformed patterns
          }
        }
      }
      this._rules.set(category, compiled);
    }
  }

  private _toolToCategory(tool: string): string {
    const normalized = tool.toLowerCase().trim();
    return TOOL_CATEGORY_MAP[normalized] ?? normalized;
  }

  private _extractScannableText(toolCall: ToolCall, category: string): string {
    const input = toolCall.toolInput;
    if (category === "bash") {
      return (input["command"] as string) ?? "";
    }
    if (category === "file_write" || category === "file_read") {
      return (input["file_path"] as string) ?? (input["path"] as string) ?? "";
    }
    return (input["command"] as string) ?? "";
  }

  private _matchRules(category: string, text: string): CompiledRule[] {
    if (!text) return [];

    const matches: CompiledRule[] = [];

    // Category-specific rules
    const categoryRules = this._rules.get(category);
    if (categoryRules) {
      for (const rule of categoryRules) {
        if (rule.regex.test(text)) {
          matches.push(rule);
        }
        // Reset lastIndex for stateful regexes
        rule.regex.lastIndex = 0;
      }
    }

    // Wildcard rules (custom rules with tool="*")
    const wildcardRules = this._rules.get("*");
    if (wildcardRules) {
      for (const rule of wildcardRules) {
        if (rule.regex.test(text)) {
          matches.push(rule);
        }
        rule.regex.lastIndex = 0;
      }
    }

    return matches;
  }

  private _isSafeCommand(command: string): boolean {
    const stripped = command.trim();
    for (const prefix of this._safePrefixes) {
      if (stripped.startsWith(prefix)) return true;
    }
    return false;
  }
}
