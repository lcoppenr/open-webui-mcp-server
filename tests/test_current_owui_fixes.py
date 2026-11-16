"""Tests for the fixes that match Open WebUI 0.13 (models, settings, tool servers, auth)."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from openwebui_mcp import client as client_module
from openwebui_mcp.client import OpenWebUIClient, OpenWebUIRouteError
from openwebui_mcp.redact import REDACTED, redact


def _http_404(path: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"https://webui.example{path}")
    return httpx.HTTPStatusError(
        "404", request=request, response=httpx.Response(404, request=request)
    )


# --- environment ------------------------------------------------------------


def test_webui_env_names_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENWEBUI_URL", raising=False)
    monkeypatch.delenv("OPENWEBUI_API_KEY", raising=False)
    monkeypatch.setenv("WEBUI_URL", "http://open-webui:8080/")
    monkeypatch.setenv("WEBUI_API_KEY", "sk-test")

    client = OpenWebUIClient()

    assert client.base_url == "http://open-webui:8080"
    assert client.api_key == "sk-test"


def test_openwebui_env_names_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWEBUI_URL", "https://a.example")
    monkeypatch.setenv("WEBUI_URL", "https://b.example")

    assert OpenWebUIClient().base_url == "https://a.example"


# --- wrong routes fail loudly -------------------------------------------------


def _client_with_transport(monkeypatch: pytest.MonkeyPatch, handler) -> OpenWebUIClient:
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", factory)
    return OpenWebUIClient(base_url="https://webui.example", api_key="sk-test")


@pytest.mark.asyncio
async def test_html_reply_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text="<!doctype html>"
        ),
    )

    with pytest.raises(OpenWebUIRouteError, match="/api/v1/models/war-hammer"):
        await client.get("/api/v1/models/war-hammer")


@pytest.mark.asyncio
async def test_json_reply_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_transport(
        monkeypatch, lambda request: httpx.Response(200, json={"ok": True})
    )

    assert await client.get("/api/version") == {"ok": True}


# --- identity ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_user_uses_route_open_to_api_keys() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(return_value={"workspace": {"models": True}})

    result = await client.get_current_user(api_key="sk-test")

    client.get.assert_awaited_once_with("/api/v1/users/permissions", "sk-test")
    assert result["permissions"] == {"workspace": {"models": True}}
    assert "token" not in result


# --- models -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_details_returns_saved_record() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(return_value={"id": "war-hammer-40000", "params": {"temperature": 1}})

    result = await client.get_model_details("war-hammer-40000", api_key="t")

    assert result["stored_record"] is True
    assert client.get.await_args.args[0] == "/api/v1/models/model?id=war-hammer-40000"


@pytest.mark.asyncio
async def test_model_details_falls_back_to_live_entry_for_unedited_connection_model() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(
        side_effect=[
            _http_404("/api/v1/models/model"),
            {"data": [{"id": "other"}, {"id": "studio.research", "name": "Research"}]},
        ]
    )

    result = await client.get_model_details("studio.research", api_key="t")

    assert result["stored_record"] is False
    assert result["effective"]["name"] == "Research"
    assert client.get.await_args_list[1].args[0] == "/api/models"


@pytest.mark.asyncio
async def test_model_details_unknown_model_raises() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(side_effect=[_http_404("/api/v1/models/model"), {"data": []}])

    with pytest.raises(ValueError, match="not found"):
        await client.get_model_details("nope", api_key="t")


@pytest.mark.asyncio
async def test_model_history_route() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(return_value={"data": []})

    await client.get_model_history("studio.chat", page=2, api_key="t")

    assert client.get.await_args.args[0] == "/api/v1/models/model/history?id=studio.chat&page=2"


@pytest.mark.asyncio
async def test_update_keeps_every_field_not_named() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    stored = {
        "id": "studio.chat",
        "name": "Studio Chat",
        "base_model_id": None,
        "meta": {"description": "d", "capabilities": {"vision": False}, "toolIds": ["a"]},
        "params": {"system": "prompt", "temperature": 0.7, "num_ctx": 32768},
        "access_grants": [{"principal": "all"}],
        "is_active": True,
    }
    client.get = AsyncMock(return_value=json.loads(json.dumps(stored)))
    client.post = AsyncMock(return_value={"id": "studio.chat"})

    await client.update_model(
        "studio.chat", params={"temperature": 0.2}, meta={"description": "new"}, api_key="t"
    )

    path, _ = client.post.await_args.args
    body = client.post.await_args.kwargs["json"]
    assert path == "/api/v1/models/model/update"
    assert body["params"] == {"system": "prompt", "temperature": 0.2, "num_ctx": 32768}
    assert body["meta"] == {
        "description": "new",
        "capabilities": {"vision": False},
        "toolIds": ["a"],
    }
    assert body["name"] == "Studio Chat"
    assert body["base_model_id"] is None
    assert body["access_grants"] == [{"principal": "all"}]


@pytest.mark.asyncio
async def test_first_edit_of_connection_model_creates_its_record() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(
        side_effect=[
            _http_404("/api/v1/models/model"),
            {"data": [{"id": "studio.research", "name": "studio.research"}]},
        ]
    )
    client.post = AsyncMock(return_value={"id": "studio.research"})

    await client.update_model("studio.research", params={"num_ctx": 65536}, api_key="t")

    path, _ = client.post.await_args.args
    body = client.post.await_args.kwargs["json"]
    assert path == "/api/v1/models/create"
    assert body["base_model_id"] is None
    assert body["params"] == {"num_ctx": 65536}
    assert client.get.await_args_list[1].args[0] == "/api/models/base"


# --- settings ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_values_reports_unstored_keys() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(return_value={"ui.default_models": "studio.chat"})

    result = await client.get_config_values(["ui.default_models", "ui.missing"], api_key="t")

    assert result == {"values": {"ui.default_models": "studio.chat"}, "not_stored": ["ui.missing"]}


@pytest.mark.asyncio
async def test_config_namespace_route() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(return_value={})

    await client.get_config_namespace("rag", api_key="t")

    assert client.get.await_args.args[0] == "/api/v1/configs/namespace/rag"


@pytest.mark.asyncio
async def test_set_config_sends_only_named_keys_and_reads_back() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(
        side_effect=[
            {"ui.default_models": "a", "rag.top_k": 3, "openai.api_keys": ["sk-x"]},
            {"ui.default_models": "b", "rag.top_k": 3, "openai.api_keys": ["sk-x"]},
        ]
    )
    client.post = AsyncMock(return_value={})

    result = await client.set_config_values({"ui.default_models": "b"}, api_key="t")

    client.post.assert_awaited_once_with(
        "/api/v1/configs/import", "t", json={"config": {"ui.default_models": "b"}}
    )
    assert result["changed"] == {"ui.default_models": {"before": "a", "after": "b"}}


@pytest.mark.asyncio
async def test_set_config_refuses_unknown_key() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(return_value={"ui.default_models": "a"})
    client.post = AsyncMock()

    with pytest.raises(ValueError, match="ui.defualt_models"):
        await client.set_config_values({"ui.defualt_models": "b"}, api_key="t")
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_config_refuses_mfa_keys() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock()
    client.post = AsyncMock()

    with pytest.raises(ValueError, match="browser session"):
        await client.set_config_values({"auth.mfa.enable": True}, api_key="t")
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_config_raises_when_value_not_kept() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(side_effect=[{"rag.top_k": 3}, {"rag.top_k": 3}])
    client.post = AsyncMock(return_value={})

    with pytest.raises(RuntimeError, match="rag.top_k"):
        await client.set_config_values({"rag.top_k": 5}, api_key="t")


# --- tool servers -----------------------------------------------------------


def _servers() -> list[dict]:
    return [
        {
            "url": "http://mcphub/a",
            "path": "",
            "type": "mcp",
            "auth_type": "bearer",
            "key": "secret-a",
            "config": {"enable": False},
            "info": {"id": "FamilyVault", "name": "FamilyVault", "description": "x"},
        },
        {
            "url": "http://mcphub/b",
            "path": "",
            "type": "mcp",
            "auth_type": "bearer",
            "key": "secret-b",
            "config": {"enable": True},
            "info": {"id": "Search", "name": "Search"},
        },
    ]


def _saved(connections: list[dict]) -> list[dict]:
    """What Open WebUI stores: the form's defaults filled in."""
    return [{"forward_cookies": False, "headers": None, **c} for c in connections]


