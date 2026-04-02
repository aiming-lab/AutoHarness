"""Built-in risk rules for tool call risk classification.

These are regex-based pattern matching rules for classifying tool call risk.
All patterns are raw strings intended for re.compile(); compilation happens
once in the RiskClassifier at init time for performance.

Rule structure:
    BUILTIN_RULES[tool_category][risk_level] -> list[RiskPattern]

Categories: bash, file_write, file_read, secrets_in_content
Risk levels: critical, high, medium, low
"""

from __future__ import annotations

from autoharness.core.types import RiskPattern

# ---------------------------------------------------------------------------
# Bash command patterns
# ---------------------------------------------------------------------------

_BASH_CRITICAL: list[RiskPattern] = [
    RiskPattern(
        pattern=r"\brm\s+-[^\s]*r[^\s]*f[^\s]*\s+/|\brm\s+-[^\s]*f[^\s]*r[^\s]*\s+/",
        description="rm -rf / — recursive force-delete from root",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\brm\s+-[^\s]*r[^\s]*f[^\s]*\s+~/|\brm\s+-[^\s]*f[^\s]*r[^\s]*\s+~/",
        description="rm -rf ~/ — recursive force-delete from home directory",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\brm\s+.*--no-preserve-root\b",
        description="rm --no-preserve-root — bypasses rm's built-in safety",
        category="bash",
    ),
    RiskPattern(
        pattern=r":\s*\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
        description="Fork bomb :(){ :|:& };:",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bmkfs\b",
        description="Filesystem format command",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bdd\b.*\bof\s*=\s*/dev/[a-z]",
        description="dd writing directly to block device",
        category="bash",
    ),
    RiskPattern(
        pattern=r"(curl|wget)\s+[^\|]*\|\s*(ba)?sh",
        description="Pipe-to-shell — remote code execution via curl|bash or wget|sh",
        category="bash",
    ),
    RiskPattern(
        pattern=r"(curl|wget)\s+.*&&\s*chmod\s+\+x\b",
        description="Download-and-execute chain — download then make executable",
        category="bash",
    ),
    RiskPattern(
        pattern=r">\s*/dev/(sd[a-z]|nvme|hd[a-z]|vd[a-z]|disk)",
        description="Direct write redirect to raw block device",
        category="bash",
    ),
]

