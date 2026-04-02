/** A single audit record from the JSONL log. */
export interface AuditRecord {
    timestamp: string;
    session_id: string;
    event_type: 'tool_call' | 'tool_blocked' | string;
    tool_name: string;
    tool_input_hash: string;
    risk: {
        level: 'low' | 'medium' | 'high' | 'critical';
        classifier: string;
        matched_rule: string | null;
        reason: string;
        confidence: number;
    };
    hooks_pre: Array<{
        action: 'allow' | 'deny' | 'ask';
        reason: string | null;
        severity: string;
    }>;
    hooks_post: Array<{
        action: string;
        reason: string | null;
        severity: string;
        sanitized?: boolean;
    }>;
    permission: {
        action: 'allow' | 'deny';
        reason: string;
        source: string;
        risk_level: string | null;
    };
    execution: {
        status: 'success' | 'blocked' | string;
        duration_ms: number;
        output_size: number;
        sanitized: boolean;
    };
}
/** Parse a JSONL file into an array of AuditRecords. */
export declare function parseJsonl(filePath: string): AuditRecord[];
/** Format an ISO timestamp to a short readable form. */
export declare function formatTimestamp(iso: string): string;
/** Map risk level to a ThemeColor name. */
export declare function riskColor(level: string): string;
/** Map risk level to a CSS color for webviews. */
export declare function riskCssColor(level: string): string;
/** Get a codicon name for event type. */
export declare function eventIcon(eventType: string): string;
/** Group records by session_id. */
export declare function groupBySession(records: AuditRecord[]): Map<string, AuditRecord[]>;
/** Compute summary stats from records. */
export declare function computeStats(records: AuditRecord[]): {
    total: number;
    blocked: number;
    blockRate: string;
    riskDist: Record<string, number>;
    topBlockReasons: [string, number][];
};
//# sourceMappingURL=utils.d.ts.map