"""MCP (Streamable HTTP) face of an environment: `/env/{env_id}/mcp` serves the same tools as the HTTP routes and
runs them through the same executor, so MCP calls reach the ledger, faults and idempotency identically."""

import json
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from agentlab.environment import catalog

if TYPE_CHECKING:
    from agentlab.fixture import Fixture, FixturePool


class EnvironmentMcp:
    """One stateless MCP server for every live environment; the environment is picked from the URL per request."""

    def __init__(self, pool: "FixturePool") -> None:
        self.pool = pool
        server = Server("agentlab-environment", on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        self.sessions = StreamableHTTPSessionManager(server, stateless=True, json_response=True)

    def lifespan(self) -> AbstractAsyncContextManager[None]:
        return self.sessions.run()

    def mount(self, app: FastAPI) -> None:
        app.router.routes.append(Route("/env/{env_id}/mcp", endpoint=self))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            self.pool.get(scope["path_params"]["env_id"])
        except KeyError:
            await JSONResponse({"detail": "unknown environment"}, status_code=404)(scope, receive, send)
            return
        await self.sessions.handle_request(scope, receive, send)

    def _fixture(self, ctx: ServerRequestContext) -> "Fixture":
        assert ctx.request is not None
        return self.pool.get(ctx.request.path_params["env_id"])

    async def _list_tools(self, ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        tools = catalog(self._fixture(ctx).spec).tools
        return ListToolsResult(
            tools=[Tool(name=t.name, description=t.description, input_schema=t.parameters) for t in tools]
        )

    async def _call_tool(self, ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        status, body = await run_in_threadpool(self._fixture(ctx).call, params.name, params.arguments or {})
        return CallToolResult(content=[TextContent(text=json.dumps(body))], is_error=status >= 400)
