"""
Minimal VTT (virtual tabletop) backend.

One shared "room" per WebSocket path. Server holds the authoritative
state (tokens + chat log) in memory and rebroadcasts every message to
all connected clients in that room, including the sender, so every
client's UI stays a pure reflection of server state.

No persistence, no auth — this is a prototype for a handful of friends
on a LAN/tunnel, not a hosted product.
"""

import itertools
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_token_ids = itertools.count(1)


class Room:
    def __init__(self) -> None:
        self.tokens: dict[str, dict[str, Any]] = {}
        self.chat: list[dict[str, Any]] = []
        self.clients: list[WebSocket] = []

    def state(self) -> dict[str, Any]:
        return {"type": "state", "tokens": self.tokens, "chat": self.chat[-100:]}

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.remove(ws)


rooms: dict[str, Room] = {}


def get_room(room_id: str) -> Room:
    if room_id not in rooms:
        rooms[room_id] = Room()
    return rooms[room_id]


@app.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str):
    await websocket.accept()
    room = get_room(room_id)
    room.clients.append(websocket)
    await websocket.send_json(room.state())

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")

            if msg_type == "add_token":
                token_id = str(next(_token_ids))
                room.tokens[token_id] = {
                    "id": token_id,
                    "label": str(msg.get("label", "?"))[:20],
                    "color": msg.get("color", "#00ff88"),
                    "x": msg.get("x", 400),
                    "y": msg.get("y", 300),
                }
                await room.broadcast({"type": "token_added", "token": room.tokens[token_id]})

            elif msg_type == "move_token":
                token_id = msg.get("id")
                token = room.tokens.get(token_id)
                if token:
                    token["x"] = msg.get("x", token["x"])
                    token["y"] = msg.get("y", token["y"])
                    await room.broadcast({"type": "token_moved", "id": token_id, "x": token["x"], "y": token["y"]})

            elif msg_type == "remove_token":
                token_id = msg.get("id")
                if room.tokens.pop(token_id, None) is not None:
                    await room.broadcast({"type": "token_removed", "id": token_id})

            elif msg_type == "chat":
                entry = {"author": str(msg.get("author", "Anon"))[:30], "text": str(msg.get("text", ""))[:500]}
                room.chat.append(entry)
                await room.broadcast({"type": "chat", **entry})

            elif msg_type == "roll":
                entry = {
                    "author": str(msg.get("author", "Anon"))[:30],
                    "text": f"rolled {msg.get('formula', '?')} → {msg.get('results')} = {msg.get('total')}",
                }
                room.chat.append(entry)
                await room.broadcast({"type": "chat", **entry})

    except WebSocketDisconnect:
        if websocket in room.clients:
            room.clients.remove(websocket)
