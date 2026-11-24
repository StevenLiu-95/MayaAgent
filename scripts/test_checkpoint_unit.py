"""Offline regression tests for the checkpoint system (no Maya required)."""

from __future__ import annotations

import copy
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maya_agent.core import checkpoint as cpmod  # noqa: E402
from maya_agent.core.chat_session import ChatSession, ProjectChatData  # noqa: E402
from maya_agent.core.memory import ConversationMemory  # noqa: E402
from maya_agent.core.message_codec import (  # noqa: E402
    message_from_dict,
    message_to_dict,
    messages_to_dicts,
)
from maya_agent.core.session_manager import SessionManager  # noqa: E402
from maya_agent.llm.base import ChatMessage  # noqa: E402
from maya_agent.utils.config import get_config  # noqa: E402


def _turn(mem: ConversationMemory, n: int, tools: bool = False) -> None:
    mem.add(ChatMessage(role="user", content=f"u{n}"))
    if tools:
        mem.add(
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": f"c{n}",
                        "type": "function",
                        "function": {"name": "t", "arguments": "{}"},
                    }
                ],
            )
        )
        mem.add(
            ChatMessage(role="tool", content="r", name="t", tool_call_id=f"c{n}")
        )
    mem.add(ChatMessage(role="assistant", content=f"a{n}"))


def test_seq_assignment_and_codec() -> None:
    mem = ConversationMemory(limit=40)
    mem.add(ChatMessage(role="system", content="sys"))
    _turn(mem, 1)
    seqs = [m.seq for m in mem.messages]
    assert seqs == [0, 1, 2], seqs
    assert mem.last_seq() == 2

    # codec round trip keeps seq; seq key only written when set
    d = message_to_dict(mem.messages[1])
    assert d["seq"] == 1
    assert "seq" not in message_to_dict(mem.messages[0])
    assert message_from_dict(d).seq == 1

    # extend keeps existing seq, assigns the rest
    other = ConversationMemory(limit=40)
    other.add(ChatMessage(role="system", content="s"))
    other.extend([copy.copy(m) for m in mem.messages if m.role != "system"])
    assert [m.seq for m in other.messages[1:]] == [1, 2]
    other.add(ChatMessage(role="user", content="next"))
    assert other.messages[-1].seq == 3


def test_legacy_memory_gets_sequential_seq() -> None:
    legacy = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    mem = ConversationMemory(limit=40)
    mem.load_from_serializable(legacy)
    assert [m.seq for m in mem.messages] == [0, 1, 2, 3]


def test_seq_survives_trim_and_drop_incomplete() -> None:
    mem = ConversationMemory(limit=6)
    mem.add(ChatMessage(role="system", content="sys"))
    for n in range(1, 8):
        _turn(mem, n)
    kept = [m.seq for m in mem.messages if m.role != "system"]
    assert kept == sorted(kept) and kept[-1] == 14, kept
    assert kept[0] > 1, "old messages must have been trimmed"
    # next seq continues after trimming (no reuse)
    mem.add(ChatMessage(role="user", content="more"))
    assert mem.messages[-1].seq == 15

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
    seq_before = m3.messages[-1].seq
    m3.add(ChatMessage(role="tool", content="r1", name="x", tool_call_id="c1"))
    m3.drop_incomplete_tool_round()
    assert m3.messages[-1].role == "assistant" and not m3.messages[-1].tool_calls
    assert m3.messages[-1].seq == seq_before


def test_truncate_memory_after_trim() -> None:
    mem = ConversationMemory(limit=8)
    mem.add(ChatMessage(role="system", content="sys"))
    for n in range(1, 4):
        _turn(mem, n, tools=(n == 2))
    cp_seq = mem.last_seq()
    for n in range(4, 12):
        _turn(mem, n)
    dicts = messages_to_dicts(mem.messages)
    cut = cpmod.truncate_memory_dicts(dicts, cp_seq)
    assert cut[0]["role"] == "system"
    assert all(d.get("seq", 0) <= cp_seq for d in cut if d["role"] != "system")
    assert len(cut) < len(dicts)
    # original untouched (deep copy)
    assert any(d.get("seq", 0) > cp_seq for d in dicts)

    # checkpoint older than everything still in memory -> only system remains
    only_sys = cpmod.truncate_memory_dicts(dicts, 0)
    assert [d["role"] for d in only_sys] == ["system"]


