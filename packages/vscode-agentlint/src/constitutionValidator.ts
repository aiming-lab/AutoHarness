import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

const DIAGNOSTIC_SOURCE = 'AutoHarness';

export class ConstitutionValidator implements vscode.Disposable {
  private diagnosticCollection: vscode.DiagnosticCollection;
  private disposables: vscode.Disposable[] = [];

  constructor() {
    this.diagnosticCollection = vscode.languages.createDiagnosticCollection('autoharness');

    // Validate on save
    this.disposables.push(
      vscode.workspace.onDidSaveTextDocument((doc) => {
        const autoValidate = vscode.workspace
          .getConfiguration('autoharness')
          .get<boolean>('autoValidate', true);

        if (autoValidate && this.isConstitutionFile(doc)) {
          this.validate(doc);
        }
      }),
    );

    // Clear diagnostics when file is closed
    this.disposables.push(
      vscode.workspace.onDidCloseTextDocument((doc) => {
        this.diagnosticCollection.delete(doc.uri);
      }),
    );
  }

  private isConstitutionFile(doc: vscode.TextDocument): boolean {
    const name = path.basename(doc.fileName);
    if (name === 'constitution.yaml' || name === 'constitution.yml') {
      return true;
    }
    const configuredPath = vscode.workspace
      .getConfiguration('autoharness')
      .get<string>('constitutionPath', 'constitution.yaml');
    return doc.fileName.endsWith(configuredPath);
  }

  /** Validate a constitution document. Called on command or on save. */
  async validate(doc?: vscode.TextDocument): Promise<void> {
    if (!doc) {
      doc = vscode.window.activeTextEditor?.document;
    }
    if (!doc) {
      vscode.window.showWarningMessage('No active constitution file to validate.');
      return;
    }

    const diagnostics: vscode.Diagnostic[] = [];

    // Try the CLI first
    const cliResult = await this.tryCliValidation(doc.fileName);
    if (cliResult !== null) {
      for (const issue of cliResult) {
        const range = new vscode.Range(
          Math.max(0, (issue.line || 1) - 1),
          0,
          Math.max(0, (issue.line || 1) - 1),
          1000,
        );
        const severity =
          issue.severity === 'error'
            ? vscode.DiagnosticSeverity.Error
            : vscode.DiagnosticSeverity.Warning;
        const diag = new vscode.Diagnostic(range, issue.message, severity);
        diag.source = DIAGNOSTIC_SOURCE;
        diagnostics.push(diag);
      }
    } else {
      // Fallback: basic YAML structure validation
      const text = doc.getText();
      this.basicYamlValidation(text, diagnostics);
    }

    this.diagnosticCollection.set(doc.uri, diagnostics);

    if (diagnostics.length === 0) {
      vscode.window.showInformationMessage('Constitution is valid.');
    }
  }

  /** Try running `autoharness validate --format json`. Returns null if CLI not available. */
  private tryCliValidation(
    filePath: string,
  ): Promise<Array<{ line?: number; severity: string; message: string }> | null> {
    return new Promise((resolve) => {
      const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || path.dirname(filePath);
      cp.exec(
        `autoharness validate --format json "${filePath}"`,
        { cwd, timeout: 10000 },
        (err, stdout, stderr) => {
          if (err && (err as any).code === 'ENOENT') {
            // CLI not installed
            resolve(null);
            return;
          }
          try {
            const result = JSON.parse(stdout);
            if (Array.isArray(result.issues)) {
              resolve(result.issues);
            } else if (Array.isArray(result)) {
              resolve(result);
            } else {
              resolve([]);
            }
          } catch {
            // Could not parse CLI output — fall back
            resolve(null);
          }
        },
      );
    });
  }

  /** Basic structural checks when the CLI is not available. */
  private basicYamlValidation(text: string, diagnostics: vscode.Diagnostic[]): void {
    const lines = text.split('\n');

    // Check for required top-level keys
    const requiredKeys = ['rules'];
    for (const key of requiredKeys) {
      const pattern = new RegExp(`^${key}\\s*:`, 'm');
      if (!pattern.test(text)) {
        const diag = new vscode.Diagnostic(
          new vscode.Range(0, 0, 0, 1),
          `Missing required top-level key: "${key}"`,
          vscode.DiagnosticSeverity.Error,
        );
        diag.source = DIAGNOSTIC_SOURCE;
        diagnostics.push(diag);
      }
    }

    // Check for tab characters (YAML does not allow tabs for indentation)
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].startsWith('\t') || /^\s*\t/.test(lines[i])) {
        const tabIndex = lines[i].indexOf('\t');
        const diag = new vscode.Diagnostic(
          new vscode.Range(i, tabIndex, i, tabIndex + 1),
          'YAML does not allow tab characters for indentation',
          vscode.DiagnosticSeverity.Error,
        );
        diag.source = DIAGNOSTIC_SOURCE;
        diagnostics.push(diag);
      }
    }

    // Check for duplicate keys at the same indentation level (simple heuristic)
    const seenAtLevel = new Map<number, Set<string>>();
    for (let i = 0; i < lines.length; i++) {
      const match = lines[i].match(/^(\s*)(\w[\w-]*):\s/);
      if (match) {
        const indent = match[1].length;
        const key = match[2];
        const set = seenAtLevel.get(indent) || new Set();
        if (set.has(key)) {
          const diag = new vscode.Diagnostic(
            new vscode.Range(i, indent, i, indent + key.length),
            `Possible duplicate key: "${key}"`,
            vscode.DiagnosticSeverity.Warning,
          );
          diag.source = DIAGNOSTIC_SOURCE;
          diagnostics.push(diag);
        }
        set.add(key);
        seenAtLevel.set(indent, set);
      }
    }
  }

  dispose(): void {
    this.diagnosticCollection.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}
