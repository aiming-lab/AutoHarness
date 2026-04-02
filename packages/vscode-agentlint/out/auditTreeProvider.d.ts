import * as vscode from 'vscode';
import { AuditRecord } from './utils';
type TreeItem = SessionItem | RecordItem;
declare class SessionItem extends vscode.TreeItem {
    readonly sessionId: string;
    readonly records: AuditRecord[];
    constructor(sessionId: string, records: AuditRecord[]);
}
declare class RecordItem extends vscode.TreeItem {
    readonly record: AuditRecord;
    constructor(record: AuditRecord);
}
export declare class AuditTreeProvider implements vscode.TreeDataProvider<TreeItem> {
    private auditLogPath;
    private _onDidChangeTreeData;
    readonly onDidChangeTreeData: vscode.Event<void | TreeItem | undefined>;
    private records;
    private watcher;
    constructor(auditLogPath: string);
    private watchFile;
    reload(): void;
    refresh(): void;
    updatePath(newPath: string): void;
    getRecords(): AuditRecord[];
    getTreeItem(element: TreeItem): vscode.TreeItem;
    getChildren(element?: TreeItem): TreeItem[];
    dispose(): void;
}
/** Show a full detail view for a single record in an editor tab. */
export declare function showRecordDetail(record: AuditRecord): void;
export {};
//# sourceMappingURL=auditTreeProvider.d.ts.map