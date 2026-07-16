"""Gray-Matter registry: discoverable MCP server registry."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ServerEntry:
    name: str
    tool_names: list[str]
    socket_path: str
    pid: int
    last_heartbeat: float = field(default_factory=time.time)
    status: str = "alive"

    def is_alive(self, timeout: float = 15.0) -> bool:
        return self.status == "alive" and (time.time() - self.last_heartbeat) < timeout


class Registry:
    _instance: Optional["Registry"] = None

    def __init__(self):
        self._servers: dict[str, ServerEntry] = {}
        self._tool_index: dict[str, str] = {}

    @classmethod
    def instance(cls) -> "Registry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, name: str, tool_names: list[str], socket_path: str, pid: int) -> None:
        entry = ServerEntry(name=name, tool_names=tool_names, socket_path=socket_path, pid=pid)
        self._servers[name] = entry
        for tool in tool_names:
            self._tool_index[tool] = name

    def unregister(self, name: str) -> None:
        entry = self._servers.pop(name, None)
        if entry:
            for tool in entry.tool_names:
                self._tool_index.pop(tool, None)

    def get_server(self, name: str) -> Optional[ServerEntry]:
        return self._servers.get(name)

    def find_server_by_tool(self, tool_name: str) -> Optional[ServerEntry]:
        sn = self._tool_index.get(tool_name)
        return self._servers.get(sn) if sn else None

    def all_servers(self) -> list[ServerEntry]:
        return list(self._servers.values())

    def alive_servers(self) -> list[ServerEntry]:
        return [s for s in self._servers.values() if s.is_alive()]

    def heartbeat(self, name: str) -> bool:
        entry = self._servers.get(name)
        if not entry:
            return False
        entry.last_heartbeat = time.time()
        entry.status = "alive"
        return True

    def mark_dead(self, name: str) -> None:
        entry = self._servers.get(name)
        if entry:
            entry.status = "dead"

    def to_dict(self) -> dict:
        return {name: {"tool_names": e.tool_names, "socket_path": e.socket_path, "pid": e.pid, "status": e.status, "last_heartbeat": e.last_heartbeat} for name, e in self._servers.items()}

    def summary(self) -> str:
        if not self._servers:
            return "Registry empty."
        return "Registered servers:\n" + "\n".join(f"  {n} ({'alive' if e.is_alive() else 'dead'}) tools={e.tool_names} pid={e.pid}" for n, e in self._servers.items())
