"""Real LLM customer-ops agent on the OpenAI Agents SDK, pointed at OpenRouter's chat-completions endpoint.

Env: OPENROUTER_API_KEY (required), PROMPT=naive|careful (default careful), MODEL (OpenRouter id), PORT, HOST.
The SDK's tracing export targets OpenAI and is disabled; tools reuse the shared schemas and `RefundApi`.
"""

import json
import os
from typing import Any

from agents import (
    Agent,
    AsyncOpenAI,
    FunctionTool,
    ModelResponse,
    OpenAIChatCompletionsModel,
    RunContextWrapper,
    RunHooks,
    Runner,
    Tool,
    set_tracing_disabled,
)

from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, JsonObject, Manifest
from examples.refund_api import (
    MAX_STEPS,
    OPENROUTER_URL,
    TOOL_SCHEMAS,
    RefundApi,
    adapter_id,
    api_key,
    load_prompt,
    model_name,
    prompt_name,
    record_model_call,
)

set_tracing_disabled(disabled=True)


def build_model() -> OpenAIChatCompletionsModel:
    """One client per run: `Runner.run_sync` uses a fresh event loop, and an AsyncOpenAI client binds to its first."""
    client = AsyncOpenAI(base_url=OPENROUTER_URL, api_key=api_key())
    return OpenAIChatCompletionsModel(model=model_name(), openai_client=client)


class ModelCallHooks(RunHooks[None]):
    def __init__(self, rec: Recorder) -> None:
        self._rec = rec

    async def on_llm_end(self, context: RunContextWrapper[None], agent: Agent[None], response: ModelResponse) -> None:
        usage = response.usage
        record_model_call(self._rec, None, usage.input_tokens, usage.output_tokens, None)


def build_tools(api: RefundApi) -> list[Tool]:
    def make(name: str, description: str, parameters: JsonObject) -> FunctionTool:
        async def invoke(_: Any, arguments: str) -> str:  # noqa: ANN401 - SDK callback signature
            return api.run_tool(name, json.loads(arguments or "{}"))

        return FunctionTool(
            name=name,
            description=description,
            params_json_schema=parameters,
            on_invoke_tool=invoke,
            strict_json_schema=False,  # strict mode would force the optional arguments to be required
        )

    return [make(**schema["function"]) for schema in TOOL_SCHEMAS]  # ty: ignore[invalid-argument-type]


def handle(req: InvokeRequest, rec: Recorder) -> str:
    with RefundApi(req.environment.base_url, rec) as api:
        agent = Agent(
            name="customer-ops", instructions=load_prompt(prompt_name()), tools=build_tools(api), model=build_model()
        )
        result = Runner.run_sync(
            agent, str(req.input.get("message", "")), max_turns=MAX_STEPS, hooks=ModelCallHooks(rec)
        )
        return str(result.final_output or "")


if __name__ == "__main__":
    manifest = Manifest(
        adapter_id=adapter_id("agents-sdk"),
        language="python",
        framework="openai-agents-sdk",
        capabilities=Capabilities(observe="native_events", intercept_tools="declared_only"),
    )
    serve(manifest, handle, port=int(os.environ.get("PORT", "7701")), host=os.environ.get("HOST", "127.0.0.1"))
