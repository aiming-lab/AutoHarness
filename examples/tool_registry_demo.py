#!/usr/bin/env python3
"""Tool Registry Demo — register, discover, and orchestrate tools.

Shows how to:
  1. Create a ToolRegistry and register tools with schemas
  2. Configure concurrency and deferred loading flags
  3. Use ToolSearch for keyword-based tool discovery
  4. Use ToolMatcher for hook routing patterns

Run:
    python examples/tool_registry_demo.py
"""

from autoharness.tools import (
    ToolDefinition,
    ToolMatcher,
    ToolRegistry,
    ToolSearch,
)


def main() -> None:
    print("=" * 60)
    print("AutoHarness Tool Registry Demo")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Create a ToolRegistry and register tools with full schemas.
    # ------------------------------------------------------------------
    registry = ToolRegistry()

    # Register a read-only, concurrency-safe tool (always loaded)
    registry.register(ToolDefinition(
        name="Read",
        description="Read a file from the local filesystem",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to read"},
            },
            "required": ["file_path"],
        },
        is_read_only=True,
        is_concurrency_safe=True,
        always_load=True,
        search_hint="read file contents",
    ))

    # Register a destructive tool
    registry.register(ToolDefinition(
        name="Bash",
        description="Execute a shell command",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
            },
            "required": ["command"],
        },
        is_destructive=True,
        always_load=True,
        search_hint="run shell command terminal",
    ))

    # Register deferred tools (not loaded until discovered via ToolSearch)
    registry.register(ToolDefinition(
        name="WebFetch",
        description="Fetch content from a URL",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
        should_defer=True,
        search_hint="fetch download web page URL HTTP",
    ))

    registry.register(ToolDefinition(
        name="NotebookEdit",
        description="Edit a Jupyter notebook cell",
        input_schema={
            "type": "object",
            "properties": {
                "notebook": {"type": "string"},
                "cell_index": {"type": "integer"},
                "new_source": {"type": "string"},
            },
            "required": ["notebook", "cell_index", "new_source"],
        },
        should_defer=True,
        search_hint="jupyter notebook cell edit",
        aliases=["notebook_edit", "edit_notebook"],
    ))

    print(f"\n1. Registered {len(registry)} tools")
    print(f"   Immediate (always loaded): {[t.name for t in registry.list_immediate()]}")
    print(f"   Deferred (loaded on demand): {[t.name for t in registry.list_deferred()]}")

    # ------------------------------------------------------------------
    # 2. Look up tools by name or alias.
    # ------------------------------------------------------------------
    print("\n2. Tool lookup:")
    tool = registry.get("Bash")
    print(f"   get('Bash') -> {tool.name}: destructive={tool.is_destructive}")

    tool = registry.get("notebook_edit")  # Alias lookup
    print(f"   get('notebook_edit') -> {tool.name} (via alias)")

    print(f"   'Read' in registry -> {'Read' in registry}")
    print(f"   'FakeBot' in registry -> {'FakeBot' in registry}")

    # ------------------------------------------------------------------
    # 3. Generate API schemas for the Anthropic tools parameter.
    # ------------------------------------------------------------------
    print("\n3. API schemas (immediate tools only):")
    schemas = registry.to_api_schemas(include_deferred=False)
    for schema in schemas:
        print(f"   {schema['name']}: {schema['description'][:50]}...")

    # ------------------------------------------------------------------
    # 4. Use ToolSearch to discover deferred tools by keyword.
    #
    # This is how the model discovers tools it needs on-demand.
    # The ToolSearch tool is available in the model's tool list.
    # ------------------------------------------------------------------
    search = ToolSearch(registry)

    print("\n4. ToolSearch — keyword discovery of deferred tools:")

    results = search.search("jupyter notebook")
    print(f"   search('jupyter notebook') -> {[r['name'] for r in results]}")

    results = search.search("fetch web URL")
    print(f"   search('fetch web URL') -> {[r['name'] for r in results]}")

    results = search.search("compile rust")  # No match
    print(f"   search('compile rust') -> {[r['name'] for r in results]} (no match)")

    # ------------------------------------------------------------------
    # 5. Use ToolMatcher for hook routing.
    #
    # ToolMatcher determines which tools a hook should apply to.
    # Supports exact names, alternation (|), wildcards (*), and
    # prefix patterns.
    # ------------------------------------------------------------------
    print("\n5. ToolMatcher — hook routing patterns:")

    # Match any tool
    m = ToolMatcher("*")
    print(f"   ToolMatcher('*').matches('Bash') -> {m.matches('Bash')}")
    print(f"   ToolMatcher('*').matches('Read') -> {m.matches('Read')}")

    # Match specific tools
    m = ToolMatcher("Bash|Edit|Write")
    print(f"   ToolMatcher('Bash|Edit|Write').matches('Bash') -> {m.matches('Bash')}")
    print(f"   ToolMatcher('Bash|Edit|Write').matches('Read') -> {m.matches('Read')}")

    # Prefix matching
    m = ToolMatcher("Web*")
    print(f"   ToolMatcher('Web*').matches('WebFetch') -> {m.matches('WebFetch')}")
    print(f"   ToolMatcher('Web*').matches('WebSearch') -> {m.matches('WebSearch')}")
    print(f"   ToolMatcher('Web*').matches('Bash') -> {m.matches('Bash')}")

    # ------------------------------------------------------------------
    # 6. Collect tool prompt contributions.
    # ------------------------------------------------------------------
    print("\n6. Tool prompt contributions:")

    # Add a prompt contribution to a tool
    def read_prompt() -> str:
        return "Always use absolute paths. Never use relative paths."

    read_tool = registry.get("Read")
    read_tool.prompt_fn = read_prompt  # type: ignore

    prompts = registry.get_tool_prompts()
    for name, prompt in prompts.items():
        print(f"   {name}: {prompt}")

    print("\nDone.")


if __name__ == "__main__":
    main()
