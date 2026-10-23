"""Real LLM agent: plain OpenAI SDK tool-calling loop against OpenRouter.

Env: OPENROUTER_API_KEY (required), PROMPT=naive|careful (default careful), MODEL (OpenRouter id), PORT, HOST.
"""

import json
import os

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, Manifest
from examples.env_tools import MAX_STEPS, OPENROUTER_URL, EnvTools, adapter_id, api_key, model_name, record_model_call

client = OpenAI(base_url=OPENROUTER_URL, api_key=api_key())


def handle(req: InvokeRequest, rec: Recorder) -> str:
    with EnvTools(req.environment.base_url, rec) as api:
        return _run(api, req, rec)


def _run(api: EnvTools, req: InvokeRequest, rec: Recorder) -> str:
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": api.system_prompt},
        {"role": "user", "content": str(req.input.get("message", ""))},
    ]
    for _ in range(MAX_STEPS):
        completion = client.chat.completions.create(model=model_name(), messages=messages, tools=api.schemas)  # ty: ignore[invalid-argument-type]
        choice = completion.choices[0]
        usage = completion.usage
        cost = getattr(usage, "cost", None) if usage else None
        record_model_call(
            rec,
            choice.finish_reason,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
            cost if isinstance(cost, int | float) else None,
        )
        message = choice.message
        messages.append(message.model_dump(exclude_none=True))
        if not message.tool_calls:
            return message.content or ""
        for call in message.tool_calls:
            if call.type != "function":
                continue
            result = api.call(call.function.name, json.loads(call.function.arguments or "{}"))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    raise RuntimeError(f"no final answer after {MAX_STEPS} model calls")


if __name__ == "__main__":
    manifest = Manifest(
        adapter_id=adapter_id("openai"),
        language="python",
        framework="openai-sdk",
        capabilities=Capabilities(observe="native_events", intercept_tools="declared_only"),
    )
    serve(manifest, handle, port=int(os.environ.get("PORT", "7401")), host=os.environ.get("HOST", "127.0.0.1"))
