import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { AuditRecord, parseJsonl, formatTimestamp, groupBySession, riskCssColor } from './utils';

type TreeItem = SessionItem | RecordItem;

class SessionItem extends vscode.TreeItem {
  constructor(
    public readonly sessionId: string,
    public readonly records: AuditRecord[],
  ) {
    const blocked = records.filter((r) => r.event_type === 'tool_blocked').length;
    const label = `Session ${sessionId}`;
    super(label, vscode.TreeItemCollapsibleState.Collapsed);
    this.description = `${records.length} calls, ${blocked} blocked`;
    this.tooltip = `Session: ${sessionId}\nFirst: ${records[0]?.timestamp}\nLast: ${records[records.length - 1]?.timestamp}`;
    this.iconPath = new vscode.ThemeIcon(
      blocked > 0 ? 'shield' : 'pass',
      blocked > 0 ? new vscode.ThemeColor('charts.orange') : new vscode.ThemeColor('charts.green'),
    );
    this.contextValue = 'session';
  }
}

class RecordItem extends vscode.TreeItem {
  constructor(public readonly record: AuditRecord) {
    const isBlocked = record.event_type === 'tool_blocked';
    const label = record.tool_name;
    super(label, vscode.TreeItemCollapsibleState.None);

    this.description = `${record.risk.level} — ${formatTimestamp(record.timestamp)}`;
    this.tooltip = new vscode.MarkdownString(
      [
        `**Tool**: ${record.tool_name}`,
        `**Event**: ${record.event_type}`,
        `**Risk**: ${record.risk.level} (${record.risk.confidence})`,
        `**Rule**: ${record.risk.matched_rule || 'none'}`,
        `**Reason**: ${record.permission.reason}`,
        `**Status**: ${record.execution.status}`,
      ].join('\n\n'),
    );

    this.iconPath = new vscode.ThemeIcon(
      isBlocked ? 'error' : 'pass',
      new vscode.ThemeColor(
        isBlocked ? 'charts.red' : 'charts.green',
      ),
    );

    this.command = {
      command: 'autoharness.showRecordDetail',
      title: 'Show Record Detail',
      arguments: [record],
    };
    this.contextValue = 'record';
  }
}

export class AuditTreeProvider implements vscode.TreeDataProvider<TreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<TreeItem | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private records: AuditRecord[] = [];
  private watcher: fs.FSWatcher | null = null;

  constructor(private auditLogPath: string) {
    this.reload();
    this.watchFile();
  }

  private watchFile(): void {
    if (!fs.existsSync(this.auditLogPath)) {
      return;
    }
    try {
      this.watcher = fs.watch(this.auditLogPath, () => {
        this.reload();
        this._onDidChangeTreeData.fire();
      });
    } catch {
      // File may not exist yet — that's fine
    }
  }

  reload(): void {
    this.records = parseJsonl(this.auditLogPath);
  }

  refresh(): void {
    this.reload();
    this._onDidChangeTreeData.fire();
  }

  updatePath(newPath: string): void {
    this.watcher?.close();
    this.auditLogPath = newPath;
    this.reload();
    this.watchFile();
    this._onDidChangeTreeData.fire();
  }

  getRecords(): AuditRecord[] {
    return this.records;
  }

  getTreeItem(element: TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: TreeItem): TreeItem[] {
    if (!element) {
      // Root: show sessions
      const sessions = groupBySession(this.records);
      const items: SessionItem[] = [];
      for (const [sessionId, records] of sessions) {
        items.push(new SessionItem(sessionId, records));
      }
      // Most recent session first
      items.reverse();
      return items;
    }

    if (element instanceof SessionItem) {
      return element.records.map((r) => new RecordItem(r));
    }

    return [];
  }

  dispose(): void {
    this.watcher?.close();
    this._onDidChangeTreeData.dispose();
  }
}

/** Show a full detail view for a single record in an editor tab. */
export function showRecordDetail(record: AuditRecord): void {
  const doc = [
    `AutoHarness Audit Record`,
    `${'='.repeat(50)}`,
    ``,
    `Timestamp:    ${record.timestamp}`,
    `Session:      ${record.session_id}`,
    `Event Type:   ${record.event_type}`,
    `Tool:         ${record.tool_name}`,
    `Input Hash:   ${record.tool_input_hash}`,
    ``,
    `--- Risk Assessment ---`,
    `Level:        ${record.risk.level}`,
    `Classifier:   ${record.risk.classifier}`,
    `Matched Rule: ${record.risk.matched_rule || '(none)'}`,
    `Reason:       ${record.risk.reason}`,
    `Confidence:   ${record.risk.confidence}`,
    ``,
    `--- Permission Decision ---`,
    `Action:       ${record.permission.action}`,
    `Reason:       ${record.permission.reason}`,
    `Source:       ${record.permission.source}`,
    `Risk Level:   ${record.permission.risk_level || '(none)'}`,
    ``,
    `--- Pre-Hooks (${record.hooks_pre.length}) ---`,
    ...record.hooks_pre.map(
      (h, i) => `  [${i + 1}] ${h.action} | ${h.severity} | ${h.reason || '(no reason)'}`,
    ),
    ``,
    `--- Post-Hooks (${record.hooks_post.length}) ---`,
    ...record.hooks_post.map(
      (h, i) =>
        `  [${i + 1}] ${h.action} | ${h.severity} | sanitized=${h.sanitized ?? false} | ${h.reason || '(no reason)'}`,
    ),
    ``,
    `--- Execution ---`,
    `Status:       ${record.execution.status}`,
    `Duration:     ${record.execution.duration_ms.toFixed(3)} ms`,
    `Output Size:  ${record.execution.output_size} bytes`,
    `Sanitized:    ${record.execution.sanitized}`,
  ].join('\n');

  vscode.workspace
    .openTextDocument({ content: doc, language: 'plaintext' })
    .then((d) => vscode.window.showTextDocument(d, { preview: true }));
}