@pytest.mark.asyncio
async def test_tool_server_update_changes_only_one_entry() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    expected = _servers()
    expected[1]["info"]["description"] = "web search"
    client.get = AsyncMock(
        side_effect=[
            {"TOOL_SERVER_CONNECTIONS": _servers()},
            {"TOOL_SERVER_CONNECTIONS": _saved(expected)},
        ]
    )
    client.post = AsyncMock(return_value={})

    result = await client.update_tool_server("Search", description="web search", api_key="t")

    posted = client.post.await_args.kwargs["json"]["TOOL_SERVER_CONNECTIONS"]
    assert posted == expected
    assert posted[0]["key"] == "secret-a"
    assert result["server"]["info"]["description"] == "web search"


@pytest.mark.asyncio
async def test_tool_server_update_flags_other_entries_changing() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    drifted = _servers()
    drifted[0]["config"]["enable"] = True
    client.get = AsyncMock(
        side_effect=[{"TOOL_SERVER_CONNECTIONS": _servers()}, {"TOOL_SERVER_CONNECTIONS": drifted}]
    )
    client.post = AsyncMock(return_value={})

    with pytest.raises(RuntimeError, match="Other tool server"):
        await client.update_tool_server("Search", enabled=False, api_key="t")


@pytest.mark.asyncio
async def test_tool_server_update_unknown_id() -> None:
    client = OpenWebUIClient(base_url="https://webui.example")
    client.get = AsyncMock(return_value={"TOOL_SERVER_CONNECTIONS": _servers()})

    with pytest.raises(ValueError, match="Nope"):
        await client.update_tool_server("Nope", enabled=True, api_key="t")


