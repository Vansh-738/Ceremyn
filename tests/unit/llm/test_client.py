import pytest

from alphaquant.config import Settings
from alphaquant.llm.client import ClaudeClient
from alphaquant.llm.exceptions import LLMProviderError
from tests.unit.llm.conftest import FakeAnthropic, FakeContentBlock, FakeMessage, FakeSDKStream


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_from_settings_requires_api_key() -> None:
    with pytest.raises(LLMProviderError):
        ClaudeClient.from_settings(make_settings())


def test_from_settings_builds_client_with_api_key() -> None:
    settings = make_settings(anthropic={"api_key": "demo-key"})
    client = ClaudeClient.from_settings(settings)
    assert client is not None


async def test_stream_accumulates_text_deltas() -> None:
    final = FakeMessage(content=[FakeContentBlock(type="text", text="hello world")])
    fake = FakeAnthropic([FakeSDKStream(["hel", "lo wo", "rld"], final)])
    client = ClaudeClient(fake, model="claude-sonnet-5")

    async with client.stream(system="sys", messages=[{"role": "user", "content": "hi"}]) as stream:
        text = "".join([delta async for delta in stream.text_deltas()])
        result = await stream.final()

    assert text == "hello world"
    assert result.text == "hello world"
    assert result.tool_uses == ()


async def test_stream_extracts_tool_use_blocks() -> None:
    final = FakeMessage(
        content=[
            FakeContentBlock(type="text", text="checking risk..."),
            FakeContentBlock(type="tool_use", id="t1", name="get_risk_decisions", input={"n": 5}),
        ],
        stop_reason="tool_use",
    )
    fake = FakeAnthropic([FakeSDKStream([], final)])
    client = ClaudeClient(fake, model="claude-sonnet-5")

    async with client.stream(system="sys", messages=[]) as stream:
        async for _ in stream.text_deltas():
            pass
        result = await stream.final()

    assert result.stop_reason == "tool_use"
    assert len(result.tool_uses) == 1
    assert result.tool_uses[0].name == "get_risk_decisions"
    assert result.tool_uses[0].input == {"n": 5}


async def test_stream_passes_model_and_tools_through() -> None:
    final = FakeMessage(content=[FakeContentBlock(type="text", text="ok")])
    fake = FakeAnthropic([FakeSDKStream([], final)])
    client = ClaudeClient(fake, model="claude-sonnet-5")

    tools = [{"name": "get_orders", "description": "...", "input_schema": {}}]
    async with client.stream(system="sys", messages=[], tools=tools) as stream:
        async for _ in stream.text_deltas():
            pass
        await stream.final()

    assert fake.messages.calls[0]["model"] == "claude-sonnet-5"
    assert fake.messages.calls[0]["tools"] == tools


async def test_stream_wraps_sdk_failure_on_entry() -> None:
    fake = FakeAnthropic()
    fake.messages.fail_next(RuntimeError("connection reset"))
    client = ClaudeClient(fake, model="claude-sonnet-5")

    with pytest.raises(LLMProviderError):
        async with client.stream(system="sys", messages=[]):
            pass


async def test_stream_wraps_failure_mid_iteration() -> None:
    final = FakeMessage(content=[])
    fake = FakeAnthropic(
        [FakeSDKStream(["partial"], final, fail_mid_stream=RuntimeError("dropped connection"))]
    )
    client = ClaudeClient(fake, model="claude-sonnet-5")

    with pytest.raises(LLMProviderError):
        async with client.stream(system="sys", messages=[]) as stream:
            async for _ in stream.text_deltas():
                pass


async def test_stream_wraps_failure_on_final_message() -> None:
    final = FakeMessage(content=[])
    fake = FakeAnthropic([FakeSDKStream([], final, fail_final=RuntimeError("timeout"))])
    client = ClaudeClient(fake, model="claude-sonnet-5")

    with pytest.raises(LLMProviderError):
        async with client.stream(system="sys", messages=[]) as stream:
            async for _ in stream.text_deltas():
                pass
            await stream.final()