_BASH_HIGH: list[RiskPattern] = [
    RiskPattern(
        pattern=r"\bsudo\b",
        description="Elevated privileges via sudo",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bchmod\s+777\b",
        description="chmod 777 — world-writable permissions",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bgit\s+push\s+.*--force\b|\bgit\s+push\s+-f\b",
        description="git push --force — destructive remote rewrite",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bgit\s+reset\s+--hard\b",
        description="git reset --hard — destroys uncommitted changes",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bDROP\s+(TABLE|DATABASE)\b",
        description="SQL DROP TABLE/DATABASE",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\beval\s*\(",
        description="eval() — dynamic code execution",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bkill\s+-9\b",
        description="kill -9 — forced process termination",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bdiskutil\s+(eraseDisk|partitionDisk)\b",
        description="macOS disk format/partition command",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bfdisk\b|\bparted\b",
        description="Disk partitioning tools",
        category="bash",
    ),
]

# --- Additional high-risk bash patterns ---
_BASH_HIGH_EXTENDED: list[RiskPattern] = [
    # Zsh builtins that can be dangerous
    RiskPattern(
        pattern=r"(?:^|\s|;)\s*(?:zmodload|zcompile|autoload|source|\.)\s+",
        description="Zsh module/autoload/source — can load arbitrary code",
        category="bash",
    ),
    # Zsh equals expansion: =curl → /usr/bin/curl, bypasses validation
    RiskPattern(
        pattern=r"(?:^|\s)=[a-zA-Z]",
        description="Zsh equals expansion (=cmd) — bypasses path validation",
        category="bash",
    ),
    # Unicode zero-width characters that can hide malicious content
    RiskPattern(
        pattern=r"[\u200b\u200c\u200d\u2060\ufeff]",
        description="Unicode zero-width character injection — hidden command obfuscation",
        category="bash",
    ),
    # IFS manipulation — can alter word splitting behavior
    RiskPattern(
        pattern=r"\bIFS\s*=",
        description="IFS variable manipulation — alters shell word splitting",
        category="bash",
    ),
    # Null byte injection
    RiskPattern(
        pattern=r"\\x00|\\0|%00|\$'\\0'",
        description="Null byte injection — may truncate strings or bypass checks",
        category="bash",
    ),
    # Process substitution — can exfiltrate data
    RiskPattern(
        pattern=r">\(|<\(",
        description="Process substitution — potential data exfiltration",
        category="bash",
    ),
    # Command chaining with background execution
    RiskPattern(
        pattern=r";\s*(?:nohup|disown|setsid)\s",
        description="Background process persistence (nohup/disown/setsid)",
        category="bash",
    ),
    # Network tools that could exfiltrate data
    RiskPattern(
        pattern=r"\b(nc|ncat|netcat|socat)\b.*(?:-l|-e|-c)",
        description="Netcat listener/exec — potential reverse shell or data exfiltration",
        category="bash",
    ),
    # Crontab modification
    RiskPattern(
        pattern=r"\bcrontab\s+-[er]",
        description="Crontab modification — can install persistent scheduled tasks",
        category="bash",
    ),
    # SSH key generation or agent manipulation
    RiskPattern(
        pattern=r"\bssh-keygen\b|\bssh-add\b",
        description="SSH key generation/agent manipulation",
        category="bash",
    ),
    # Interpreter execution with inline code (auto-mode danger)
    RiskPattern(
        pattern=r"\b(python|python3|node|ruby|perl|php|lua)\s+-[ec]\s",
        description="Interpreter inline code execution — bypasses file-level governance",
        category="bash",
    ),
    # Package runner execution (auto-mode danger)
    RiskPattern(
        pattern=r"\b(npx|bunx|pnpx)\s+[^-]",
        description="Package runner execution — runs arbitrary packages",
        category="bash",
    ),
    # Dangerous Zsh builtins (18 blocked)
    RiskPattern(
        pattern=r"(?:^|\s|;)\s*(?:bindkey|compctl|compadd|compdef|zle|vared|rehash|unlimit|limit|sched|zsocket|zselect|ztcp)\b",
        description="Dangerous Zsh builtin command",
        category="bash",
    ),
]

_BASH_MEDIUM: list[RiskPattern] = [
    RiskPattern(
        pattern=r"\bgit\s+push\b(?!.*--force)(?!.*-f\b)",
        description="git push — pushes to remote",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bnpm\s+publish\b",
        description="npm publish — publishes package to registry",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bpip\s+install\b(?!.*-r\s)",
        description="pip install (ad-hoc, not from requirements file)",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bdocker\s+(rm|rmi)\b",
        description="docker rm/rmi — removes containers or images",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\b(systemctl|service)\s+(restart|stop)\b",
        description="Service restart/stop command",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bgit\s+checkout\s+\.\s*$|\bgit\s+restore\s+\.\s*$",
        description="git checkout/restore . — discards all unstaged changes",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bgit\s+clean\s+-[^\s]*f",
        description="git clean -f — removes untracked files",
        category="bash",
    ),
    RiskPattern(
        pattern=r"\bgit\s+branch\s+-D\b",
        description="git branch -D — force-delete branch",
        category="bash",
    ),
]

_BASH_LOW: list[RiskPattern] = [
    RiskPattern(
        pattern=r"^\s*(git\s+status|git\s+log|git\s+diff|git\s+show)\b",
        description="Safe git read commands",
        category="bash",
    ),
    RiskPattern(
        pattern=r"^\s*ls\b",
        description="Directory listing",
        category="bash",
    ),
    RiskPattern(
        pattern=r"^\s*(cat|head|tail|less|more)\b",
        description="File viewing commands",
        category="bash",
    ),
    RiskPattern(
        pattern=r"^\s*echo\b",
        description="Echo command",
        category="bash",
    ),
    RiskPattern(
        pattern=r"^\s*(npm\s+test|npx\s+jest|pytest|python\s+-m\s+pytest)\b",
        description="Test runner commands",
        category="bash",
    ),
    RiskPattern(
        pattern=r"^\s*(pwd|whoami|hostname|uname|date|wc|sort|uniq)\b",
        description="Safe informational commands",
        category="bash",
    ),
    RiskPattern(
        pattern=r"^\s*(grep|rg|find|fd)\b",
        description="Search/find commands",
        category="bash",
    ),
    RiskPattern(
        pattern=r"^\s*(npm\s+run|yarn\s+run|make)\b",
        description="Build/script runner commands",
        category="bash",
    ),
]

# ---------------------------------------------------------------------------
# File write patterns
# ---------------------------------------------------------------------------

_FILE_WRITE_CRITICAL: list[RiskPattern] = [
    RiskPattern(
        pattern=r"\.env($|\.local$|\.production$|\.secret$)",
        description="Environment file with potential secrets",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"\.(pem|key|cert|p12|pfx|jks)$",
        description="Certificate/key file",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"credentials(\.json|\.yaml|\.yml|\.xml|\.toml)?$",
        description="Credentials file",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)\.ssh/",
        description="SSH directory — private keys, config, authorized_keys",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"id_(rsa|ed25519|ecdsa|dsa)($|\.pub$)",
        description="SSH key files",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)\.aws/(credentials|config)$",
        description="AWS credentials/config file",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)\.kube/config$",
        description="Kubernetes config (may contain cluster secrets)",
        category="file_write",
    ),
]

_FILE_WRITE_HIGH: list[RiskPattern] = [
    RiskPattern(
        pattern=r"package\.json$",
        description="Node.js package manifest — can change deps, scripts",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"Dockerfile$|docker-compose\.(yml|yaml)$",
        description="Docker configuration — affects build/deploy",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)\.github/(workflows|actions)/",
        description="GitHub Actions CI config",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)\.gitlab-ci\.yml$",
        description="GitLab CI configuration",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(deploy|deployment)\.(yml|yaml|json|toml)$",
        description="Deployment configuration file",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"Makefile$|Rakefile$|Taskfile\.(yml|yaml)$",
        description="Build system entry point",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)\.circleci/config\.yml$",
        description="CircleCI configuration",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)Jenkinsfile$",
        description="Jenkins pipeline definition",
        category="file_write",
    ),
]