# --- credentials never reach the caller --------------------------------------


def test_redact_masks_credentials_and_keeps_settings() -> None:
    data = {
        "openai.api_keys": ["sk-1", ""],
        "openai.api_base_urls": ["http://studio"],
        "auth.enable_api_keys": True,
        "auth.api_key.allowed_endpoints": "/api/models",
        "rag.web.search.brave_search_api_key": "brv",
        "TOOL_SERVER_CONNECTIONS": _servers(),
        "params": {"max_tokens": 100},
        "headers": {"X-Api": "v"},
    }

    out = redact(data)

    assert out["openai.api_keys"] == [REDACTED, ""]
    assert out["openai.api_base_urls"] == ["http://studio"]
    assert out["auth.enable_api_keys"] is True
    assert out["auth.api_key.allowed_endpoints"] == "/api/models"
    assert out["rag.web.search.brave_search_api_key"] == REDACTED
    assert out["TOOL_SERVER_CONNECTIONS"][0]["key"] == REDACTED
    assert out["TOOL_SERVER_CONNECTIONS"][0]["url"] == "http://mcphub/a"
    assert out["params"] == {"max_tokens": 100}
    assert out["headers"] == {"X-Api": REDACTED}
    assert data["openai.api_keys"] == ["sk-1", ""]  # original untouched


# --- MCP surface --------------------------------------------------------------


def _tools(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENWEBUI_URL", "https://webui.example")
    from openwebui_mcp.main import mcp

    return asyncio.run(mcp.list_tools())


def test_every_tool_is_annotated_read_or_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from openwebui_mcp.main import ADDITIVE_WRITE_TOOLS, READ_TOOLS

    tools = {tool.name: tool for tool in _tools(monkeypatch)}

    assert READ_TOOLS <= tools.keys()
    assert ADDITIVE_WRITE_TOOLS <= tools.keys()
    for name, tool in tools.items():
        hints = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        assert hints["readOnlyHint"] is (name in READ_TOOLS), name
        if name.startswith(("get_", "list_", "search_")):
            assert name in READ_TOOLS, name
        if name.startswith(("update_", "set_", "delete_")):
            assert hints["destructiveHint"] is True, name


def test_new_tools_are_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    names = {tool.name for tool in _tools(monkeypatch)}

    assert {
        "get_model_history",
        "get_config_namespace",
        "get_config_values",
        "set_config_values",
        "update_tool_server",
    } <= names


@pytest.mark.asyncio
async def test_update_model_tool_passes_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWEBUI_URL", "https://webui.example")
    monkeypatch.setenv("OPENWEBUI_API_KEY", "sk-test")
    from fastmcp import Client

    from openwebui_mcp import main

    fake = AsyncMock()
    fake.update_model = AsyncMock(return_value={"id": "m"})
    fake.create_note = AsyncMock(return_value={"id": "note"})
    monkeypatch.setattr(main, "get_client", lambda: fake)

    async with Client(main.mcp) as mcp_client:
        await mcp_client.call_tool(
            "update_model",
            {
                "params": {
                    "model_id": "m",
                    "temperature": 0.3,
                    "params_patch": {"function_calling": "native", "temperature": 9},
                    "meta_patch": {"capabilities": {"vision": False}},
                }
            },
        )

    kwargs = fake.update_model.await_args.kwargs
    assert kwargs["params"] == {"function_calling": "native", "temperature": 0.3}
    assert kwargs["meta"] == {"capabilities": {"vision": False}}


@pytest.mark.asyncio
async def test_tool_server_reads_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWEBUI_URL", "https://webui.example")
    monkeypatch.setenv("OPENWEBUI_API_KEY", "sk-test")
    from fastmcp import Client

    from openwebui_mcp import main

    fake = AsyncMock()
    fake.get_tool_servers = AsyncMock(return_value={"TOOL_SERVER_CONNECTIONS": _servers()})
    monkeypatch.setattr(main, "get_client", lambda: fake)

    async with Client(main.mcp) as mcp_client:
        result = await mcp_client.call_tool("get_tool_servers", {})

    text = json.dumps(result.structured_content)
    assert "secret-a" not in text and "secret-b" not in text
