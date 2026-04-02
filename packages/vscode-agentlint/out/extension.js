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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
const auditTreeProvider_1 = require("./auditTreeProvider");
const dashboardPanel_1 = require("./dashboardPanel");
const constitutionValidator_1 = require("./constitutionValidator");
let treeProvider;
let constitutionValidator;
function activate(context) {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
    // Resolve audit log path
    const config = vscode.workspace.getConfiguration('harnessagent');
    const auditLogRelative = config.get('auditLogPath', 'audit.jsonl');
    const auditLogPath = path.isAbsolute(auditLogRelative)
        ? auditLogRelative
        : path.join(workspaceRoot, auditLogRelative);
    // --- Tree view ---
    treeProvider = new auditTreeProvider_1.AuditTreeProvider(auditLogPath);
    const treeView = vscode.window.createTreeView('harnessagent.auditTree', {
        treeDataProvider: treeProvider,
        showCollapseAll: true,
    });
    context.subscriptions.push(treeView);
    context.subscriptions.push({ dispose: () => treeProvider?.dispose() });
    // --- Constitution validator ---
    constitutionValidator = new constitutionValidator_1.ConstitutionValidator();
    context.subscriptions.push(constitutionValidator);
    // --- Commands ---
    context.subscriptions.push(vscode.commands.registerCommand('harnessagent.showDashboard', () => {
        dashboardPanel_1.DashboardPanel.createOrShow(context.extensionUri, () => treeProvider?.getRecords() || []);
    }));
    context.subscriptions.push(vscode.commands.registerCommand('harnessagent.showAuditLog', () => {
        if (fs.existsSync(auditLogPath)) {
            vscode.workspace.openTextDocument(auditLogPath).then((doc) => {
                vscode.window.showTextDocument(doc);
            });
        }
        else {
            vscode.window.showWarningMessage(`Audit log not found: ${auditLogPath}`);
        }
    }));
    context.subscriptions.push(vscode.commands.registerCommand('harnessagent.validateConstitution', () => {
        constitutionValidator?.validate();
    }));
    context.subscriptions.push(vscode.commands.registerCommand('harnessagent.initConstitution', async () => {
        const constitutionRelative = config.get('constitutionPath', 'constitution.yaml');
        const constitutionPath = path.isAbsolute(constitutionRelative)
            ? constitutionRelative
            : path.join(workspaceRoot, constitutionRelative);
        if (fs.existsSync(constitutionPath)) {
            const doc = await vscode.workspace.openTextDocument(constitutionPath);
            await vscode.window.showTextDocument(doc);
            return;
        }
        const template = [
            '# HarnessAgent Constitution',
            '# Defines governance rules for AI agent tool usage.',
            '#',
            '# Documentation: https://github.com/Jiaaqiliu/HarnessAgent',
            '',
            'rules:',
            '  - name: block-destructive-commands',
            '    description: Prevent destructive shell commands',
            '    tool: bash',
            '    match: "rm -rf /"',
            '    action: deny',
            '    risk: critical',
            '',
            '  - name: block-secret-leak',
            '    description: Prevent secrets in tool inputs',
            '    match: "sk-ant-|sk-proj-|AKIA[A-Z0-9]"',
            '    action: deny',
            '    risk: critical',
            '',
            '  - name: warn-force-push',
            '    description: Flag force-push attempts',
            '    tool: bash',
            '    match: "git push --force"',
            '    action: ask',
            '    risk: high',
            '',
        ].join('\n');
        fs.mkdirSync(path.dirname(constitutionPath), { recursive: true });
        fs.writeFileSync(constitutionPath, template, 'utf-8');
        const doc = await vscode.workspace.openTextDocument(constitutionPath);
        await vscode.window.showTextDocument(doc);
        vscode.window.showInformationMessage('Created constitution.yaml');
    }));
    // Internal command for record detail view
    context.subscriptions.push(vscode.commands.registerCommand('harnessagent.showRecordDetail', (record) => {
        (0, auditTreeProvider_1.showRecordDetail)(record);
    }));
    // --- Config change listener ---
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('harnessagent.auditLogPath')) {
            const newRelative = vscode.workspace
                .getConfiguration('harnessagent')
                .get('auditLogPath', 'audit.jsonl');
            const newPath = path.isAbsolute(newRelative)
                ? newRelative
                : path.join(workspaceRoot, newRelative);
            treeProvider?.updatePath(newPath);
        }
    }));
}
function deactivate() {
    treeProvider?.dispose();
    constitutionValidator?.dispose();
}
//# sourceMappingURL=extension.js.map