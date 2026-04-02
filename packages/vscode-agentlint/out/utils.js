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
exports.parseJsonl = parseJsonl;
exports.formatTimestamp = formatTimestamp;
exports.riskColor = riskColor;
exports.riskCssColor = riskCssColor;
exports.eventIcon = eventIcon;
exports.groupBySession = groupBySession;
exports.computeStats = computeStats;
const fs = __importStar(require("fs"));
/** Parse a JSONL file into an array of AuditRecords. */
function parseJsonl(filePath) {
    if (!fs.existsSync(filePath)) {
        return [];
    }
    const content = fs.readFileSync(filePath, 'utf-8');
    const records = [];
    for (const line of content.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed) {
            continue;
        }
        try {
            records.push(JSON.parse(trimmed));
        }
        catch {
            // Skip malformed lines
        }
    }
    return records;
}
/** Format an ISO timestamp to a short readable form. */
function formatTimestamp(iso) {
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
    }
    catch {
        return iso;
    }
}
/** Map risk level to a ThemeColor name. */
function riskColor(level) {
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
function riskCssColor(level) {
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
function eventIcon(eventType) {
    return eventType === 'tool_blocked' ? 'error' : 'pass';
}
/** Group records by session_id. */
function groupBySession(records) {
    const map = new Map();
    for (const r of records) {
        const group = map.get(r.session_id) || [];
        group.push(r);
        map.set(r.session_id, group);
    }
    return map;
}
/** Compute summary stats from records. */
function computeStats(records) {
    const total = records.length;
    const blocked = records.filter((r) => r.event_type === 'tool_blocked').length;
    const blockRate = total > 0 ? ((blocked / total) * 100).toFixed(1) : '0.0';
    const riskDist = { low: 0, medium: 0, high: 0, critical: 0 };
    const blockReasons = {};
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
//# sourceMappingURL=utils.js.map