<p align="center">
  <img src="../images/logo.png" alt="AutoHarness Logo" width="800"/>
</p>

<h2 align="center">「Aha」— AutoHarness: Automated Harness Engineering for AI Agents</h2>

<h3 align="center"><em>すべてのエージェントに <b>aha</b> モーメントを — モデルは推論を、私たちが残りすべてをハーネスします。</em></h3>

<p align="center">
  <img src="../images/poster.png" width="90%" alt="AutoHarness Poster">
</p>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="#-クイックスタート"><img src="https://img.shields.io/badge/Tests-958%20passed-brightgreen?logo=pytest&logoColor=white" alt="958 Tests Passed"></a>
  <a href="https://github.com/aiming-lab/AutoHarness"><img src="https://img.shields.io/badge/GitHub-AutoHarness-181717?logo=github" alt="GitHub"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/Code%20Style-Ruff-000000?logo=ruff&logoColor=white" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/Type%20Check-mypy-blue?logo=python&logoColor=white" alt="mypy"></a>
</p>

<p align="center">
  <a href="../README.md">🇬🇧 English</a> ·
  <a href="README_CN.md">🇨🇳 简体中文</a> ·
  🇯🇵 日本語 ·
  <a href="README_KO.md">🇰🇷 한국어</a> ·
  <a href="README_ES.md">🇪🇸 Español</a> ·
  <a href="README_FR.md">🇫🇷 Français</a> ·
  <a href="README_DE.md">🇩🇪 Deutsch</a> ·
  <a href="README_PT.md">🇵🇹 Português</a> ·
  <a href="README_RU.md">🇷🇺 Русский</a>
</p>

<p align="center">
  <a href="https://autoharness.dev"><b>📖 ドキュメント</b></a> ·
  <a href="#-クイックスタート"><b>🚀 クイックスタート</b></a> ·
  <a href="#-使い方"><b>💡 使い方</b></a> ·
  <a href="#-謝辞"><b>🤝 謝辞</b></a>
</p>

---

## ⚡ クイックインストール

```bash
git clone https://github.com/aiming-lab/AutoHarness.git
cd AutoHarness && pip install -e .
```

```python
from openai import OpenAI
from autoharness import AutoHarness

client = AutoHarness.wrap(OpenAI())
# これだけです。あなたのエージェントは aha モーメントを迎えました。
```

---

## 🔥 ニュース

