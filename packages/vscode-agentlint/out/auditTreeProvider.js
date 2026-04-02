"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.AuditTreeProvider = void 0;
exports.showRecordDetail = showRecordDetail;
const vscode = __importStar(require("vscode"));
const fs = __importStar(require("fs"));
const utils_1 = require("./utils");
class SessionItem extends vscode.TreeItem {
    sessionId;
    records;
    constructor(sessionId, records) {
        const blocked = records.filter((r) => r.event_type === 'tool_blocked').length;
        const label = `Session ${sessionId}`;
        super(label, vscode.TreeItemCollapsibleState.Collapsed);
        this.sessionId = sessionId;
        this.records = records;
        this.description = `${records.length} calls, ${blocked} blocked`;
        this.tooltip = `Session: ${sessionId}\nFirst: ${records[0]?.timestamp}\nLast: ${records[records.length - 1]?.timestamp}`;
        this.iconPath = new vscode.ThemeIcon(blocked > 0 ? 'shield' : 'pass', blocked > 0 ? new vscode.ThemeColor('charts.orange') : new vscode.ThemeColor('charts.green'));
        this.contextValue = 'session';
    }
}
class RecordItem extends vscode.TreeItem {
    record;
    constructor(record) {
        const isBlocked = record.event_type === 'tool_blocked';
        const label = record.tool_name;
        super(label, vscode.TreeItemCollapsibleState.None);
        this.record = record;
        this.description = `${record.risk.level} — ${(0, utils_1.formatTimestamp)(record.timestamp)}`;
        this.tooltip = new vscode.MarkdownString([
            `**Tool**: ${record.tool_name}`,
            `**Event**: ${record.event_type}`,
            `**Risk**: ${record.risk.level} (${record.risk.confidence})`,
            `**Rule**: ${record.risk.matched_rule || 'none'}`,
            `**Reason**: ${record.permission.reason}`,
            `**Status**: ${record.execution.status}`,
        ].join('\n\n'));
        this.iconPath = new vscode.ThemeIcon(isBlocked ? 'error' : 'pass', new vscode.ThemeColor(isBlocked ? 'charts.red' : 'charts.green'));
        this.command = {
            command: 'harnessagent.showRecordDetail',
            title: 'Show Record Detail',
            arguments: [record],
        };
        this.contextValue = 'record';
    }
}
class AuditTreeProvider {
    auditLogPath;
    _onDidChangeTreeData = new vscode.EventEmitter();
    onDidChangeTreeData = this._onDidChangeTreeData.event;
    records = [];
    watcher = null;
    constructor(auditLogPath) {
        this.auditLogPath = auditLogPath;
        this.reload();
        this.watchFile();
    }
    watchFile() {
        if (!fs.existsSync(this.auditLogPath)) {
            return;
        }
        try {
            this.watcher = fs.watch(this.auditLogPath, () => {
                this.reload();
                this._onDidChangeTreeData.fire();
            });
        }
        catch {
            // File may not exist yet — that's fine
        }
    }
    reload() {
        this.records = (0, utils_1.parseJsonl)(this.auditLogPath);
    }
    refresh() {
        this.reload();
        this._onDidChangeTreeData.fire();
    }
    updatePath(newPath) {
        this.watcher?.close();
        this.auditLogPath = newPath;
        this.reload();
        this.watchFile();
        this._onDidChangeTreeData.fire();
    }
    getRecords() {
        return this.records;
    }
    getTreeItem(element) {
        return element;
    }
    getChildren(element) {
        if (!element) {
            // Root: show sessions
            const sessions = (0, utils_1.groupBySession)(this.records);
            const items = [];
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
    dispose() {
        this.watcher?.close();
        this._onDidChangeTreeData.dispose();
    }
}
exports.AuditTreeProvider = AuditTreeProvider;
/** Show a full detail view for a single record in an editor tab. */
function showRecordDetail(record) {
    const doc = [
        `HarnessAgent Audit Record`,
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
        ...record.hooks_pre.map((h, i) => `  [${i + 1}] ${h.action} | ${h.severity} | ${h.reason || '(no reason)'}`),
        ``,
        `--- Post-Hooks (${record.hooks_post.length}) ---`,
        ...record.hooks_post.map((h, i) => `  [${i + 1}] ${h.action} | ${h.severity} | sanitized=${h.sanitized ?? false} | ${h.reason || '(no reason)'}`),
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
//# sourceMappingURL=auditTreeProvider.js.map