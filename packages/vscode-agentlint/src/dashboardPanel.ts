import * as vscode from 'vscode';
import { AuditRecord, computeStats, formatTimestamp, riskCssColor } from './utils';

export class DashboardPanel {
  public static currentPanel: DashboardPanel | undefined;
  private static readonly viewType = 'autoharness.dashboard';

  private readonly panel: vscode.WebviewPanel;
  private refreshTimer: ReturnType<typeof setInterval> | undefined;
  private disposables: vscode.Disposable[] = [];

  private constructor(
    panel: vscode.WebviewPanel,
    private getRecords: () => AuditRecord[],
  ) {
    this.panel = panel;
    this.update();

    // Auto-refresh every 5 seconds
    this.refreshTimer = setInterval(() => this.update(), 5000);

    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
  }

  static createOrShow(
    extensionUri: vscode.Uri,
    getRecords: () => AuditRecord[],
  ): void {
    const column = vscode.ViewColumn.Beside;

    if (DashboardPanel.currentPanel) {
      DashboardPanel.currentPanel.panel.reveal(column);
      DashboardPanel.currentPanel.update();
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      DashboardPanel.viewType,
      'AutoHarness Dashboard',
      column,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      },
    );

    DashboardPanel.currentPanel = new DashboardPanel(panel, getRecords);
  }

  private update(): void {
    const records = this.getRecords();
    this.panel.webview.html = this.getHtml(records);
  }

  private getHtml(records: AuditRecord[]): string {
    const stats = computeStats(records);
    const recent = records.slice(-20).reverse();

    const riskBarMax = Math.max(...Object.values(stats.riskDist), 1);

    const riskBarsHtml = ['critical', 'high', 'medium', 'low']
      .map((level) => {
        const count = stats.riskDist[level] || 0;
        const pct = ((count / riskBarMax) * 100).toFixed(0);
        const color = riskCssColor(level);
        return `
          <div class="bar-row">
            <span class="bar-label">${level}</span>
            <div class="bar-track">
              <div class="bar-fill" style="width: ${pct}%; background: ${color};"></div>
            </div>
            <span class="bar-count">${count}</span>
          </div>`;
      })
      .join('');

    const topReasonsHtml = stats.topBlockReasons.length
      ? stats.topBlockReasons
          .map(
            ([reason, count]) =>
              `<tr><td class="reason-text">${escapeHtml(reason)}</td><td class="reason-count">${count}</td></tr>`,
          )
          .join('')
      : '<tr><td colspan="2" class="empty">No blocked actions</td></tr>';

    const timelineHtml = recent.length
      ? recent
          .map((r) => {
            const isBlocked = r.event_type === 'tool_blocked';
            const icon = isBlocked ? '&#x2716;' : '&#x2714;';
            const cls = isBlocked ? 'blocked' : 'allowed';
            const riskBadge = `<span class="risk-badge" style="background:${riskCssColor(r.risk.level)}">${r.risk.level}</span>`;
            return `
            <div class="timeline-item ${cls}">
              <span class="timeline-icon">${icon}</span>
              <span class="timeline-tool">${escapeHtml(r.tool_name)}</span>
              ${riskBadge}
              <span class="timeline-time">${formatTimestamp(r.timestamp)}</span>
            </div>`;
          })
          .join('')
      : '<div class="empty">No audit records found</div>';

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  :root {
    --bg: var(--vscode-editor-background);
    --fg: var(--vscode-editor-foreground);
    --border: var(--vscode-panel-border);
    --card-bg: var(--vscode-editorWidget-background);
  }
  body { font-family: var(--vscode-font-family); color: var(--fg); background: var(--bg); padding: 16px; margin: 0; }
  h1 { font-size: 18px; margin: 0 0 16px; display: flex; align-items: center; gap: 8px; }
  h1::before { content: '\\1F6E1'; }
  .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
  .stat-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 14px; text-align: center; }
  .stat-value { font-size: 28px; font-weight: bold; }
  .stat-label { font-size: 11px; opacity: 0.7; text-transform: uppercase; margin-top: 4px; }
  .stat-value.red { color: #e74c3c; }

  .section { margin-bottom: 20px; }
  .section-title { font-size: 13px; font-weight: 600; text-transform: uppercase; opacity: 0.7; margin-bottom: 8px; letter-spacing: 0.5px; }

  .bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .bar-label { width: 60px; font-size: 12px; text-align: right; text-transform: capitalize; }
  .bar-track { flex: 1; height: 18px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
  .bar-count { width: 30px; font-size: 12px; }

  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
  .reason-text { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .reason-count { text-align: right; font-weight: bold; width: 40px; }

  .timeline-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
  .timeline-icon { font-size: 14px; width: 20px; text-align: center; }
  .timeline-item.blocked .timeline-icon { color: #e74c3c; }
  .timeline-item.allowed .timeline-icon { color: #2ecc71; }
  .timeline-tool { font-weight: 600; min-width: 60px; }
  .timeline-time { margin-left: auto; opacity: 0.6; }
  .risk-badge { font-size: 10px; padding: 1px 6px; border-radius: 8px; color: #fff; text-transform: uppercase; }
  .empty { opacity: 0.5; font-style: italic; padding: 8px; }
</style>
</head>
<body>
  <h1>AutoHarness Governance Dashboard</h1>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-value">${stats.total}</div>
      <div class="stat-label">Total Calls</div>
    </div>
    <div class="stat-card">
      <div class="stat-value red">${stats.blocked}</div>
      <div class="stat-label">Blocked</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">${stats.blockRate}%</div>
      <div class="stat-label">Block Rate</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Risk Distribution</div>
    ${riskBarsHtml}
  </div>

  <div class="section">
    <div class="section-title">Top Block Reasons</div>
    <table>${topReasonsHtml}</table>
  </div>

  <div class="section">
    <div class="section-title">Recent Actions (last 20)</div>
    ${timelineHtml}
  </div>
</body>
</html>`;
  }

  private dispose(): void {
    DashboardPanel.currentPanel = undefined;
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
    }
    this.panel.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
