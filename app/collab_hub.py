"""In-process WebSocket rooms for live document collaboration."""
from __future__ import annotations

import json
from collections import defaultdict

from fastapi import WebSocket

_rooms: dict[int, set[WebSocket]] = defaultdict(set)


async def join(doc_id: int, ws: WebSocket) -> None:
    _rooms[int(doc_id)].add(ws)


async def leave(doc_id: int, ws: WebSocket) -> None:
    room = _rooms.get(int(doc_id))
    if not room:
        return
    room.discard(ws)
    if not room:
        _rooms.pop(int(doc_id), None)


async def broadcast(doc_id: int, payload: dict | str, skip: WebSocket | None = None) -> int:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    sent = 0
    dead: list[WebSocket] = []
    for peer in list(_rooms.get(int(doc_id), ())):
        if peer is skip:
            continue
        try:
            await peer.send_text(text)
            sent += 1
        except Exception:
            dead.append(peer)
    for peer in dead:
        await leave(doc_id, peer)
    return sent


def room_size(doc_id: int) -> int:
    return len(_rooms.get(int(doc_id), ()))
