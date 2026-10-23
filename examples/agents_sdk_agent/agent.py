"""Real LLM agent on the OpenAI Agents SDK, pointed at OpenRouter, using the environment's MCP server for tools.

Env: OPENROUTER_API_KEY (required), PROMPT=naive|careful (default careful), MODEL (OpenRouter id), PORT, HOST.
Tools are discovered over MCP Streamable HTTP at `<environment base url>/mcp`. MCP calls bypass `Recorder.tool`, so
tool events come from run hooks (one per environment call) and harness faults cannot be injected (`intercept_tools`
is "none"). The SDK's tracing export targets OpenAI and is disabled.
"""

import asyncio
import json
import os

from agents import (
    Agent,
    AsyncOpenAI,
    ModelResponse,
    OpenAIChatCompletionsModel,
    RunContextWrapper,
    RunHooks,
    Runner,
    Tool,
    set_tracing_disabled,
)
from agents.mcp import MCPServerStreamableHttp, MCPServerStreamableHttpParams

from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, Manifest
from examples.env_tools import (
    MAX_STEPS,
    OPENROUTER_URL,
    adapter_id,
    api_key,
    load_catalog,
    model_name,
    record_model_call,
    system_prompt,
)

set_tracing_disabled(disabled=True)


def build_model() -> OpenAIChatCompletionsModel:
    """One client per run: each `asyncio.run` uses a fresh event loop, and an AsyncOpenAI client binds to its first."""
    client = AsyncOpenAI(base_url=OPENROUTER_URL, api_key=api_key())
    return OpenAIChatCompletionsModel(model=model_name(), openai_client=client)


def _text(output: object) -> str:
    """The tool output as text: the SDK hands MCP results over as a str or as text content items."""
    if isinstance(output, dict):
        return str(output.get("text", ""))
    if isinstance(output, list):
        return "".join(_text(item) for item in output)
    return str(output)


def _is_error(output: object) -> bool:
    """Environment failures are `{"error": ...}` bodies; transport/SDK failures are formatted tool-error strings."""
    text = _text(output)
    if text.startswith("An error occurred"):
        return True
    try:
        body = json.loads(text)
    except ValueError:
        return False
    return isinstance(body, dict) and "error" in body


class EventHooks(RunHooks[None]):
    """Model-call usage plus exactly one tool event per environment call, recorded from the SDK's run hooks."""

    def __init__(self, rec: Recorder) -> None:
        self._rec = rec

    async def on_llm_end(self, context: RunContextWrapper[None], agent: Agent[None], response: ModelResponse) -> None:
        usage = response.usage
        record_model_call(self._rec, None, usage.input_tokens, usage.output_tokens, None)

    async def on_tool_start(self, context: RunContextWrapper[None], agent: Agent[None], tool: Tool) -> None:
        self._rec.emit("tool_requested", tool.name)

    async def on_tool_end(
        self, context: RunContextWrapper[None], agent: Agent[None], tool: Tool, result: object
    ) -> None:
        if _is_error(result):
            self._rec.emit("tool_failed", tool.name, error=_text(result)[:500])
        else:
            self._rec.emit("tool_completed", tool.name)


async def _run(req: InvokeRequest, rec: Recorder) -> str:
    base = req.environment.base_url.rstrip("/")
    params = MCPServerStreamableHttpParams(url=f"{base}/mcp", timeout=10)
    async with MCPServerStreamableHttp(name="environment", params=params, cache_tools_list=True) as server:
        agent = Agent(
            name="ops-agent", instructions=system_prompt(load_catalog(base)), mcp_servers=[server], model=build_model()
        )
        result = await Runner.run(agent, str(req.input.get("message", "")), max_turns=MAX_STEPS, hooks=EventHooks(rec))
    return str(result.final_output or "")


def handle(req: InvokeRequest, rec: Recorder) -> str:
    return asyncio.run(_run(req, rec))


if __name__ == "__main__":
    manifest = Manifest(
        adapter_id=adapter_id("agents-sdk-mcp"),
        language="python",
        framework="openai-agents-sdk+mcp",
        capabilities=Capabilities(observe="native_events", intercept_tools="none"),
    )
    serve(manifest, handle, port=int(os.environ.get("PORT", "7701")), host=os.environ.get("HOST", "127.0.0.1"))