- **[04/01/2026]** **v0.2.0 リリース**：3段階パイプラインモード（Core / Standard / Enhanced）、トレースベースの診断、インターフェース検証ゲート、コンテキスト管理の改善。**テスト958件合格。**
- **[04/01/2026]** [**v0.1.0 リリース**](https://github.com/aiming-lab/AutoHarness/releases/tag/v0.1.0)：6ステップガバナンスパイプライン、リスクパターンマッチング、YAMLコンスティテューション、監査証跡、マルチエージェントプロファイル、コスト追跡付きセッション永続化。

---

## 🤔 なぜ *Aha*（**A**uto**Ha**rness）なのか？

> LLMの訓練において、***aha* モーメント**とはモデルが突然推論を学び取る瞬間のことです。
>
> エージェントにとっての ***aha* モーメント**とは、「デモなら動く」レベルから真に信頼できるレベルへと飛躍する瞬間です。

その間のギャップは膨大です：コンテキスト管理、ツールガバナンス、コスト制御、可観測性、セッション永続化……これらこそが、おもちゃと本番システムを隔てるエンジニアリングパターンです。私たちはこれを**ハーネスエンジニアリング**と呼んでいます。

AutoHarness は軽量かつ階層的なガバナンスフレームワークです。**すべてのエージェントが *aha* モーメントを迎えられるように。**

> **Agent = Model + Harness。** モデルが推論し、ハーネスがそれ以外のすべてを担います。

---

## 🚀 クイックスタート

```python
# 任意のLLMクライアントをラップ（2行で即座にガバナンス）
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
# またはフルエージェントループを使用
from autoharness import AgentLoop

loop = AgentLoop(model="gpt-5.4", constitution="constitution.yaml")
result = loop.run("Fix the failing tests in auth.py")
```

> **[その他の例 →](features.md#cli)**

---

## ✨ 何が手に入るのか

| ハーネスなし | AutoHarnessあり |
|:------------|:----------------|
| エージェントが `rm -rf /` を実行しても誰も止めない | **6ステップパイプライン**がブロックし、ログに記録し、理由を説明 |
| コンテキストがトークン上限を超えて破綻する | **トークン予算** + **トランケーション**でコンテキストを制御下に |
| どのツール呼び出しにいくらかかったか不明 | **呼び出し単位のコスト帰属**、モデル対応の価格設定 |
| プロンプトインジェクションが素通りする | **多層バリデーション**：入力レール → 実行 → 出力レール |
| コンプライアンスに必要な監査証跡がない | **JSONL監査ログ**がすべての判断を完全な来歴とともに記録 |
| エージェント全員が同一の権限セット | **マルチエージェントプロファイル**によるロールベースのガバナンス |

### コアアーキテクチャ：6ステップガバナンスパイプライン

すべてのツール呼び出しが構造化されたパイプラインを通過します：

```
1. パース＆検証  →  2. リスク分類  →  3. 権限チェック
4. 実行          →  5. 出力サニタイズ →  6. 監査ログ
```

組み込みのリスクパターンが、危険な操作、シークレットの露出、パストラバーサルなどを検出します。

### 数字で見る

```
6ステップガバナンスパイプライン  ·  リスクパターンマッチング      ·  YAMLコンスティテューション
トークン予算管理                ·  マルチエージェントプロファイル  ·  JSONL監査証跡
2行で統合                      ·  ベンダーロックインなし          ·  MITライセンス
```

---

## 🔧 パイプラインモード

AutoHarnessは3段階のパイプラインモードをサポートしています。ニーズに合ったガバナンスレベルを選択してください：

| モード | パイプライン | コンテキスト | マルチエージェント | ユースケース |
|:-------|:------------|:------------|:------------------|:------------|
| **Core** | 6ステップ | トークン予算 + トランケーション | シングルエージェント | 軽量ガバナンス |
| **Standard** | 8ステップ | + Microcompact + トレースストア | 基本プロファイル | 本番エージェント |
| **Enhanced** | 14ステップ | + LLM要約 + 画像ストリッピング | Fork / Swarm / Background | 最高レベルのガバナンス |

```python
# コンスティテューションでモードを切り替え
# constitution.yaml
mode: core      # または "standard" または "enhanced"
```

```bash
# またはCLIで切り替え
autoharness mode enhanced
```

> **Enhancedがデフォルトモードです。** 最強のガバナンスをすぐに利用可能。最小限のオーバーヘッドが必要な場合はCoreモードに切り替えてください。

> **[モード比較の詳細 →](features.md#pipeline-modes)**

---

## 🖥️ CLI

```bash
autoharness init                          # コンスティテューション生成（default/strict/soc2/hipaa/financial）
autoharness init --mode core              # 特定のパイプラインモードで生成
autoharness mode                          # 現在のパイプラインモードを表示
autoharness mode enhanced                 # パイプラインモードを切り替え
autoharness validate constitution.yaml    # コンスティテューションファイルを検証
autoharness check --stdin --format json   # ルールに対してツール呼び出しをチェック
autoharness audit summary                 # 監査サマリーを表示
autoharness install --target claude-code  # Claude Codeフックとしてインストール（ワンコマンド）
autoharness export --format cursor        # クロスハーネスコンスティテューションをエクスポート
```

---

## 📊 比較表

| 機能 | AutoHarness | LangGraph | Guardrails AI | OpenAI SDK |
|:-----------|:---:|:---:|:---:|:---:|
| ツールガバナンスパイプライン | ✅ 6ステップ（最大14） | ❌ | ⚠️ 出力のみ | ❌ |
| コンテキスト管理 | ✅ マルチレイヤー | ❌ | ❌ | ⚠️ トリミング |
| マルチエージェントプロファイル | ✅ | ✅ グラフ | ❌ | ⚠️ ハンドオフ |
| バリデーション（入力+出力） | ✅ | ❌ | ✅ Rails | ❌ |
| トレースベース診断 | ✅ | ❌ | ❌ | ❌ |
| コスト帰属 | ✅ 呼び出し単位 | ❌ | ❌ | ❌ |
| ベンダーロックイン | なし | LangChain | なし | OpenAI |
| セットアップ | 2行 | Graph DSL | RAIL XML | SDK |

---

## 🙏 謝辞

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)（Anthropic）：一部のエンジニアリングパターンがEnhancedモードの機能設計にインスピレーションを与えました
- [Codex](https://github.com/openai/codex)（OpenAI）：コンテキストエンジニアリングの実践が、コンテキスト管理の設計に参考となりました

---

## 📌 引用

研究でAutoHarnessを使用する場合は、以下を引用してください：

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

## ⚠️ 免責事項

Enhanced モードの一部のアーキテクチャ上の決定は、2026年3月31日に Anthropic の npm レジストリを通じて意図せず公開された Claude Code の設計に関する公開分析およびコミュニティでの議論を参考にしています。Claude Code のオリジナルソースコードは Anthropic の知的財産であることを認識しています。AutoHarness は Anthropic の専有コードを含んでおらず、再配布や直接的な翻訳も行っていません。Anthropic の知的財産権を尊重し、懸念事項には迅速に対応いたします — [issue](https://github.com/aiming-lab/AutoHarness/issues) または [autoharness.aha@gmail.com](mailto:autoharness.aha@gmail.com) でご連絡ください。

---

## 📄 ライセンス

MIT — 詳細は [LICENSE](../LICENSE) をご覧ください。
