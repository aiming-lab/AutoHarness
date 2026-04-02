<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>모든 에이전트는 <b>aha</b> 모먼트를 누릴 자격이 있습니다 — 모델은 추론하고, 나머지는 우리가 harness합니다.</em></h3>

<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-빠른-시작"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
  <a href="https://github.com/aiming-lab/AutoHarness"><img src="https://img.shields.io/badge/GitHub-AutoHarness-181717?logo=github" alt="GitHub"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/Code%20Style-Ruff-000000?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/Type%20Check-mypy-blue?logo=python&logoColor=white" alt="mypy"></a>
</p>

<p align="center">
  🇬🇧 <a href="../README.md">English</a> ·
  🇨🇳 <a href="README_CN.md">简体中文</a> ·
  🇯🇵 <a href="README_JA.md">日本語</a> ·
  🇰🇷 한국어 ·
  🇪🇸 <a href="README_ES.md">Español</a> ·
  🇫🇷 <a href="README_FR.md">Français</a> ·
  🇩🇪 <a href="README_DE.md">Deutsch</a> ·
  🇵🇹 <a href="README_PT.md">Português</a> ·
  🇷🇺 <a href="README_RU.md">Русский</a>
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 문서</b></a> ·
  <a href="#-빠른-시작"><b>🚀 빠른 시작</b></a> ·
  <a href="#-파이프라인-모드"><b>🔧 파이프라인 모드</b></a> ·
  <a href="#-비교표"><b>📊 비교표</b></a>
</p>

---

