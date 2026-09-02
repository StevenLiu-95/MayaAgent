from maya_agent.llm.base import ChatMessage
from maya_agent.core.memory import ConversationMemory

m = ConversationMemory(limit=8)
m.add(ChatMessage(role="system", content="sys"))
m.add(ChatMessage(role="user", content="u1"))
m.add(
    ChatMessage(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "get_scene_info", "arguments": "{}"},
            }
        ],
    )
)
m.add(
    ChatMessage(
        role="tool",
        content='{"ok":true}',
        name="get_scene_info",
        tool_call_id="c1",
    )
)
m.add(ChatMessage(role="assistant", content="done1"))
for i in range(10):
    m.add(ChatMessage(role="user", content=f"u{i}"))
    m.add(ChatMessage(role="assistant", content=f"a{i}"))

out = m.as_list()
# orphan tool must be removed
m2 = ConversationMemory(limit=40)
m2.messages = [
    ChatMessage(role="system", content="s"),
    ChatMessage(role="tool", content="orphan", tool_call_id="x"),
    ChatMessage(role="user", content="hi"),
]
clean = m2.as_list()
assert clean[1].role == "user"
assert not any(x.role == "tool" for x in clean)

# incomplete trailing round
m3 = ConversationMemory(limit=40)
m3.add(ChatMessage(role="system", content="s"))
m3.add(ChatMessage(role="user", content="u"))
m3.add(
    ChatMessage(
        role="assistant",
        content="calling",
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "x", "arguments": "{}"},
            },
            {
                "id": "c2",
                "type": "function",
                "function": {"name": "y", "arguments": "{}"},
            },
        ],
    )
)
m3.add(ChatMessage(role="tool", content="r1", name="x", tool_call_id="c1"))
m3.drop_incomplete_tool_round()
assert m3.messages[-1].role == "assistant"
assert m3.messages[-1].content == "calling"
assert not m3.messages[-1].tool_calls

# as_list fills missing tool results for API
m4 = ConversationMemory(limit=40)
m4.messages = [
    ChatMessage(role="system", content="s"),
    ChatMessage(role="user", content="u"),
    ChatMessage(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "x", "arguments": "{}"},
            },
            {
                "id": "c2",
                "type": "function",
                "function": {"name": "y", "arguments": "{}"},
            },
        ],
    ),
    ChatMessage(role="tool", content="r1", name="x", tool_call_id="c1"),
]
api = m4.as_list()
tool_msgs = [x for x in api if x.role == "tool"]
assert len(tool_msgs) == 2
assert tool_msgs[1].tool_call_id == "c2"

print("memory sanitize OK")
