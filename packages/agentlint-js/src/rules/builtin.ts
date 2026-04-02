/**
 * Built-in risk rules for common dangerous operations.
 *
 * These are regex-based pattern matching rules for classifying tool call risk.
 * All patterns are compiled RegExp objects for performance.
 *
 * Rule structure:
 *   BUILTIN_RULES[toolCategory][riskLevel] -> RiskPattern[]
 *
 * Categories: bash, file_write, file_read, secrets_in_content
 * Risk levels: critical, high, medium, low
 */

import type { RiskPattern } from "../types.js";

// ---------------------------------------------------------------------------
// Bash command patterns
// ---------------------------------------------------------------------------

const BASH_CRITICAL: RiskPattern[] = [
  {
    pattern: String.raw`\brm\s+-[^\s]*r[^\s]*f[^\s]*\s+/\s*$|\brm\s+-[^\s]*f[^\s]*r[^\s]*\s+/\s*$`,
    description: "rm -rf / — recursive force-delete from root",
    category: "bash",
  },
  {
    pattern: String.raw`:\s*\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:`,
    description: "Fork bomb :(){ :|:& };:",
    category: "bash",
  },
  {
    pattern: String.raw`\bmkfs\b`,
    description: "Filesystem format command",
    category: "bash",
  },
  {
    pattern: String.raw`\bdd\b.*\bof\s*=\s*/dev/[a-z]`,
    description: "dd writing directly to block device",
    category: "bash",
  },
  {
    pattern: String.raw`(curl|wget)\s+[^\|]*\|\s*(ba)?sh`,
    description: "Pipe-to-shell — remote code execution via curl|bash or wget|sh",
    category: "bash",
  },
  {
    pattern: String.raw`>\s*/dev/(sd[a-z]|nvme|hd[a-z]|vd[a-z]|disk)`,
    description: "Direct write redirect to raw block device",
    category: "bash",
  },
];

const BASH_HIGH: RiskPattern[] = [
  {
    pattern: String.raw`\bsudo\b`,
    description: "Elevated privileges via sudo",
    category: "bash",
  },
  {
    pattern: String.raw`\bchmod\s+777\b`,
    description: "chmod 777 — world-writable permissions",
    category: "bash",
  },
  {
    pattern: String.raw`\bgit\s+push\s+.*--force\b|\bgit\s+push\s+-f\b`,
    description: "git push --force — destructive remote rewrite",
    category: "bash",
  },
  {
    pattern: String.raw`\bgit\s+reset\s+--hard\b`,
    description: "git reset --hard — destroys uncommitted changes",
    category: "bash",
  },
  {
    pattern: String.raw`\bDROP\s+(TABLE|DATABASE)\b`,
    description: "SQL DROP TABLE/DATABASE",
    category: "bash",
  },
  {
    pattern: String.raw`\beval\s*\(`,
    description: "eval() — dynamic code execution",
    category: "bash",
  },
  {
    pattern: String.raw`\bkill\s+-9\b`,
    description: "kill -9 — forced process termination",
    category: "bash",
  },
  {
    pattern: String.raw`\bdiskutil\s+(eraseDisk|partitionDisk)\b`,
    description: "macOS disk format/partition command",
    category: "bash",
  },
  {
    pattern: String.raw`\bfdisk\b|\bparted\b`,
    description: "Disk partitioning tools",
    category: "bash",
  },
];

const BASH_MEDIUM: RiskPattern[] = [
  {
    pattern: String.raw`\bgit\s+push\b(?!.*--force)(?!.*-f\b)`,
    description: "git push — pushes to remote",
    category: "bash",
  },
  {
    pattern: String.raw`\bnpm\s+publish\b`,
    description: "npm publish — publishes package to registry",
    category: "bash",
  },
  {
    pattern: String.raw`\bpip\s+install\b(?!.*-r\s)`,
    description: "pip install (ad-hoc, not from requirements file)",
    category: "bash",
  },
  {
    pattern: String.raw`\bdocker\s+(rm|rmi)\b`,
    description: "docker rm/rmi — removes containers or images",
    category: "bash",
  },
  {
    pattern: String.raw`\b(systemctl|service)\s+(restart|stop)\b`,
    description: "Service restart/stop command",
    category: "bash",
  },
  {
    pattern: String.raw`\bgit\s+checkout\s+\.\s*$|\bgit\s+restore\s+\.\s*$`,
    description: "git checkout/restore . — discards all unstaged changes",
    category: "bash",
  },
  {
    pattern: String.raw`\bgit\s+clean\s+-[^\s]*f`,
    description: "git clean -f — removes untracked files",
    category: "bash",
  },
  {
    pattern: String.raw`\bgit\s+branch\s+-D\b`,
    description: "git branch -D — force-delete branch",
    category: "bash",
  },
];

