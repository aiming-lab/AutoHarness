import * as fs from 'fs';

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
export function parseJsonl(filePath: string): AuditRecord[] {
  if (!fs.existsSync(filePath)) {
    return [];
  }
  const content = fs.readFileSync(filePath, 'utf-8');
  const records: AuditRecord[] = [];
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    try {
      records.push(JSON.parse(trimmed) as AuditRecord);
    } catch {
      // Skip malformed lines
    }
  }
  return records;
}

/** Format an ISO timestamp to a short readable form. */
export function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return iso;
  }
}

/** Map risk level to a ThemeColor name. */
export function riskColor(level: string): string {
  switch (level) {
    case 'critical':
      return 'charts.red';
    case 'high':
      return 'charts.orange';
    case 'medium':
      return 'charts.yellow';
    case 'low':
      return 'charts.green';
    default:
      return 'foreground';
  }
}

/** Map risk level to a CSS color for webviews. */
export function riskCssColor(level: string): string {
  switch (level) {
    case 'critical':
      return '#e74c3c';
    case 'high':
      return '#e67e22';
    case 'medium':
      return '#f1c40f';
    case 'low':
      return '#2ecc71';
    default:
      return '#95a5a6';
  }
}

/** Get a codicon name for event type. */
export function eventIcon(eventType: string): string {
  return eventType === 'tool_blocked' ? 'error' : 'pass';
}

/** Group records by session_id. */
export function groupBySession(records: AuditRecord[]): Map<string, AuditRecord[]> {
  const map = new Map<string, AuditRecord[]>();
  for (const r of records) {
    const group = map.get(r.session_id) || [];
    group.push(r);
    map.set(r.session_id, group);
  }
  return map;
}

/** Compute summary stats from records. */
export function computeStats(records: AuditRecord[]) {
  const total = records.length;
  const blocked = records.filter((r) => r.event_type === 'tool_blocked').length;
  const blockRate = total > 0 ? ((blocked / total) * 100).toFixed(1) : '0.0';

  const riskDist: Record<string, number> = { low: 0, medium: 0, high: 0, critical: 0 };
  const blockReasons: Record<string, number> = {};

  for (const r of records) {
    const level = r.risk.level || 'low';
    riskDist[level] = (riskDist[level] || 0) + 1;

    if (r.event_type === 'tool_blocked' && r.permission.reason) {
      const reason = r.permission.reason.substring(0, 80);
      blockReasons[reason] = (blockReasons[reason] || 0) + 1;
    }
  }

  const topBlockReasons = Object.entries(blockReasons)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  return { total, blocked, blockRate, riskDist, topBlockReasons };
}
