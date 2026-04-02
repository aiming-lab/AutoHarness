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
exports.ConstitutionValidator = void 0;
const vscode = __importStar(require("vscode"));
const cp = __importStar(require("child_process"));
const path = __importStar(require("path"));
const DIAGNOSTIC_SOURCE = 'HarnessAgent';
class ConstitutionValidator {
    diagnosticCollection;
    disposables = [];
    constructor() {
        this.diagnosticCollection = vscode.languages.createDiagnosticCollection('harnessagent');
        // Validate on save
        this.disposables.push(vscode.workspace.onDidSaveTextDocument((doc) => {
            const autoValidate = vscode.workspace
                .getConfiguration('harnessagent')
                .get('autoValidate', true);
            if (autoValidate && this.isConstitutionFile(doc)) {
                this.validate(doc);
            }
        }));
        // Clear diagnostics when file is closed
        this.disposables.push(vscode.workspace.onDidCloseTextDocument((doc) => {
            this.diagnosticCollection.delete(doc.uri);
        }));
    }
    isConstitutionFile(doc) {
        const name = path.basename(doc.fileName);
        if (name === 'constitution.yaml' || name === 'constitution.yml') {
            return true;
        }
        const configuredPath = vscode.workspace
            .getConfiguration('harnessagent')
            .get('constitutionPath', 'constitution.yaml');
        return doc.fileName.endsWith(configuredPath);
    }
    /** Validate a constitution document. Called on command or on save. */
    async validate(doc) {
        if (!doc) {
            doc = vscode.window.activeTextEditor?.document;
        }
        if (!doc) {
            vscode.window.showWarningMessage('No active constitution file to validate.');
            return;
        }
        const diagnostics = [];
        // Try the CLI first
        const cliResult = await this.tryCliValidation(doc.fileName);
        if (cliResult !== null) {
            for (const issue of cliResult) {
                const range = new vscode.Range(Math.max(0, (issue.line || 1) - 1), 0, Math.max(0, (issue.line || 1) - 1), 1000);
                const severity = issue.severity === 'error'
                    ? vscode.DiagnosticSeverity.Error
                    : vscode.DiagnosticSeverity.Warning;
                const diag = new vscode.Diagnostic(range, issue.message, severity);
                diag.source = DIAGNOSTIC_SOURCE;
                diagnostics.push(diag);
            }
        }
        else {
            // Fallback: basic YAML structure validation
            const text = doc.getText();
            this.basicYamlValidation(text, diagnostics);
        }
        this.diagnosticCollection.set(doc.uri, diagnostics);
        if (diagnostics.length === 0) {
            vscode.window.showInformationMessage('Constitution is valid.');
        }
    }
    /** Try running `harnessagent validate --format json`. Returns null if CLI not available. */
    tryCliValidation(filePath) {
        return new Promise((resolve) => {
            const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || path.dirname(filePath);
            cp.exec(`harnessagent validate --format json "${filePath}"`, { cwd, timeout: 10000 }, (err, stdout, stderr) => {
                if (err && err.code === 'ENOENT') {
                    // CLI not installed
                    resolve(null);
                    return;
                }
                try {
                    const result = JSON.parse(stdout);
                    if (Array.isArray(result.issues)) {
                        resolve(result.issues);
                    }
                    else if (Array.isArray(result)) {
                        resolve(result);
                    }
                    else {
                        resolve([]);
                    }
                }
                catch {
                    // Could not parse CLI output — fall back
                    resolve(null);
                }
            });
        });
    }
    /** Basic structural checks when the CLI is not available. */
    basicYamlValidation(text, diagnostics) {
        const lines = text.split('\n');
        // Check for required top-level keys
        const requiredKeys = ['rules'];
        for (const key of requiredKeys) {
            const pattern = new RegExp(`^${key}\\s*:`, 'm');
            if (!pattern.test(text)) {
                const diag = new vscode.Diagnostic(new vscode.Range(0, 0, 0, 1), `Missing required top-level key: "${key}"`, vscode.DiagnosticSeverity.Error);
                diag.source = DIAGNOSTIC_SOURCE;
                diagnostics.push(diag);
            }
        }
        // Check for tab characters (YAML does not allow tabs for indentation)
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].startsWith('\t') || /^\s*\t/.test(lines[i])) {
                const tabIndex = lines[i].indexOf('\t');
                const diag = new vscode.Diagnostic(new vscode.Range(i, tabIndex, i, tabIndex + 1), 'YAML does not allow tab characters for indentation', vscode.DiagnosticSeverity.Error);
                diag.source = DIAGNOSTIC_SOURCE;
                diagnostics.push(diag);
            }
        }
        // Check for duplicate keys at the same indentation level (simple heuristic)
        const seenAtLevel = new Map();
        for (let i = 0; i < lines.length; i++) {
            const match = lines[i].match(/^(\s*)(\w[\w-]*):\s/);
            if (match) {
                const indent = match[1].length;
                const key = match[2];
                const set = seenAtLevel.get(indent) || new Set();
                if (set.has(key)) {
                    const diag = new vscode.Diagnostic(new vscode.Range(i, indent, i, indent + key.length), `Possible duplicate key: "${key}"`, vscode.DiagnosticSeverity.Warning);
                    diag.source = DIAGNOSTIC_SOURCE;
                    diagnostics.push(diag);
                }
                set.add(key);
                seenAtLevel.set(indent, set);
            }
        }
    }
    dispose() {
        this.diagnosticCollection.dispose();
        for (const d of this.disposables) {
            d.dispose();
        }
    }
}
exports.ConstitutionValidator = ConstitutionValidator;
//# sourceMappingURL=constitutionValidator.js.map