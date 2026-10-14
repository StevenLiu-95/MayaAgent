"""Background QThread that runs MayaAgent.chat and emits UI events."""

from __future__ import annotations

import traceback

from maya_agent.core.agent import MayaAgent
from maya_agent.ui.qt_bind import QtCore


class _WorkerSignals(QtCore.QObject):
    event = QtCore.Signal(dict)
    finished = QtCore.Signal()
    failed = QtCore.Signal(str)


class AgentWorker(QtCore.QThread):
    """Run one agent turn off the UI thread; serialize with MCP via agent_lock."""

    def __init__(
        self,
        agent: MayaAgent,
        text: str,
        stream: bool,
        images=None,
        parent=None,
    ):
        super().__init__(parent)
        self.agent = agent
        self.text = text
        self.stream = stream
        self.images = images
        self.signals = _WorkerSignals()

    def run(self):
        from maya_agent.bridge.agent_remote import agent_lock

        lock = agent_lock()
        if not lock.acquire(timeout=5.0):
            self.signals.failed.emit(
                "Agent busy: MCP chat is in progress. Stop it or wait."
            )
            return
        try:
            for event in self.agent.chat(
                self.text, stream=self.stream, images=self.images
            ):
                self.signals.event.emit(event)
            self.signals.finished.emit()
        except Exception:
            self.signals.failed.emit(traceback.format_exc())
        finally:
            lock.release()


def create_agent_worker(
    agent: MayaAgent, text: str, stream: bool, images=None, parent=None
) -> AgentWorker:
    return AgentWorker(agent, text, stream, images, parent=parent)
