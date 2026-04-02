# Build a Custom Agent

This guide shows how to build a custom agent using AutoHarness's components.

## Using AgentLoop with custom tools

```python
from autoharness import AgentLoop, ToolDefinition
import subprocess

# Define a custom tool
def run_tests(test_path: str = "tests/") -> str:
    result = subprocess.run(
        ["python", "-m", "pytest", test_path, "-x", "-q"],
        capture_output=True, text=True, timeout=120,
    )
    return result.stdout + result.stderr

test_tool = ToolDefinition(
    name="RunTests",
    description="Run pytest on the specified test path",
    input_schema={
        "type": "object",
        "properties": {
            "test_path": {"type": "string", "default": "tests/"},
        },
    },
    is_read_only=True,
    execute=run_tests,
)

# Create the loop with custom tools
loop = AgentLoop(
    model="claude-sonnet-4-6",
    tools=[test_tool],
    constitution="constitution.yaml",
)

result = loop.run("Run the tests and fix any failures")
```

## Step-by-step custom loop

For full control over the agent loop, use `step()`:

```python
from autoharness import AgentLoop

loop = AgentLoop(model="claude-sonnet-4-6")
messages = [{"role": "user", "content": "Analyze the project structure"}]

for i in range(50):  # Custom iteration limit
    messages, should_continue = loop.step(messages)

    # Custom logic between steps
    if not should_continue:
        break

    # Inspect the latest response
    last_msg = messages[-1]
    if last_msg["role"] == "assistant":
        print(f"Step {i}: assistant responded")

# Extract final text
final = messages[-1]["content"]
```

## Custom LLM provider

Use any LLM by providing a callback:

```python
import openai

def openai_callback(model, messages, tools, max_tokens):
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=[{"type": "function", "function": t} for t in tools] if tools else None,
        max_tokens=max_tokens,
    )
    choice = response.choices[0]
    content = []
    if choice.message.content:
        content.append({"type": "text", "text": choice.message.content})
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.function.name,
                "input": json.loads(tc.function.arguments),
            })
    return {
        "content": content,
        "stop_reason": "tool_use" if choice.message.tool_calls else "end_turn",
        "usage": {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        },
    }

loop = AgentLoop(
    model="gpt-4o",
    llm_callback=openai_callback,
)
```

## Registering prompt sections

Add custom sections to the system prompt:

```python
from autoharness import system_prompt_section

loop = AgentLoop(model="claude-sonnet-4-6")

# Static section (cached)
loop.prompt_registry.register_static(
    system_prompt_section(
        "project_context",
        lambda: "This is a Python web application using FastAPI and SQLAlchemy.",
    )
)
```

## Combining subsystems manually

For maximum flexibility, wire subsystems together yourself:

```python
from autoharness import (
    Constitution,
    ToolGovernancePipeline,
    ToolRegistry,
    TokenBudget,
)
from autoharness.core.types import ToolCall

# Set up governance
constitution = Constitution.load("constitution.yaml")
pipeline = ToolGovernancePipeline(constitution, project_dir=".")

# Evaluate a tool call
tc = ToolCall(tool_name="Bash", tool_input={"command": "ls -la"})
decision = pipeline.evaluate(tc)

if decision.action == "allow":
    # Execute the tool
    ...
elif decision.action == "deny":
    print(f"Blocked: {decision.reason}")
```

## Related pages

- [Agent Loop](../concepts/agent-loop.md) -- how the built-in loop works
- [Tool System](../concepts/tools.md) -- tool registration details
- [Governance Pipeline](../concepts/governance.md) -- the 14-step pipeline