def test_truncate_blocks() -> None:
    blocks = [
        {"type": "user", "text": "a"},
        {"type": "assistant", "text": "b", "done": True},
        {"type": "checkpoint", "id": "c1", "name": "one"},
        {"type": "user", "text": "c"},
        {"type": "assistant", "text": "d", "done": True},
        {"type": "checkpoint", "id": "c2", "name": "two"},
    ]
    cut = cpmod.truncate_blocks(blocks, "c1")
    assert cut is not None and len(cut) == 3 and cut[-1]["id"] == "c1"
    assert cpmod.truncate_blocks(blocks, "nope") is None
    cut[0]["text"] = "changed"
    assert blocks[0]["text"] == "a"


def _make_manager(tmp: pathlib.Path):
    mgr = SessionManager.__new__(SessionManager)
    mgr.project = ProjectChatData(scene_path="")
    mgr.save = lambda: None  # no sidecar writes in tests
    return mgr


def _build_session(mgr: SessionManager, snap_dir: pathlib.Path) -> ChatSession:
    """3 turns, one checkpoint each, with real (fake) snapshot files."""
    sess = mgr.create_session("S", set_active=True, save_now=False)
    mem = ConversationMemory(limit=40)
    mem.add(ChatMessage(role="system", content="sys"))
    blocks = []
    for n in (1, 2, 3):
        _turn(mem, n)
        blocks.append({"type": "user", "text": f"u{n}"})
        blocks.append({"type": "assistant", "text": f"a{n}", "done": True})
        cp = cpmod.new_checkpoint(name=f"cp{n}", memory_seq=mem.last_seq())
        snap = snap_dir / f"{cp.id}.mb"
        snap.write_bytes(b"snap")
        cp.snapshot_path = str(snap)
        blocks.append(cpmod.make_block(cp))
        mgr.sync_session(sess.id, mem.messages, blocks, force=True)
        mgr.add_checkpoint(sess.id, cp)
    return sess


