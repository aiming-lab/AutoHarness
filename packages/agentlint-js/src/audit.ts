/**
 * Audit Engine — structured JSONL logging of all governance decisions.
 *
 * Provides an append-only audit trail of every tool call that passes through
 * the AutoHarness governance pipeline: risk assessments, hook results, permission
 * decisions, and execution outcomes.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type {
  AuditRecord,
  HookResult,
  PermissionDecision,
  RiskAssessment,
  ToolCall,
  ToolResult,
} from "./types.js";
import { hashToolInputSync } from "./types.js";

// ---------------------------------------------------------------------------
// AuditEngine
// ---------------------------------------------------------------------------

export class AuditEngine {
  private readonly _outputPath: string;
  private _enabled: boolean;
  private readonly _retentionDays: number;
  private _fileHandle: number | null = null;
  private _closed = false;

  constructor(
    outputPath: string = ".autoharness/audit.jsonl",
    enabled: boolean = true,
    retentionDays: number = 30,
  ) {
    this._outputPath = outputPath;
    this._enabled = enabled;
    this._retentionDays = retentionDays;

    if (this._enabled) {
      try {
        const parent = path.dirname(outputPath);
        fs.mkdirSync(parent, { recursive: true });
        this._fileHandle = fs.openSync(outputPath, "a");
      } catch {
        this._enabled = false;
      }
    }
  }

  // ------------------------------------------------------------------
  // Public logging API
  // ------------------------------------------------------------------

  /** Log a complete tool execution cycle (call -> result). */
  log(params: {
    toolCall: ToolCall;
    risk: RiskAssessment | null;
    preHooks: HookResult[];
    permission: PermissionDecision;
    result: ToolResult | null;
    postHooks: HookResult[];
    sessionId?: string;
  }): void {
    if (!this._enabled) return;

    const record = this._buildRecord({
      ...params,
      eventType: "tool_call",
    });
    this._write(record);
  }

  /** Log a blocked tool call. */
  logBlock(params: {
    toolCall: ToolCall;
    risk: RiskAssessment | null;
    preHooks: HookResult[];
    permission: PermissionDecision;
    sessionId?: string;
  }): void {
    if (!this._enabled) return;

    const record = this._buildRecord({
      ...params,
      result: null,
      postHooks: [],
      eventType: "tool_blocked",
    });
    this._write(record);
  }

  /** Log an error during governance or execution. */
  logError(
    toolCall: ToolCall,
    error: string | Error,
    sessionId?: string,
  ): void {
    if (!this._enabled) return;

    const errorStr = typeof error === "string" ? error : error.message;
    const now = new Date();
    const sid = sessionId ?? toolCall.sessionId ?? "unknown";
    const inputHash = hashToolInputSync(toolCall.toolInput as Record<string, unknown>);

    const record: AuditRecord = {
      timestamp: now,
      sessionId: sid,
      eventType: "tool_error",
      toolName: toolCall.toolName,
      toolInputHash: inputHash,
      risk: null,
      hooksPre: [],
      hooksPost: [],
      permission: {
        action: "deny",
        reason: `Error during governance: ${errorStr.slice(0, 200)}`,
        source: "error_handler",
      },
      execution: {
        status: "error",
        durationMs: 0,
        outputSize: 0,
        sanitized: false,
        error: errorStr.slice(0, 1000),
      },
    };
    this._write(record);
  }

  // ------------------------------------------------------------------
  // Record construction
  // ------------------------------------------------------------------

  private _buildRecord(params: {
    toolCall: ToolCall;
    risk: RiskAssessment | null;
    preHooks: HookResult[];
    permission: PermissionDecision;
    result: ToolResult | null;
    postHooks: HookResult[];
    sessionId?: string;
    eventType: string;
  }): AuditRecord {
    const now = new Date();
    const sid = params.sessionId ?? params.toolCall.sessionId ?? "unknown";
    const inputHash = hashToolInputSync(params.toolCall.toolInput as Record<string, unknown>);

    const preSummaries = params.preHooks.map((hr) => ({
      action: hr.action,
      reason: hr.reason,
      severity: hr.severity,
    }));

    const postSummaries = params.postHooks.map((hr) => ({
      action: hr.action,
      reason: hr.reason,
      severity: hr.severity,
      sanitized: hr.sanitizedOutput != null,
    }));

    let execution: Record<string, unknown>;
    if (params.result) {
      const outputText = params.result.output != null ? String(params.result.output) : "";
      execution = {
        status: params.result.status,
        durationMs: params.result.durationMs,
        outputSize: outputText.length,
        sanitized: params.result.sanitized,
      };
      if (params.result.error) {
        execution["error"] = params.result.error.slice(0, 1000);
      }
    } else {
      execution = {
        status: params.eventType === "tool_blocked" ? "blocked" : "pending",
        durationMs: 0,
        outputSize: 0,
        sanitized: false,
      };
    }

    return {
      timestamp: now,
      sessionId: sid,
      eventType: params.eventType as AuditRecord["eventType"],
      toolName: params.toolCall.toolName,
      toolInputHash: inputHash,
      risk: params.risk,
      hooksPre: preSummaries,
      hooksPost: postSummaries,
      permission: params.permission,
      execution,
    };
  }

  // ------------------------------------------------------------------
  // Writing
  // ------------------------------------------------------------------

  private _write(record: AuditRecord): void {
    if (!this._enabled || this._fileHandle == null || this._closed) return;

    // Serialize record to JSON line
    const serialized = JSON.stringify(record, (_key, value) => {
      if (value instanceof Date) return value.toISOString();
      return value;
    });

    try {
      fs.writeSync(this._fileHandle, serialized + "\n");
    } catch {
      // Swallow write errors
    }
  }

  // ------------------------------------------------------------------
  // Query and reporting
  // ------------------------------------------------------------------

  /** Get summary statistics from the audit log. */
  getSummary(sessionId?: string): Record<string, unknown> {
    const records = this._readRecords(sessionId);

    let blocked = 0;
    let errors = 0;
    const riskDist: Record<string, number> = {};
    const blockedReasons: Record<string, number> = {};
    const toolsUsed: Record<string, number> = {};

    for (const rec of records) {
      toolsUsed[rec.toolName] = (toolsUsed[rec.toolName] ?? 0) + 1;

      if (rec.eventType === "tool_blocked") {
        blocked++;
        const reason = rec.permission.reason;
        blockedReasons[reason] = (blockedReasons[reason] ?? 0) + 1;
      } else if (rec.eventType === "tool_error") {
        errors++;
      }

      if (rec.risk) {
        riskDist[rec.risk.level] = (riskDist[rec.risk.level] ?? 0) + 1;
      } else {
        riskDist["unassessed"] = (riskDist["unassessed"] ?? 0) + 1;
      }
    }

    return {
      totalCalls: records.length,
      blockedCount: blocked,
      errorCount: errors,
      riskDistribution: riskDist,
      topBlockedReasons: blockedReasons,
      toolsUsed,
    };
  }

  private _readRecords(sessionId?: string): AuditRecord[] {
    if (!fs.existsSync(this._outputPath)) return [];

    const records: AuditRecord[] = [];
    try {
      const content = fs.readFileSync(this._outputPath, "utf-8");
      for (const line of content.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const parsed = JSON.parse(trimmed);
          if (sessionId && parsed.sessionId !== sessionId) continue;
          records.push(parsed as AuditRecord);
        } catch {
          // Skip malformed lines
        }
      }
    } catch {
      // Failed to read
    }
    return records;
  }

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------

  /** Flush and close the audit file. */
  close(): void {
    if (this._fileHandle != null && !this._closed) {
      try {
        fs.closeSync(this._fileHandle);
      } catch {
        // Ignore
      } finally {
        this._closed = true;
        this._fileHandle = null;
      }
    }
  }

  get enabled(): boolean {
    return this._enabled;
  }

  get outputPath(): string {
    return this._outputPath;
  }
}
