import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { AuditTreeProvider, showRecordDetail } from './auditTreeProvider';
import { DashboardPanel } from './dashboardPanel';
import { ConstitutionValidator } from './constitutionValidator';
import { AuditRecord } from './utils';

let treeProvider: AuditTreeProvider | undefined;
let constitutionValidator: ConstitutionValidator | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';

  // Resolve audit log path
  const config = vscode.workspace.getConfiguration('autoharness');
  const auditLogRelative = config.get<string>('auditLogPath', 'audit.jsonl');
  const auditLogPath = path.isAbsolute(auditLogRelative)
    ? auditLogRelative
    : path.join(workspaceRoot, auditLogRelative);

  // --- Tree view ---
  treeProvider = new AuditTreeProvider(auditLogPath);
  const treeView = vscode.window.createTreeView('autoharness.auditTree', {
    treeDataProvider: treeProvider,
    showCollapseAll: true,
  });
  context.subscriptions.push(treeView);
  context.subscriptions.push({ dispose: () => treeProvider?.dispose() });

  // --- Constitution validator ---
  constitutionValidator = new ConstitutionValidator();
  context.subscriptions.push(constitutionValidator);

  // --- Commands ---
  context.subscriptions.push(
    vscode.commands.registerCommand('autoharness.showDashboard', () => {
      DashboardPanel.createOrShow(context.extensionUri, () => treeProvider?.getRecords() || []);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('autoharness.showAuditLog', () => {
      if (fs.existsSync(auditLogPath)) {
        vscode.workspace.openTextDocument(auditLogPath).then((doc) => {
          vscode.window.showTextDocument(doc);
        });
      } else {
        vscode.window.showWarningMessage(`Audit log not found: ${auditLogPath}`);
      }
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('autoharness.validateConstitution', () => {
      constitutionValidator?.validate();
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('autoharness.initConstitution', async () => {
      const constitutionRelative = config.get<string>('constitutionPath', 'constitution.yaml');
      const constitutionPath = path.isAbsolute(constitutionRelative)
        ? constitutionRelative
        : path.join(workspaceRoot, constitutionRelative);

      if (fs.existsSync(constitutionPath)) {
        const doc = await vscode.workspace.openTextDocument(constitutionPath);
        await vscode.window.showTextDocument(doc);
        return;
      }

      const template = [
        '# AutoHarness Constitution',
        '# Defines governance rules for AI agent tool usage.',
        '#',
        '# Documentation: https://github.com/aiming-lab/AutoHarness',
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
    }),
  );

  // Internal command for record detail view
  context.subscriptions.push(
    vscode.commands.registerCommand('autoharness.showRecordDetail', (record: AuditRecord) => {
      showRecordDetail(record);
    }),
  );

  // --- Config change listener ---
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('autoharness.auditLogPath')) {
        const newRelative = vscode.workspace
          .getConfiguration('autoharness')
          .get<string>('auditLogPath', 'audit.jsonl');
        const newPath = path.isAbsolute(newRelative)
          ? newRelative
          : path.join(workspaceRoot, newRelative);
        treeProvider?.updatePath(newPath);
      }
    }),
  );
}

export function deactivate(): void {
  treeProvider?.dispose();
  constitutionValidator?.dispose();
}