def test_rollback_and_branch_integrity() -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mayaagent_cp_"))
    old_dir = cpmod.snapshot_dir
    cpmod.snapshot_dir = lambda: tmp
    try:
        mgr = _make_manager(tmp)
        sess = _build_session(mgr, tmp)
        cps = [cpmod.Checkpoint.from_dict(c) for c in sess.checkpoints]
        assert [c.name for c in cps] == ["cp1", "cp2", "cp3"]
        assert [c.memory_seq for c in cps] == [2, 4, 6]

        # ---- branch from cp1: source untouched, snapshots shared
        src_blocks = copy.deepcopy(sess.ui_blocks)
        src_memory = copy.deepcopy(sess.memory)
        branch = mgr.branch_from(sess.id, cps[0].id)
        assert branch is not None and branch.id != sess.id
        assert mgr.project.active_session_id == branch.id
        assert branch.ui_blocks[-1].get("id") == cps[0].id
        assert len(branch.ui_blocks) == 3
        assert [c["id"] for c in branch.checkpoints] == [cps[0].id]
        seqs = [d.get("seq", 0) for d in branch.memory if d["role"] != "system"]
        assert seqs == [1, 2], seqs
        assert sess.ui_blocks == src_blocks and sess.memory == src_memory
        assert len(sess.checkpoints) == 3

        # deleting the branch must keep the snapshot the source still uses
        mgr.delete(branch.id)
        assert pathlib.Path(cps[0].snapshot_path).is_file()

        # ---- rollback to cp2: later data and cp3 snapshot are gone
        mgr.project.active_session_id = sess.id
        res = mgr.rollback_to(sess.id, cps[1].id)
        assert res is sess
        assert sess.ui_blocks[-1]["id"] == cps[1].id and len(sess.ui_blocks) == 6
        assert [c["id"] for c in sess.checkpoints] == [cps[0].id, cps[1].id]
        assert all(
            d.get("seq", 0) <= cps[1].memory_seq
            for d in sess.memory
            if d["role"] != "system"
        )
        assert pathlib.Path(cps[1].snapshot_path).is_file()
        assert not pathlib.Path(cps[2].snapshot_path).exists()
        # user/assistant counts match between dialogue and memory
        n_user_blocks = sum(1 for b in sess.ui_blocks if b["type"] == "user")
        n_user_mem = sum(1 for d in sess.memory if d["role"] == "user")
        assert n_user_blocks == n_user_mem == 2

        # unknown ids are rejected without touching anything
        assert mgr.rollback_to(sess.id, "missing") is None
        assert mgr.branch_from(sess.id, "missing") is None

        # ---- rename updates both the checkpoint and its block
        assert mgr.rename_checkpoint(sess.id, cps[1].id, "  milestone  ")
        assert sess.get_checkpoint(cps[1].id)["name"] == "milestone"
        assert sess.ui_blocks[-1]["name"] == "milestone"

        # ---- clearing the session releases every snapshot
        mgr.reset_active()
        assert sess.checkpoints == [] and sess.ui_blocks == []
        assert not list(tmp.glob("*.mb"))
    finally:
        cpmod.snapshot_dir = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_checkpoint_max_drops_oldest_snapshot() -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mayaagent_cpmax_"))
    old_dir = cpmod.snapshot_dir
    cpmod.snapshot_dir = lambda: tmp
    cfg = get_config()
    old_max = cfg.get("agent.checkpoint_max", 30)
    cfg.set("agent.checkpoint_max", 2)
    try:
        mgr = _make_manager(tmp)
        sess = _build_session(mgr, tmp)
        raw = sess.checkpoints
        assert [bool(c["snapshot_path"]) for c in raw] == [False, True, True]
        assert len(list(tmp.glob("*.mb"))) == 2
        # checkpoint without snapshot can still be branched, not "restored"
        cp1 = mgr.get_checkpoint(sess.id, raw[0]["id"])
        assert cp1 is not None and not cp1.has_snapshot
        assert mgr.branch_from(sess.id, cp1.id) is not None
    finally:
        cfg.set("agent.checkpoint_max", old_max)
        cpmod.snapshot_dir = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_session_roundtrip_and_legacy() -> None:
    legacy = ChatSession.from_dict(
        {"id": "x", "title": "old", "memory": [], "ui_blocks": []}
    )
    assert legacy.checkpoints == []
    assert "checkpoints" not in legacy.to_dict()

    cp = cpmod.new_checkpoint(name="n", memory_seq=5, plan={"title": "p"})
    cp.snapshot_path = "/tmp/x.mb"
    cp.scene_meta = {"units": {"linear": "cm"}}
    s = ChatSession.create("t")
    s.checkpoints.append(cp.to_dict())
    data = ProjectChatData(scene_path="", sessions=[s]).to_dict()
    back = ProjectChatData.from_dict(data).sessions[0]
    cp2 = cpmod.Checkpoint.from_dict(back.checkpoints[0])
    assert cp2.id == cp.id and cp2.name == "n" and cp2.memory_seq == 5
    assert cp2.plan == {"title": "p"}
    assert cp2.scene_meta == {"units": {"linear": "cm"}}
    assert cp2.snapshot_path == "/tmp/x.mb"


def test_scene_ops_degrade_outside_maya() -> None:
    path, meta, err = cpmod.snapshot_scene("abc")
    assert path == "" and err
    ok, err = cpmod.restore_scene_safe("/nonexistent.mb", {})
    assert not ok and err


def test_scene_hook_suppression() -> None:
    from maya_agent.plugin import scene_hooks

    assert not scene_hooks.hooks_suppressed()
    with scene_hooks.suppress_scene_hooks():
        assert scene_hooks.hooks_suppressed()
        with scene_hooks.suppress_scene_hooks():
            assert scene_hooks.hooks_suppressed()
        assert scene_hooks.hooks_suppressed()
    assert not scene_hooks.hooks_suppressed()


