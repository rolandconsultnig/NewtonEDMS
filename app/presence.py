"""Real-time online user presence registry."""

import threading
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PresenceManager:
    """Thread-safe in-memory presence tracking for online users."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[int, dict[str, Any]] = {}

    def touch(
        self,
        user_id: int,
        username: str,
        role: str,
        email: str | None = None,
        avatar: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        current_path: str | None = None,
    ) -> None:
        now = _utc_now()
        with self._lock:
            self._sessions[user_id] = {
                "user_id": user_id,
                "username": username,
                "role": role,
                "email": email or "",
                "avatar": avatar or "",
                "ip": ip or "127.0.0.1",
                "user_agent": user_agent or "",
                "current_path": current_path or "/",
                "last_seen": now,
            }

    def get_online(self, max_idle_seconds: int = 300) -> list[dict[str, Any]]:
        """Return list of active users within the idle threshold (default 5 min)."""
        now = _utc_now()
        active: list[dict[str, Any]] = []
        with self._lock:
            # Clean up old sessions (> 1 hour)
            to_del = []
            for uid, sess in self._sessions.items():
                idle_secs = (now - sess["last_seen"]).total_seconds()
                if idle_secs > 3600:
                    to_del.append(uid)
                elif idle_secs <= max_idle_seconds:
                    active.append(
                        {
                            "user_id": sess["user_id"],
                            "username": sess["username"],
                            "role": sess["role"],
                            "email": sess["email"],
                            "avatar": sess["avatar"],
                            "ip": sess["ip"],
                            "user_agent": sess["user_agent"],
                            "current_path": sess["current_path"],
                            "last_seen": sess["last_seen"].isoformat(),
                            "idle_seconds": int(idle_secs),
                            "status": "active" if idle_secs < 90 else "idle",
                        }
                    )
            for uid in to_del:
                del self._sessions[uid]

        active.sort(key=lambda x: x["idle_seconds"])
        return active

    def count_online(self, max_idle_seconds: int = 300) -> int:
        now = _utc_now()
        with self._lock:
            return sum(
                1
                for sess in self._sessions.values()
                if (now - sess["last_seen"]).total_seconds() <= max_idle_seconds
            )

    def remove(self, user_id: int) -> None:
        with self._lock:
            self._sessions.pop(user_id, None)


presence_manager = PresenceManager()