_FILE_WRITE_MEDIUM: list[RiskPattern] = [
    RiskPattern(
        pattern=r"\.(cfg|conf|config|ini|toml|yml|yaml)$",
        description="Configuration file",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(package-lock|yarn\.lock|pnpm-lock|Pipfile\.lock|poetry\.lock|Cargo\.lock|Gemfile\.lock).*$",
        description="Dependency lock file",
        category="file_write",
    ),
    RiskPattern(
        pattern=r"(^|/)\.gitignore$",
        description="Git ignore rules — may expose secrets if modified",
        category="file_write",
    ),
]

# ---------------------------------------------------------------------------
# File read patterns
# ---------------------------------------------------------------------------

_FILE_READ_CRITICAL: list[RiskPattern] = [
    RiskPattern(
        pattern=r"id_(rsa|ed25519|ecdsa|dsa)$",
        description="SSH private key (no .pub extension)",
        category="file_read",
    ),
    RiskPattern(
        pattern=r"\.env\.local$",
        description="Local environment overrides — typically has real secrets",
        category="file_read",
    ),
    RiskPattern(
        pattern=r"\.(pem|key)$",
        description="Private key / certificate key file",
        category="file_read",
    ),
]

_FILE_READ_HIGH: list[RiskPattern] = [
    RiskPattern(
        pattern=r"\.env($|\.production$|\.secret$)",
        description="Environment file likely containing secrets",
        category="file_read",
    ),
    RiskPattern(
        pattern=r"credentials(\.json|\.yaml|\.yml|\.xml|\.toml)?$",
        description="Credentials file",
        category="file_read",
    ),
    RiskPattern(
        pattern=r"(^|/)\.aws/(credentials|config)$",
        description="AWS credentials/config",
        category="file_read",
    ),
    RiskPattern(
        pattern=r"(^|/)\.netrc$",
        description=".netrc — plaintext login credentials",
        category="file_read",
    ),
    # Sensitive system files
    RiskPattern(
        pattern=r"(^|/)(etc/shadow|etc/passwd|etc/sudoers)$",
        description="Sensitive system file (shadow/passwd/sudoers)",
        category="file_read",
    ),
    RiskPattern(
        pattern=r"(^|/)\.ssh/(id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys|config)$",
        description="SSH key or config file",
        category="file_read",
    ),
]

# ---------------------------------------------------------------------------
# Secrets-in-content patterns (scan arbitrary text for leaked secrets)
# ---------------------------------------------------------------------------

_SECRETS_CRITICAL: list[RiskPattern] = [
    RiskPattern(
        pattern=r"\bsk-[A-Za-z0-9]{20,}",
        description="OpenAI API key (sk-...)",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"\bsk-proj-[A-Za-z0-9_\-]{10,}",
        description="OpenAI project API key (sk-proj-...)",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"\bsk-ant-[A-Za-z0-9\-]{20,}",
        description="Anthropic API key (sk-ant-...)",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
        description="GitHub personal access token / OAuth / app token",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"\bAKIA[0-9A-Z]{16}\b",
        description="AWS access key ID (AKIA...)",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PGP)?\s*PRIVATE\s+KEY-----",
        description="Private key block in content",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"\bxox[bprsao]-[A-Za-z0-9\-]{10,}",
        description="Slack token (xoxb-, xoxp-, etc.)",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"(postgres(ql)?|mysql|mongodb(\+srv)?|redis|amqp)://[^:]+:[^@\s]+@",
        description="Database connection URL with embedded password",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
        description="JWT token (eyJ...)",
        category="secrets_in_content",
    ),
    RiskPattern(
        pattern=r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9/+=_\-]{20,}",
        description="Generic API key assignment pattern (api_key=..., secret_key=...)",
        category="secrets_in_content",
    ),
]

# ---------------------------------------------------------------------------
# Assembled registry
# ---------------------------------------------------------------------------

BUILTIN_RULES: dict[str, dict[str, list[RiskPattern]]] = {
    "bash": {
        "critical": _BASH_CRITICAL,
        "high": _BASH_HIGH + _BASH_HIGH_EXTENDED,
        "medium": _BASH_MEDIUM,
        "low": _BASH_LOW,
    },
    "file_write": {
        "critical": _FILE_WRITE_CRITICAL,
        "high": _FILE_WRITE_HIGH,
        "medium": _FILE_WRITE_MEDIUM,
    },
    "file_read": {
        "critical": _FILE_READ_CRITICAL,
        "high": _FILE_READ_HIGH,
    },
    "secrets_in_content": {
        "critical": _SECRETS_CRITICAL,
    },
}

# Known-safe command prefixes — if a command starts with one of these,
# skip the medium/high/critical rule scan (still log at low).
SAFE_COMMAND_PREFIXES: set[str] = {
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
}
