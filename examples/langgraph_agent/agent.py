"""Real LLM agent on LangGraph + langchain-openai (OpenRouter), with checkpoint/resume/fork.

Env: OPENROUTER_API_KEY (required), PROMPT=naive|careful (default careful), MODEL (OpenRouter id), PORT, HOST.
Checkpoints live in a process-wide in-memory saver keyed by thread_id = trial_id; the graph is rebuilt per
invocation so tools bind to that invocation's environment catalog and Recorder.
"""

import os
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RunnableConfig
from pydantic import SecretStr
from typing_extensions import TypedDict

from agentlab.adapter import Recorder, serve
from agentlab.protocol import Capabilities, InvokeRequest, Manifest
from examples.env_tools import MAX_STEPS, OPENROUTER_URL, EnvTools, adapter_id, api_key, model_name, record_model_call


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


CHECKPOINTER = InMemorySaver()
llm = ChatOpenAI(model=model_name(), base_url=OPENROUTER_URL, api_key=SecretStr(api_key()))


def build_graph(api: EnvTools, rec: Recorder) -> CompiledStateGraph:
    model = llm.bind_tools(api.schemas)
    system = SystemMessage(api.system_prompt)

    def agent(state: State) -> dict[str, list[BaseMessage]]:
        reply = model.invoke([system, *state["messages"]])
        meta = reply.response_metadata
        usage = meta.get("token_usage") or {}
        cost = usage.get("cost")
        record_model_call(
            rec,
            meta.get("finish_reason"),
            (reply.usage_metadata or {}).get("input_tokens", 0),
            (reply.usage_metadata or {}).get("output_tokens", 0),
            cost if isinstance(cost, int | float) else None,
        )
        return {"messages": [reply]}

    def tools(state: State) -> dict[str, list[BaseMessage]]:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        results: list[BaseMessage] = [
            ToolMessage(api.call(call["name"], call["args"]), tool_call_id=call["id"] or "") for call in last.tool_calls
        ]
        return {"messages": results}

    def route(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    return (
        StateGraph(State)  # ty: ignore[invalid-argument-type]  # ty can't see typing_extensions TypedDict bound
        .add_node("agent", agent)
        .add_node("tools", tools)
        .add_edge(START, "agent")
        .add_conditional_edges("agent", route)
        .add_edge("tools", "agent")
        .compile(checkpointer=CHECKPOINTER)
    )


def handle(req: InvokeRequest, rec: Recorder) -> str:
    with EnvTools(req.environment.base_url, rec) as api:
        return _run(build_graph(api, rec), req, rec)


def _run(graph: CompiledStateGraph, req: InvokeRequest, rec: Recorder) -> str:
    if req.resume_from:  # fork: continue the original thread from that checkpoint with no new input
        thread_id, checkpoint_id = req.resume_from.trial_id, req.resume_from.checkpoint_id
        graph_input = None
    else:
        thread_id, checkpoint_id = req.trial_id, None
        graph_input = {"messages": [("user", str(req.input.get("message", "")))]}
    configurable = {"thread_id": thread_id, **({"checkpoint_id": checkpoint_id} if checkpoint_id else {})}
    config: RunnableConfig = {"configurable": configurable, "recursion_limit": 2 * MAX_STEPS + 1}

    # A checkpoint chunk streams once its superstep (and so its tool calls) has finished, keeping events ordered.
    for chunk in graph.stream(graph_input, config, stream_mode="checkpoints"):
        saved = chunk["config"]["configurable"]
        rec.emit("checkpoint_saved", checkpoint_id=saved["checkpoint_id"], thread_id=saved["thread_id"])
    final = graph.get_state({"configurable": {"thread_id": thread_id}}).values["messages"][-1]
    return str(final.content)


if __name__ == "__main__":
    manifest = Manifest(
        adapter_id=adapter_id("langgraph"),
        language="python",
        framework="langgraph",
        capabilities=Capabilities(
            observe="native_events", intercept_tools="declared_only", checkpoint=True, resume=True, fork=True
        ),
    )
    serve(manifest, handle, port=int(os.environ.get("PORT", "7501")), host=os.environ.get("HOST", "127.0.0.1"))