const BASH_LOW: RiskPattern[] = [
  {
    pattern: String.raw`^\s*(git\s+status|git\s+log|git\s+diff|git\s+show)\b`,
    description: "Safe git read commands",
    category: "bash",
  },
  {
    pattern: String.raw`^\s*ls\b`,
    description: "Directory listing",
    category: "bash",
  },
  {
    pattern: String.raw`^\s*(cat|head|tail|less|more)\b`,
    description: "File viewing commands",
    category: "bash",
  },
  {
    pattern: String.raw`^\s*echo\b`,
    description: "Echo command",
    category: "bash",
  },
  {
    pattern: String.raw`^\s*(npm\s+test|npx\s+jest|pytest|python\s+-m\s+pytest)\b`,
    description: "Test runner commands",
    category: "bash",
  },
  {
    pattern: String.raw`^\s*(pwd|whoami|hostname|uname|date|wc|sort|uniq)\b`,
    description: "Safe informational commands",
    category: "bash",
  },
  {
    pattern: String.raw`^\s*(grep|rg|find|fd)\b`,
    description: "Search/find commands",
    category: "bash",
  },
  {
    pattern: String.raw`^\s*(npm\s+run|yarn\s+run|make)\b`,
    description: "Build/script runner commands",
    category: "bash",
  },
];

// ---------------------------------------------------------------------------
// File write patterns
// ---------------------------------------------------------------------------