## ⚡ 빠른 설치

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# 이게 전부입니다. 에이전트가 방금 aha 모먼트를 경험했습니다.
```

---

## 🔥 뉴스

- **[04/01/2026]** **v0.2.0 출시**: 3단계 파이프라인 모드(Core / Standard / Enhanced), 트레이스 기반 진단, 인터페이스 검증 게이트, 개선된 컨텍스트 관리. **958개 테스트 통과.**
- **[04/01/2026]** [**v0.1.0 출시**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0): 6단계 거버넌스 파이프라인, 위험 패턴 매칭, YAML 헌법, 감사 트레일, 멀티 에이전트 프로파일, 비용 추적이 포함된 세션 영속성.

---

## 🤔 왜 *Aha* (**A**uto**Ha**rness)인가?

> LLM 훈련에서 ***aha* 모먼트**는 모델이 갑자기 추론을 배우는 순간입니다.
>
> 에이전트에게 ***aha* 모먼트**는 "데모용"에서 진정으로 신뢰할 수 있는 시스템으로 도약하는 순간입니다.

그 사이의 간극은 거대합니다: 컨텍스트 관리, 도구 거버넌스, 비용 제어, 관측성, 세션 영속성... 이것들이 장난감 수준과 실제 시스템을 구분하는 패턴입니다. 우리는 이것을 **하네스 엔지니어링**이라 부릅니다.

AutoHarness는 경량의 계층적 거버넌스 프레임워크로, **모든 에이전트가 자신만의 *aha* 모먼트를 경험할 수 있도록** 만들어졌습니다.

> **에이전트 = 모델 + 하네스.** 모델은 추론하고, 하네스는 나머지 모든 것을 담당합니다.

---

## 🚀 빠른 시작

```python
# 기존 LLM 클라이언트에 거버넌스 래핑 (2줄, 즉시 거버넌스)
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
response = client.chat.completions.create(
    model="gpt-5.4",
    messages=[{"role": "user", "content": "Refactor auth.py"}],
    tools=[{"type": "function", "function": {"name": "Bash", "description": "Run shell commands",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}],
)
```

```python
# 또는 풀 에이전트 루프 사용
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[더 많은 예시 →](features.md#cli)**

---

## ✨ 주요 기능

| 하네스 없이 | AutoHarness 적용 후 |
|:------------|:-------------------|
| 에이전트가 `rm -rf /`를 실행해도 아무도 막지 않음 | **6단계 파이프라인**이 차단하고, 로그를 남기고, 이유를 설명 |
| 토큰 한도를 넘어 컨텍스트 폭발 | **토큰 예산** + **트렁케이션**으로 컨텍스트 제어 |
| 어떤 도구 호출이 얼마나 비용이 드는지 알 수 없음 | **호출별 비용 귀속**과 모델 인식 가격 책정 |
| 프롬프트 인젝션이 그대로 통과 | **계층별 검증**: 입력 레일, 실행, 출력 레일 |
| 컴플라이언스를 위한 감사 트레일 없음 | **JSONL 감사**로 모든 결정을 완전한 출처와 함께 기록 |
| 모든 에이전트가 동일한 권한 세트 공유 | **멀티 에이전트 프로파일**로 역할 기반 거버넌스 |

### 핵심 아키텍처: 6단계 거버넌스 파이프라인

모든 도구 호출은 구조화된 파이프라인을 통과합니다:

```
1. 파싱 및 검증  →  2. 위험 분류  →  3. 권한 확인
4. 실행          →  5. 출력 소독  →  6. 감사 기록
```

내장 위험 패턴으로 위험한 작업, 시크릿 노출, 경로 탐색 등을 탐지합니다.

### 핵심 수치

```
6단계 거버넌스 파이프라인   ·  위험 패턴 매칭          ·  YAML 헌법
토큰 예산 관리             ·  멀티 에이전트 프로파일    ·  JSONL 감사 트레일
통합에 단 2줄              ·  벤더 종속 없음           ·  MIT 라이선스
```

---

## 🔧 파이프라인 모드

AutoHarness는 3가지 파이프라인 모드를 지원합니다. 필요에 맞는 거버넌스 수준을 선택하세요:

| 모드 | 파이프라인 | 컨텍스트 | 멀티 에이전트 | 사용 사례 |
|:-----|:----------|:---------|:-------------|:---------|
| **Core** | 6단계 | 토큰 예산 + 트렁케이션 | 단일 에이전트 | 경량 거버넌스 |
| **Standard** | 8단계 | + Microcompact + 트레이스 저장소 | 기본 프로파일 | 프로덕션 에이전트 |
| **Enhanced** | 14단계 | + LLM 요약 + 이미지 제거 | Fork / Swarm / Background | 최대 거버넌스 |

```python
# 헌법으로 모드 전환
# constitution.yaml
mode: core      # 또는 "standard" 또는 "enhanced"
```

```bash
# 또는 CLI로 전환
autoharness mode enhanced
```

> **Enhanced 모드가 기본값입니다.** 사용자에게 가장 강력한 거버넌스가 기본 제공됩니다. 최소 오버헤드를 원하면 Core로 전환하세요.

> **[전체 모드 비교 →](features.md#pipeline-modes)**

---

## 🖥️ CLI

```bash
autoharness init                          # 헌법 생성 (default/strict/soc2/hipaa/financial)
autoharness init --mode core              # 특정 파이프라인 모드로 생성
autoharness mode                          # 현재 파이프라인 모드 표시
autoharness mode enhanced                 # 파이프라인 모드 전환
autoharness validate constitution.yaml    # 헌법 파일 검증
autoharness check --stdin --format json   # 규칙에 대해 도구 호출 검사
autoharness audit summary                 # 감사 요약 보기
autoharness install --target claude-code  # Claude Code 훅으로 설치 (원커맨드)
autoharness export --format cursor        # 크로스 하네스 헌법 내보내기
```

---

## 📊 비교표

| 기능 | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:-----|:---:|:---:|:---:|:---:|
| 도구 거버넌스 파이프라인 | ✅ 6단계 (최대 14) | ❌ | ⚠️ 출력만 | ❌ |
| 컨텍스트 관리 | ✅ 멀티 레이어 | ❌ | ❌ | ⚠️ Trimming |
| 멀티 에이전트 프로파일 | ✅ | ✅ 그래프 기반 | ❌ | ⚠️ Handoff |
| 검증 (입력+출력) | ✅ | ❌ | ✅ Rails | ❌ |
| 트레이스 기반 진단 | ✅ | ❌ | ❌ | ❌ |
| 비용 귀속 | ✅ 호출별 | ❌ | ❌ | ❌ |
| 벤더 종속 | 없음 | LangChain | 없음 | OpenAI |
| 설정 난이도 | 2줄 | Graph DSL | RAIL XML | SDK |

---

## 🙏 감사의 글

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (Anthropic): Enhanced 모드의 일부 기능에 영감을 준 엔지니어링 패턴
- [Codex](https://github.com/openai/codex) (OpenAI): 컨텍스트 관리 설계에 참고가 된 컨텍스트 엔지니어링 사례

---

## 📌 인용

연구에서 AutoHarness를 사용하신 경우 다음과 같이 인용해 주세요:

```bibtex
@software{autoharness2026,
  title   = {AutoHarness: The Harness Engineering Framework for AI Agents},
  author  = {{AutoHarness Team}},
  year    = {2026},
  url     = {https://github.com/aiming-lab/AutoHarness},
  license = {MIT}
}
```

---

## ⚠️ 면책 조항

Enhanced 모드의 일부 아키텍처 결정은 2026년 3월 31일 Anthropic의 npm 레지스트리를 통해 의도치 않게 공개된 Claude Code 설계에 대한 공개 분석 및 커뮤니티 논의를 참고했습니다. Claude Code의 원본 소스 코드가 Anthropic의 지적 재산임을 인정합니다. AutoHarness는 Anthropic의 독점 코드를 포함, 재배포 또는 직접 번역하지 않습니다. Anthropic의 지적 재산권을 존중하며 관련 우려 사항에 신속히 대응하겠습니다 — [issue](https://github.com/aiming-lab/AutoHarness/issues) 또는 [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com) 로 연락해 주세요.

---

## 📄 라이선스

MIT. 자세한 내용은 [LICENSE](../LICENSE)를 참고하세요.
