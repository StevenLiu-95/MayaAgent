"""Vision message conversion — no Maya / Qt required."""

from maya_agent.core.message_codec import message_from_dict, message_to_dict
from maya_agent.llm.anthropic_provider import AnthropicProvider
from maya_agent.llm.base import ChatMessage, ImageAttachment
from maya_agent.llm.google_provider import GoogleProvider
from maya_agent.llm.vision import model_supports_vision


class _Cfg:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)


def _img():
    return ImageAttachment(mime="image/jpeg", data_b64="aGVsbG8=", name="shot.jpg")


def test_vision_detect():
    cfg = _Cfg(
        {
            "providers.deepseek": {
                "vision_models": ["deepseek-v4-flash-vision-exp"],
            },
            "providers.google": {"vision": True},
            "providers.custom": {"vision_policy": "on"},
            "providers.openai": {"vision_policy": "off"},
            "providers.qwen": {},
        }
    )
    assert model_supports_vision("deepseek", "deepseek-v4-pro", cfg) is False
    assert model_supports_vision("deepseek", "deepseek-v4-flash-vision-exp", cfg) is True
    assert model_supports_vision("google", "gemini-2.0-flash", cfg) is True
    assert model_supports_vision("custom", "my-model", cfg) is True
    assert model_supports_vision("openai", "gpt-4o", cfg) is False
    assert model_supports_vision("qwen", "qwen-vl-max", cfg) is True
    assert model_supports_vision("qwen", "qwen-max", cfg) is False
    assert model_supports_vision("anthropic", "claude-sonnet-4-20250514", cfg) is True


def test_openai_parts():
    msg = ChatMessage(role="user", content="看这张图", images=[_img()])
    payload = msg.to_openai(include_images=True)
    assert isinstance(payload["content"], list)
    assert payload["content"][0]["type"] == "text"
    assert payload["content"][1]["type"] == "image_url"
    assert payload["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    plain = msg.to_openai(include_images=False)
    assert isinstance(plain["content"], str)
    assert "无法查看" in plain["content"]
    assert "看这张图" in plain["content"]


def test_anthropic_and_gemini():
    msg = ChatMessage(role="user", content="参考", images=[_img()])
    _system, anthropic = AnthropicProvider._convert_messages([msg], include_images=True)
    blocks = anthropic[0]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"]["media_type"] == "image/jpeg"

    _system, contents = GoogleProvider._convert([msg], include_images=True)
    parts = contents[0]["parts"]
    assert parts[0]["text"] == "参考"
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"

    _system, skipped = GoogleProvider._convert([msg], include_images=False)
    assert "inlineData" not in str(skipped)
    assert "无法查看" in skipped[0]["parts"][0]["text"]


def test_codec_roundtrip():
    msg = ChatMessage(role="user", content="hi", images=[_img()])
    again = message_from_dict(message_to_dict(msg))
    assert again.content == "hi"
    assert again.images and again.images[0].data_b64 == "aGVsbG8="
    assert again.images[0].name == "shot.jpg"
    bare = message_from_dict({"role": "user", "content": "only"})
    assert not bare.images


def test_tool_specs_vision_filter():
    from maya_agent.tools.registry import ensure_tools_loaded, tool_specs

    ensure_tools_loaded()
    names_on = {t.name for t in tool_specs(vision=True)}
    names_off = {t.name for t in tool_specs(vision=False)}
    assert "capture_viewport" in names_on
    assert "capture_viewport" not in names_off
    assert "get_scene_info" in names_off


def test_anthropic_merge_after_tools():
    from maya_agent.llm.base import ChatMessage, ImageAttachment

    msgs = [
        ChatMessage(role="user", content="看场景"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "capture_viewport", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(
            role="tool",
            content='{"ok":true}',
            name="capture_viewport",
            tool_call_id="c1",
        ),
        ChatMessage(
            role="user",
            content="[系统] 截图",
            images=[ImageAttachment(mime="image/jpeg", data_b64="aGVsbG8=", name="v.jpg")],
        ),
    ]
    _system, out = AnthropicProvider._convert_messages(msgs, include_images=True)
    roles = [m["role"] for m in out]
    # tool_result (user) + vision inject (user) must merge into one user turn
    assert roles == ["user", "assistant", "user"]
    last = out[-1]["content"]
    assert isinstance(last, list)
    assert any(b.get("type") == "image" for b in last)


if __name__ == "__main__":
    test_vision_detect()
    test_openai_parts()
    test_anthropic_and_gemini()
    test_codec_roundtrip()
    test_tool_specs_vision_filter()
    test_anthropic_merge_after_tools()
    print("ok")
