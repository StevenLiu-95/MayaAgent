# -*- coding: utf-8 -*-
"""Offline regression tests for risk/tech-debt fixes (no Maya required).

Run: python scripts/test_risk_fixes_unit.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import threading
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_run_on_main_thread_never_reexecutes_on_error() -> None:
    """P0: a raising callback must run once, not twice (old fallback re-ran it)."""
    from maya_agent.utils import maya_compat

    calls = []
    errors = []

    def boom() -> None:
        calls.append(1)
        raise ValueError("boom")

    fake_maya = types.ModuleType("maya")
    fake_utils = types.ModuleType("maya.utils")
    fake_utils.executeInMainThreadWithResult = lambda fn: fn()
    fake_maya.utils = fake_utils

    old_maya = sys.modules.get("maya")
    old_utils = sys.modules.get("maya.utils")
    old_flag = maya_compat._IN_MAYA
    sys.modules["maya"] = fake_maya
    sys.modules["maya.utils"] = fake_utils
    maya_compat._IN_MAYA = True
    try:
        def worker() -> None:
            try:
                maya_compat.run_on_main_thread(boom)
            except ValueError:
                errors.append(1)

        t = threading.Thread(target=worker)
        t.start()
        t.join()
    finally:
        maya_compat._IN_MAYA = old_flag
        if old_maya is None:
            sys.modules.pop("maya", None)
        else:
            sys.modules["maya"] = old_maya
        if old_utils is None:
            sys.modules.pop("maya.utils", None)
        else:
            sys.modules["maya.utils"] = old_utils

    assert errors == [1], "exception should propagate"
    assert len(calls) == 1, f"callback ran {len(calls)} times (expected 1)"


def test_executor_confirms_on_main_thread() -> None:
    """P0: destructive off-main-thread tools must marshal their confirm dialog."""
    from maya_agent.core import executor as ex
    from maya_agent.tools.registry import ToolResult, ensure_tools_loaded, get_tool

    ensure_tools_loaded()
    reg = get_tool("delete_path")
    assert reg is not None and reg.destructive and not reg.main_thread

    state = {"marshalled": 0, "confirmed": 0}
    old_romt = ex.run_on_main_thread
    old_run_tool = ex.run_tool
    old_get_config = ex.get_config

    class FakeCfg:
        def get(self, key, default=None):
            return default

    def fake_romt(fn):
        state["marshalled"] += 1
        return fn()

    def fake_run_tool(name, args):
        return ToolResult(ok=True, message="stub")

    ex.run_on_main_thread = fake_romt
    ex.run_tool = fake_run_tool
    ex.get_config = lambda: FakeCfg()
    try:
        exe = ex.ToolExecutor(
            confirm_callback=lambda name, args: (
                state.__setitem__("confirmed", state["confirmed"] + 1) or True
            )
        )
        result = exe.execute("delete_path", '{"path": "C:/definitely/not/here"}')
    finally:
        ex.run_on_main_thread = old_romt
        ex.run_tool = old_run_tool
        ex.get_config = old_get_config

    assert result.ok is True
    assert state["confirmed"] == 1, "confirm callback should run once"
    assert state["marshalled"] >= 1, "confirm path must go through run_on_main_thread"


def test_web_tools_are_off_main_thread() -> None:
    """P1: web tools blocked the Maya UI for up to 7 x 20 s HTTP calls."""
    from maya_agent.tools.registry import ensure_tools_loaded, get_tool

    ensure_tools_loaded()
    for name in (
        "web_search",
        "fetch_webpage",
        "search_images",
        "fetch_image",
        "fetch_images",
    ):
        reg = get_tool(name)
        assert reg is not None, f"missing tool {name}"
        assert reg.main_thread is False, f"{name} must run off the Maya main thread"


def test_config_save_user_keeps_cloud_sections() -> None:
    """P1: tripo/hunyuan/web settings were dropped by the save whitelist."""
    import maya_agent.utils.config as cfgmod

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="mayaagent_cfg_"))
    settings = tmpdir / "settings.json"
    old_path = cfgmod.user_config_path
    old_secrets = cfgmod.user_secrets_path
    cfgmod.user_config_path = lambda: settings
    cfgmod.user_secrets_path = lambda: tmpdir / "secrets.json"
    try:
        cfg = cfgmod.Config()
        cfg.set("tripo.enabled", False)
        cfg.set("hunyuan.region", "ap-shanghai")
        cfg.set("web.max_images", 2)
        cfg.save_user()
        saved = json.loads(settings.read_text(encoding="utf-8"))
        assert saved["tripo"]["enabled"] is False, "tripo.enabled not persisted"
        assert saved["hunyuan"]["region"] == "ap-shanghai", "hunyuan.region not persisted"
        assert saved["web"]["max_images"] == 2, "web.max_images not persisted"

        reloaded = cfgmod.Config()
        assert reloaded.get("tripo.enabled") is False
        assert reloaded.get("hunyuan.region") == "ap-shanghai"
        assert reloaded.get("web.max_images") == 2
    finally:
        cfgmod.user_config_path = old_path
        cfgmod.user_secrets_path = old_secrets


def test_session_store_writes_atomically() -> None:
    """P1: a crash mid-write must not truncate the chat sidecar."""
    from maya_agent.core import session_store
    from maya_agent.core.chat_session import ChatSession, ProjectChatData

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="mayaagent_sidecar_"))
    scene = tmpdir / "shot.ma"
    target = tmpdir / "shot.ma.mayaagent.json"
    tmp_path = target.with_suffix(target.suffix + ".tmp")

    old_storage = session_store.storage_path
    session_store.storage_path = lambda scene_path=None: target
    try:
        project = ProjectChatData(
            scene_path=str(scene), sessions=[ChatSession.create("hello")]
        )
        session_store.save_project(project, str(scene))
        assert target.is_file() and not tmp_path.exists()
        before = target.read_text(encoding="utf-8")
        assert "hello" in before

        old_dump = session_store.json.dump

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        session_store.json.dump = boom
        try:
            try:
                session_store.save_project(project, str(scene))
                raise AssertionError("expected save failure")
            except RuntimeError:
                pass
        finally:
            session_store.json.dump = old_dump

        assert target.read_text(encoding="utf-8") == before, "existing sidecar was damaged"
        assert not tmp_path.exists(), "temporary file left behind"
    finally:
        session_store.storage_path = old_storage


def test_undo_never_consumes_user_operation() -> None:
    """P1: undo_last() must inspect the stack before calling cmds.undo()."""
    from maya_agent.core import undo as undo_mod

    class FakeCmds:
        def __init__(self, names):
            self.names = list(names)
            self.undo_calls = 0

        def undoInfo(self, **kwargs):
            if kwargs.get("query") and kwargs.get("state"):
                return True
            if kwargs.get("query") and kwargs.get("undoName"):
                return self.names[0] if self.names else ""
            return None

        def undo(self):
            self.undo_calls += 1
            if not self.names:
                raise RuntimeError("nothing to undo")
            self.names.pop(0)

    fake_maya = types.ModuleType("maya")
    old_in_maya = undo_mod.in_maya
    old_romt = undo_mod.run_on_main_thread
    saved_cmds = sys.modules.get("maya.cmds")
    saved_maya = sys.modules.get("maya")
    undo_mod.in_maya = lambda: True
    undo_mod.run_on_main_thread = lambda fn: fn()
    fake_maya.cmds = None
    try:
        # (a) user operation on top: nothing may be undone
        cmds_a = FakeCmds(["move_user_object", "MayaAgentTurn"])
        sys.modules["maya"] = fake_maya
        sys.modules["maya.cmds"] = cmds_a
        fake_maya.cmds = cmds_a
        result = undo_mod.UndoTurnManager().undo_last()
        assert result["ok"] is False, result
        assert cmds_a.undo_calls == 0, "a normal user edit was undone"
        assert cmds_a.names == ["move_user_object", "MayaAgentTurn"]

        # (b) whole-turn chunk on top: undo exactly one step
        cmds_b = FakeCmds(["MayaAgentTurn", "move_user_object"])
        sys.modules["maya.cmds"] = cmds_b
        fake_maya.cmds = cmds_b
        result = undo_mod.UndoTurnManager().undo_last()
        assert result["ok"] is True and result["steps"] == 1, result
        assert cmds_b.names == ["move_user_object"]

        # (c) per-tool chunk before the turn chunk: undo both, stop there
        cmds_c = FakeCmds(["MayaAgent_create_primitive", "MayaAgentTurn", "user_op"])
        sys.modules["maya.cmds"] = cmds_c
        fake_maya.cmds = cmds_c
        result = undo_mod.UndoTurnManager().undo_last()
        assert result["ok"] is True and result["steps"] == 2, result
        assert cmds_c.names == ["user_op"]
    finally:
        undo_mod.in_maya = old_in_maya
        undo_mod.run_on_main_thread = old_romt
        if saved_cmds is None:
            sys.modules.pop("maya.cmds", None)
        else:
            sys.modules["maya.cmds"] = saved_cmds
        if saved_maya is None:
            sys.modules.pop("maya", None)
        else:
            sys.modules["maya"] = saved_maya


def test_cancel_checker_contextvar() -> None:
    """P1: cancellation must be visible inside tool side threads."""
    from maya_agent.core import tool_progress

    assert tool_progress.is_cancel_requested() is False
    token = tool_progress.push_cancel_checker(lambda: True)
    try:
        assert tool_progress.is_cancel_requested() is True
    finally:
        tool_progress.reset_cancel_checker(token)
    assert tool_progress.is_cancel_requested() is False


def test_cloud_wait_aborts_on_cancel() -> None:
    """P1: cloud polling loops must stop promptly instead of running 600 s."""
    from maya_agent.core import tool_progress
    from maya_agent.tools.hunyuan_client import HunyuanClient, HunyuanError
    from maya_agent.tools.meshy_client import MeshyClient, MeshyError
    from maya_agent.tools.tripo_client import TripoClient, TripoError

    meshy = object.__new__(MeshyClient)
    meshy.wait_timeout = 600.0
    meshy.poll_interval = 5.0
    meshy.get = lambda kind, task_id: ({"status": "PENDING", "progress": 0}, None)

    tripo = object.__new__(TripoClient)
    tripo.wait_timeout = 600.0
    tripo.poll_interval = 5.0
    tripo.get_task = lambda task_id: {"status": "running", "progress": 0}

    hunyuan = object.__new__(HunyuanClient)
    hunyuan.wait_timeout = 600.0
    hunyuan.poll_interval = 5.0
    hunyuan.get_job = lambda kind, job_id: {"Status": "RUN"}

    token = tool_progress.push_cancel_checker(lambda: True)
    try:
        cases = (
            ("Meshy", lambda: meshy.wait("text-to-3d", "t1", timeout=60), MeshyError),
            ("Tripo", lambda: tripo.wait("t1", timeout=60), TripoError),
            ("Hunyuan", lambda: hunyuan.wait("pro", "j1", timeout=60), HunyuanError),
        )
        for label, call, exc in cases:
            try:
                call()
                raise AssertionError(f"{label} wait() did not abort on cancel")
            except exc as e:
                assert "已请求停止" in str(e), f"{label}: {e}"
    finally:
        tool_progress.reset_cancel_checker(token)


def test_tools_panel_import_has_color_token() -> None:
    """P1: tools tab crashed with NameError: COLOR_TEXT."""
    try:
        from maya_agent.ui.settings import tools_panel
    except ImportError as e:  # no Qt binding in this environment
        print(f"  (skipped: {e})")
        return
    assert hasattr(tools_panel, "COLOR_TEXT")
    assert hasattr(tools_panel, "COLOR_MUTED")


def test_http_get_limited_caps_page_bytes() -> None:
    """P1: fetch_webpage must stop reading after the byte budget."""
    from maya_agent.tools import web

    chunks = [b"<html><body>" + b"A" * 80, b"B" * 80, b"C" * 80]

    class FakeResp:
        def __init__(self):
            self.url = "https://example.com/page"
            self.headers = {"content-type": "text/html; charset=utf-8"}
            self.encoding = "utf-8"

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield from chunks

    class FakeStream:
        def __init__(self, resp):
            self._resp = resp

        def __enter__(self):
            return self._resp

        def __exit__(self, *exc):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self._resp = FakeResp()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url):
            return FakeStream(self._resp)

    old_client = web.httpx.Client
    old_cfg = web._web_cfg
    old_validate = web._validate_public_url
    web.httpx.Client = FakeClient
    web._web_cfg = lambda: {"timeout": 5.0, "user_agent": "test", "max_download_bytes": 100}
    web._validate_public_url = lambda url: (True, "")
    try:
        text, final_url, ctype, capped = web._http_get_limited(
            "https://example.com/page", 100
        )
    finally:
        web.httpx.Client = old_client
        web._web_cfg = old_cfg
        web._validate_public_url = old_validate

    assert final_url == "https://example.com/page"
    assert ctype == "text/html"
    assert capped is True, "byte cap was not reported"
    assert len(text) <= 100, f"read {len(text)} bytes past a 100-byte cap"
    assert text.startswith("<html><body>AAAA")


def test_scene_hooks_after_new_isolates_previous_sidecar() -> None:
    """P0: File -> New Scene must register kAfterNew and never overwrite A.ma sidecar."""
    from maya_agent.core import session_manager as sm_mod
    from maya_agent.core import session_store
    from maya_agent.llm.base import ChatMessage
    from maya_agent.plugin import scene_hooks

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="mayaagent_hooks_new_"))
    scene_a = (tmpdir / "A.ma").as_posix()
    sidecar_a = session_store.sidecar_path_for_scene(scene_a)
    untitled_fb = tmpdir / "untitled" / "current.json"
    assert sidecar_a is not None

    live = {"scene": scene_a}
    registered: list = []
    removed: list = []

    class FakeMSceneMessage:
        kBeforeNew = 101
        kAfterNew = 102
        kBeforeOpen = 103
        kAfterOpen = 104
        kAfterSave = 105

        @staticmethod
        def addCallback(msg_id, fn):
            cid = len(registered) + 1
            registered.append((cid, msg_id, fn))
            return cid

    class FakeMMessage:
        @staticmethod
        def removeCallback(cid):
            removed.append(cid)

    fake_maya = types.ModuleType("maya")
    fake_api = types.ModuleType("maya.api")
    fake_om2 = types.ModuleType("maya.api.OpenMaya")
    fake_om2.MSceneMessage = FakeMSceneMessage
    fake_om2.MMessage = FakeMMessage
    fake_api.OpenMaya = fake_om2
    fake_maya.api = fake_api

    class FakeWindow:
        def __init__(self):
            self.sessions = sm_mod.SessionManager()
            self.messages = [ChatMessage(role="user", content="rig hero A")]
            self.blocks = [{"type": "user", "text": "rig hero A"}]

        def persist_sessions(self):
            self.sessions.sync_active(self.messages, self.blocks)

        def on_scene_changed(self, reload_only: bool = True, *, persist_current: bool = True):
            if persist_current:
                self.persist_sessions()
            self.sessions.reload_from_disk()
            self.messages = self.sessions.memory_for_active()
            self.blocks = self.sessions.blocks_for_active()

    saved_mods = {
        k: sys.modules.get(k)
        for k in ("maya", "maya.api", "maya.api.OpenMaya")
    }
    old_in_maya = scene_hooks.in_maya
    old_get_win = scene_hooks._get_window
    old_get_scene_ss = session_store.get_maya_scene_path
    old_get_scene_sm = sm_mod.get_maya_scene_path
    old_fb = session_store.fallback_path_for_untitled

    sys.modules["maya"] = fake_maya
    sys.modules["maya.api"] = fake_api
    sys.modules["maya.api.OpenMaya"] = fake_om2
    scene_hooks.uninstall_scene_hooks()
    scene_hooks.in_maya = lambda: True
    session_store.get_maya_scene_path = lambda: live["scene"]
    sm_mod.get_maya_scene_path = lambda: live["scene"]
    session_store.fallback_path_for_untitled = lambda: untitled_fb

    try:
        win = FakeWindow()
        win.persist_sessions()
        scene_hooks._get_window = lambda: win

        scene_hooks.install_scene_hooks()
        hook_map = {msg_id: fn for _cid, msg_id, fn in registered}
        assert FakeMSceneMessage.kBeforeNew in hook_map
        assert FakeMSceneMessage.kAfterNew in hook_map, "missing MSceneMessage.kAfterNew"
        assert FakeMSceneMessage.kAfterOpen in hook_map
        assert FakeMSceneMessage.kAfterSave in hook_map

        # Simulate File -> New Scene from A.ma
        hook_map[FakeMSceneMessage.kBeforeNew]()
        live["scene"] = ""
        hook_map[FakeMSceneMessage.kAfterNew]()

        assert win.sessions.project.scene_path == "", (
            f"expected untitled bound path '', got {win.sessions.project.scene_path!r}"
        )

        # Chatting in the new untitled scene must NOT overwrite A.ma's sidecar
        win.messages = [ChatMessage(role="user", content="untitled blockout")]
        win.blocks = [{"type": "user", "text": "untitled blockout"}]
        win.persist_sessions()

        a_text = sidecar_a.read_text(encoding="utf-8")
        assert "rig hero A" in a_text
        assert "untitled blockout" not in a_text, "A.ma sidecar was polluted after New Scene!"
        assert untitled_fb.is_file()
        assert "untitled blockout" in untitled_fb.read_text(encoding="utf-8")

        # Teardown removes all OpenMaya callbacks cleanly
        expected_ids = [cid for cid, _, _ in registered]
        scene_hooks.uninstall_scene_hooks()
        assert removed == expected_ids
        assert scene_hooks._INSTALLED is False
    finally:
        scene_hooks.uninstall_scene_hooks()
        scene_hooks.in_maya = old_in_maya
        scene_hooks._get_window = old_get_win
        session_store.get_maya_scene_path = old_get_scene_ss
        sm_mod.get_maya_scene_path = old_get_scene_sm
        session_store.fallback_path_for_untitled = old_fb
        for k, mod in saved_mods.items():
            if mod is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = mod


def test_untitled_open_and_save_transitions() -> None:
    """P0: Opening B.ma from untitled must not clobber B.ma; Save/SaveAs must migrate cleanly."""
    from maya_agent.core import session_manager as sm_mod
    from maya_agent.core import session_store
    from maya_agent.core.chat_session import ChatSession, ProjectChatData
    from maya_agent.llm.base import ChatMessage
    from maya_agent.plugin import scene_hooks

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="mayaagent_hooks_open_"))
    scene_b = (tmpdir / "B.ma").as_posix()
    scene_c = (tmpdir / "C.ma").as_posix()
    scene_d = (tmpdir / "D.ma").as_posix()
    sidecar_b = session_store.sidecar_path_for_scene(scene_b)
    sidecar_c = session_store.sidecar_path_for_scene(scene_c)
    sidecar_d = session_store.sidecar_path_for_scene(scene_d)
    untitled_fb = tmpdir / "untitled" / "current.json"
    assert sidecar_b and sidecar_c and sidecar_d

    # Pre-seed B.ma with an existing project conversation
    b_sess = ChatSession.create("B rig session")
    b_sess.ui_blocks = [{"type": "user", "text": "existing B history"}]
    session_store.save_project(
        ProjectChatData(
            scene_path=scene_b,
            active_session_id=b_sess.id,
            sessions=[b_sess],
        ),
        scene_b,
    )

    live = {"scene": ""}

    class FakeWindow:
        def __init__(self):
            self.sessions = sm_mod.SessionManager()
            self.messages = [ChatMessage(role="user", content="scratch in untitled")]
            self.blocks = [{"type": "user", "text": "scratch in untitled"}]

        def persist_sessions(self):
            self.sessions.sync_active(self.messages, self.blocks)

        def on_scene_changed(self, reload_only: bool = True, *, persist_current: bool = True):
            if persist_current:
                self.persist_sessions()
            self.sessions.reload_from_disk()
            self.messages = self.sessions.memory_for_active()
            self.blocks = self.sessions.blocks_for_active()

    old_get_win = scene_hooks._get_window
    old_get_scene_ss = session_store.get_maya_scene_path
    old_get_scene_sm = sm_mod.get_maya_scene_path
    old_fb = session_store.fallback_path_for_untitled

    session_store.get_maya_scene_path = lambda: live["scene"]
    sm_mod.get_maya_scene_path = lambda: live["scene"]
    session_store.fallback_path_for_untitled = lambda: untitled_fb

    try:
        # 1) Start in untitled, then File -> Open -> B.ma (Maya updates sceneName BEFORE kAfterOpen)
        win = FakeWindow()
        scene_hooks._get_window = lambda: win
        scene_hooks._LAST_SCENE_PATH = ""

        live["scene"] = scene_b
        scene_hooks._on_scene_opened()

        assert "existing B history" in sidecar_b.read_text(encoding="utf-8"), (
            "B.ma sidecar was clobbered by untitled session on AfterOpen!"
        )
        assert "scratch in untitled" not in sidecar_b.read_text(encoding="utf-8")
        assert untitled_fb.is_file()
        assert "scratch in untitled" in untitled_fb.read_text(encoding="utf-8")
        assert win.sessions.project.scene_path == scene_b
        assert win.blocks == [{"type": "user", "text": "existing B history"}]

        # 2) Saving already-named B.ma (Ctrl+S) must NOT consume unrelated untitled fallback
        scene_hooks._on_scene_saved()
        assert untitled_fb.is_file(), "Ctrl+S on named scene stole unrelated untitled fallback"

        # 3) Switch to New Scene, chat in untitled, then Save Scene -> C.ma
        live["scene"] = ""
        scene_hooks._on_new_scene()
        win.messages = [ChatMessage(role="user", content="brand new C asset")]
        win.blocks = [{"type": "user", "text": "brand new C asset"}]

        live["scene"] = scene_c
        scene_hooks._on_scene_saved()

        assert sidecar_c.is_file()
        assert "brand new C asset" in sidecar_c.read_text(encoding="utf-8")
        assert win.sessions.project.scene_path == scene_c
        assert not untitled_fb.exists(), (
            "untitled fallback was resurrected after migrating to C.ma"
        )

        # 4) Save Scene As C.ma -> D.ma clones conversation to D.ma while keeping C.ma intact
        live["scene"] = scene_d
        scene_hooks._on_scene_saved()

        assert sidecar_d.is_file()
        assert "brand new C asset" in sidecar_d.read_text(encoding="utf-8")
        assert "brand new C asset" in sidecar_c.read_text(encoding="utf-8")
        assert win.sessions.project.scene_path == scene_d
    finally:
        scene_hooks._get_window = old_get_win
        scene_hooks._LAST_SCENE_PATH = ""
        session_store.get_maya_scene_path = old_get_scene_ss
        sm_mod.get_maya_scene_path = old_get_scene_sm
        session_store.fallback_path_for_untitled = old_fb


TESTS = (
    test_run_on_main_thread_never_reexecutes_on_error,
    test_executor_confirms_on_main_thread,
    test_web_tools_are_off_main_thread,
    test_config_save_user_keeps_cloud_sections,
    test_session_store_writes_atomically,
    test_undo_never_consumes_user_operation,
    test_cancel_checker_contextvar,
    test_cloud_wait_aborts_on_cancel,
    test_tools_panel_import_has_color_token,
    test_http_get_limited_caps_page_bytes,
    test_scene_hooks_after_new_isolates_previous_sidecar,
    test_untitled_open_and_save_transitions,
)


def main() -> int:
    failures = []
    for test in TESTS:
        name = test.__name__
        try:
            test()
            print(f"  ok   {name}")
        except Exception as e:
            failures.append((name, e))
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    if failures:
        print(f"test_risk_fixes: {len(failures)} failure(s)")
        return 1
    print("test_risk_fixes: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