def test_panel_separator_logic() -> None:
    try:
        from maya_agent.ui.qt_bind import QtWidgets
    except Exception:
        print("  (skip panel test: no Qt binding)")
        return
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from maya_agent.ui.chat.checkpoint_bar import CheckpointBar, CheckpointOffer
    from maya_agent.ui.chat.panel import ChatPanel, TurnSeparator

    panel = ChatPanel()
    events = []
    panel.set_checkpoint_handlers(
        on_rollback=lambda i: events.append(("rb", i)),
        on_branch=lambda i: events.append(("br", i)),
        on_rename=lambda i, n: events.append(("rn", i, n)),
        on_add=lambda: events.append(("add",)),
        can_rollback=lambda i: i != "nosnap",
    )

    def kinds():
        return [type(w).__name__ for w in panel._widgets]

    panel.add_user("hi")
    panel.begin_assistant()
    panel.finish_assistant("hello")
    panel.add_checkpoint("c1", "cp1")
    panel.add_user("again")
    # checkpoint bar replaces the turn separator
    assert "TurnSeparator" not in kinds(), kinds()
    assert panel.blocks[-2]["type"] == "checkpoint"

    # manual offer is replaced by the bar, and dropped on the next user send
    panel.begin_assistant()
    panel.finish_assistant("ok")
    panel.add_checkpoint_offer()
    assert isinstance(panel._widgets[-1], CheckpointOffer)
    panel.add_user("third")
    assert not any(isinstance(w, CheckpointOffer) for w in panel._widgets)
    assert kinds().count("TurnSeparator") == 1  # offer skipped -> normal separator

    # restore from blocks keeps bars and does not add separators around them
    blocks = [
        {"type": "user", "text": "a"},
        {"type": "assistant", "text": "b", "done": True},
        {"type": "checkpoint", "id": "c1", "name": "x"},
        {"type": "user", "text": "c"},
        {"type": "assistant", "text": "d", "done": True},
        {"type": "checkpoint", "id": "nosnap", "name": "y"},
    ]
    panel.restore_blocks(blocks)
    bars = panel._checkpoint_bars()
    assert [b.cp_id for b in bars] == ["c1", "nosnap"]
    assert bars[0]._rollback_btn.isEnabled() and not bars[1]._rollback_btn.isEnabled()
    k = kinds()
    i = [j for j, w in enumerate(panel._widgets) if isinstance(w, CheckpointBar)][0]
    assert not isinstance(panel._widgets[i - 1], TurnSeparator)
    assert not isinstance(panel._widgets[i + 1], TurnSeparator)
    assert panel.blocks == blocks

    # busy state disables actions; callbacks wired
    panel.set_checkpoint_actions_enabled(False)
    assert not any(b._rollback_btn.isEnabled() or b._branch_btn.isEnabled() for b in bars)
    panel.set_checkpoint_actions_enabled(True)
    bars[0]._rollback_btn.click()
    bars[0]._branch_btn.click()
    bars[0]._begin_rename()
    bars[0]._name_edit.setText("renamed")
    bars[0]._commit_rename()
    assert ("rb", "c1") in events and ("br", "c1") in events
    assert ("rn", "c1", "renamed") in events
    assert panel.blocks[2]["name"] == "renamed"
    app.processEvents()


TESTS = [
    test_seq_assignment_and_codec,
    test_legacy_memory_gets_sequential_seq,
    test_seq_survives_trim_and_drop_incomplete,
    test_truncate_memory_after_trim,
    test_truncate_blocks,
    test_rollback_and_branch_integrity,
    test_checkpoint_max_drops_oldest_snapshot,
    test_session_roundtrip_and_legacy,
    test_scene_ops_degrade_outside_maya,
    test_scene_hook_suppression,
    test_panel_separator_logic,
]


if __name__ == "__main__":
    for fn in TESTS:
        fn()
        print(f"OK  {fn.__name__}")
    print("checkpoint unit tests OK")
