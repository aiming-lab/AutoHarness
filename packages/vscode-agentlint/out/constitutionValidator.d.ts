import * as vscode from 'vscode';
export declare class ConstitutionValidator implements vscode.Disposable {
    private diagnosticCollection;
    private disposables;
    constructor();
    private isConstitutionFile;
    /** Validate a constitution document. Called on command or on save. */
    validate(doc?: vscode.TextDocument): Promise<void>;
    /** Try running `autoharness validate --format json`. Returns null if CLI not available. */
    private tryCliValidation;
    /** Basic structural checks when the CLI is not available. */
    private basicYamlValidation;
    dispose(): void;
}
//# sourceMappingURL=constitutionValidator.d.ts.map