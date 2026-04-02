import * as vscode from 'vscode';
import { AuditRecord } from './utils';
export declare class DashboardPanel {
    private getRecords;
    static currentPanel: DashboardPanel | undefined;
    private static readonly viewType;
    private readonly panel;
    private refreshTimer;
    private disposables;
    private constructor();
    static createOrShow(extensionUri: vscode.Uri, getRecords: () => AuditRecord[]): void;
    private update;
    private getHtml;
    private dispose;
}
//# sourceMappingURL=dashboardPanel.d.ts.map