const FILE_WRITE_CRITICAL: RiskPattern[] = [
  {
    pattern: String.raw`\.env($|\.local$|\.production$|\.secret$)`,
    description: "Environment file with potential secrets",
    category: "file_write",
  },
  {
    pattern: String.raw`\.(pem|key|cert|p12|pfx|jks)$`,
    description: "Certificate/key file",
    category: "file_write",
  },
  {
    pattern: String.raw`credentials(\.json|\.yaml|\.yml|\.xml|\.toml)?$`,
    description: "Credentials file",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)\.ssh/`,
    description: "SSH directory — private keys, config, authorized_keys",
    category: "file_write",
  },
  {
    pattern: String.raw`id_(rsa|ed25519|ecdsa|dsa)($|\.pub$)`,
    description: "SSH key files",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)\.aws/(credentials|config)$`,
    description: "AWS credentials/config file",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)\.kube/config$`,
    description: "Kubernetes config (may contain cluster secrets)",
    category: "file_write",
  },
];

const FILE_WRITE_HIGH: RiskPattern[] = [
  {
    pattern: String.raw`package\.json$`,
    description: "Node.js package manifest — can change deps, scripts",
    category: "file_write",
  },
  {
    pattern: String.raw`Dockerfile$|docker-compose\.(yml|yaml)$`,
    description: "Docker configuration — affects build/deploy",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)\.github/(workflows|actions)/`,
    description: "GitHub Actions CI config",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)\.gitlab-ci\.yml$`,
    description: "GitLab CI configuration",
    category: "file_write",
  },
  {
    pattern: String.raw`(deploy|deployment)\.(yml|yaml|json|toml)$`,
    description: "Deployment configuration file",
    category: "file_write",
  },
  {
    pattern: String.raw`Makefile$|Rakefile$|Taskfile\.(yml|yaml)$`,
    description: "Build system entry point",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)\.circleci/config\.yml$`,
    description: "CircleCI configuration",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)Jenkinsfile$`,
    description: "Jenkins pipeline definition",
    category: "file_write",
  },
];

const FILE_WRITE_MEDIUM: RiskPattern[] = [
  {
    pattern: String.raw`\.(cfg|conf|config|ini|toml|yml|yaml)$`,
    description: "Configuration file",
    category: "file_write",
  },
  {
    pattern: String.raw`(package-lock|yarn\.lock|pnpm-lock|Pipfile\.lock|poetry\.lock|Cargo\.lock|Gemfile\.lock).*$`,
    description: "Dependency lock file",
    category: "file_write",
  },
  {
    pattern: String.raw`(^|/)\.gitignore$`,
    description: "Git ignore rules — may expose secrets if modified",
    category: "file_write",
  },
];

// ---------------------------------------------------------------------------
// File read patterns
// ---------------------------------------------------------------------------

const FILE_READ_CRITICAL: RiskPattern[] = [
  {
    pattern: String.raw`id_(rsa|ed25519|ecdsa|dsa)$`,
    description: "SSH private key (no .pub extension)",
    category: "file_read",
  },
  {
    pattern: String.raw`\.env\.local$`,
    description: "Local environment overrides — typically has real secrets",
    category: "file_read",
  },
  {
    pattern: String.raw`\.(pem|key)$`,
    description: "Private key / certificate key file",
    category: "file_read",
  },
];

const FILE_READ_HIGH: RiskPattern[] = [
  {
    pattern: String.raw`\.env($|\.production$|\.secret$)`,
    description: "Environment file likely containing secrets",
    category: "file_read",
  },
  {
    pattern: String.raw`credentials(\.json|\.yaml|\.yml|\.xml|\.toml)?$`,
    description: "Credentials file",
    category: "file_read",
  },
  {
    pattern: String.raw`(^|/)\.aws/(credentials|config)$`,
    description: "AWS credentials/config",
    category: "file_read",
  },
  {
    pattern: String.raw`(^|/)\.netrc$`,
    description: ".netrc — plaintext login credentials",
    category: "file_read",
  },
];

// ---------------------------------------------------------------------------
// Secrets-in-content patterns
// ---------------------------------------------------------------------------

const SECRETS_CRITICAL: RiskPattern[] = [
  {
    pattern: String.raw`\bsk-[A-Za-z0-9]{20,}`,
    description: "OpenAI API key (sk-...)",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`\bsk-ant-[A-Za-z0-9\-]{20,}`,
    description: "Anthropic API key (sk-ant-...)",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}`,
    description: "GitHub personal access token / OAuth / app token",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`\bAKIA[0-9A-Z]{16}\b`,
    description: "AWS access key ID (AKIA...)",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PGP)?\s*PRIVATE\s+KEY-----`,
    description: "Private key block in content",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`\bxox[bprsao]-[A-Za-z0-9\-]{10,}`,
    description: "Slack token (xoxb-, xoxp-, etc.)",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`(postgres|mysql|mongodb(\+srv)?|redis|amqp)://[^:]+:[^@\s]+@`,
    description: "Database connection URL with embedded password",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}`,
    description: "JWT token (eyJ...)",
    category: "secrets_in_content",
  },
  {
    pattern: String.raw`(?:api[_-]?key|api[_-]?secret|secret[_-]?key)\s*[:=]\s*['"]?[A-Za-z0-9/+=_\-]{20,}`,
    description: "Generic API key assignment pattern (api_key=..., secret_key=...)",
    category: "secrets_in_content",
  },
];

// ---------------------------------------------------------------------------
// Assembled registry
// ---------------------------------------------------------------------------

export type RiskLevelPatterns = Partial<
  Record<"critical" | "high" | "medium" | "low", RiskPattern[]>
>;

export const BUILTIN_RULES: Record<string, RiskLevelPatterns> = {
  bash: {
    critical: BASH_CRITICAL,
    high: BASH_HIGH,
    medium: BASH_MEDIUM,
    low: BASH_LOW,
  },
  file_write: {
    critical: FILE_WRITE_CRITICAL,
    high: FILE_WRITE_HIGH,
    medium: FILE_WRITE_MEDIUM,
  },
  file_read: {
    critical: FILE_READ_CRITICAL,
    high: FILE_READ_HIGH,
  },
  secrets_in_content: {
    critical: SECRETS_CRITICAL,
  },
};

// ---------------------------------------------------------------------------
// Known-safe command prefixes
// ---------------------------------------------------------------------------

export const SAFE_COMMAND_PREFIXES: ReadonlySet<string> = new Set([
  "git status",
  "git log",
  "git diff",
  "git show",
  "git branch",
  "git stash list",
  "ls",
  "cat",
  "head",
  "tail",
  "echo",
  "pwd",
  "whoami",
  "hostname",
  "uname",
  "date",
  "wc",
  "sort",
  "uniq",
  "grep",
  "rg",
  "find",
  "fd",
  "npm test",
  "npx jest",
  "pytest",
  "python -m pytest",
  "npm run",
  "yarn run",
  "make",
]);
