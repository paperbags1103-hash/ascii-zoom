#!/usr/bin/env python3
"""ASCII Zoom WebSocket server — aiohttp-based (handles HTTP health checks + WebSocket)."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import signal
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOGGER = logging.getLogger("ascii-zoom-server")


@dataclass
class Participant:
    participant_id: str
    name: str
    ws: web.WebSocketResponse


@dataclass
class Room:
    room_id: str
    participants: Dict[str, Participant] = field(default_factory=dict)


class RoomManager:
    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}
        self.lock = asyncio.Lock()

    async def join(self, room_id: str, participant: Participant) -> Room:
        async with self.lock:
            room = self.rooms.setdefault(room_id, Room(room_id=room_id))
            room.participants[participant.participant_id] = participant
            return room

    async def leave(self, room_id: str, participant_id: str) -> Optional[Room]:
        async with self.lock:
            room = self.rooms.get(room_id)
            if not room:
                return None
            room.participants.pop(participant_id, None)
            if not room.participants:
                self.rooms.pop(room_id, None)
                return None
            return room

    async def get_room(self, room_id: str) -> Optional[Room]:
        async with self.lock:
            return self.rooms.get(room_id)


ROOM_MANAGER = RoomManager()
BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML = BASE_DIR / "static" / "index.html"


async def safe_send(ws: web.WebSocketResponse, payload: dict) -> bool:
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        return False


async def broadcast(room: Room, payload: dict, exclude_id: Optional[str] = None) -> None:
    dead = []
    for pid, p in list(room.participants.items()):
        if pid == exclude_id:
            continue
        ok = await safe_send(p.ws, payload)
        if not ok:
            dead.append(pid)
    for pid in dead:
        await ROOM_MANAGER.leave(room.room_id, pid)


async def health_handler(request: web.Request) -> web.Response:
    return web.Response(text="OK", status=200)


async def app_handler(request: web.Request) -> web.FileResponse:
    if not INDEX_HTML.exists():
        raise web.HTTPNotFound(reason="static/index.html not found")
    return web.FileResponse(INDEX_HTML)


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    room_id = request.match_info.get("room_id", "").strip()
    if not room_id:
        raise web.HTTPBadRequest(reason="room_id required")

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    participant_id = uuid.uuid4().hex[:8]
    participant_name = "Anonymous"
    joined = False

    try:
        # Wait for join message
        msg = await asyncio.wait_for(ws.receive(), timeout=10)
        if msg.type != WSMsgType.TEXT:
            await ws.close()
            return ws

        data = json.loads(msg.data)
        if data.get("type") != "join":
            await ws.close()
            return ws

        participant_name = str(data.get("name", "Anonymous"))[:32] or "Anonymous"
        participant = Participant(participant_id=participant_id, name=participant_name, ws=ws)
        room = await ROOM_MANAGER.join(room_id, participant)
        joined = True

        LOGGER.info("join room=%s participant=%s(%s)", room_id, participant_name, participant_id)

        # Send welcome
        await safe_send(ws, {
            "type": "welcome",
            "id": participant_id,
            "room": room_id,
            "participants": [
                {"id": p.participant_id, "name": p.name}
                for p in room.participants.values()
            ],
        })

        # Notify others
        await broadcast(room, {
            "type": "participant_join",
            "participant": {"id": participant_id, "name": participant_name},
        }, exclude_id=participant_id)

        # Main message loop
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type == "frame":
                    current_room = await ROOM_MANAGER.get_room(room_id)
                    if current_room:
                        await broadcast(current_room, {
                            "type": "frame",
                            "id": participant_id,
                            "name": participant_name,
                            "frame": str(data.get("frame", "")),
                            "muted": bool(data.get("muted", False)),
                        }, exclude_id=participant_id)
                elif msg_type == "chat":
                    text = str(data.get("text", "")).strip()
                    if not text:
                        continue
                    current_room = await ROOM_MANAGER.get_room(room_id)
                    if current_room:
                        await broadcast(current_room, {
                            "type": "chat",
                            "id": participant_id,
                            "name": participant_name,
                            "text": text[:500],
                        })
                elif msg_type == "ping":
                    await safe_send(ws, {"type": "pong"})
                elif msg_type == "leave":
                    break
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break

    except asyncio.TimeoutError:
        LOGGER.info("timeout waiting for join: %s", participant_id)
    except Exception:
        LOGGER.exception("unexpected error")
    finally:
        if joined:
            room = await ROOM_MANAGER.leave(room_id, participant_id)
            if room:
                await broadcast(room, {"type": "participant_leave", "id": participant_id})
            LOGGER.info("leave room=%s participant=%s(%s)", room_id, participant_name, participant_id)

    return ws


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", app_handler)
    app.router.add_get("/app", app_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/room/{room_id}", websocket_handler)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASCII Zoom WebSocket server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app()
    LOGGER.info("ASCII Zoom server starting on %s:%s", args.host, args.port)
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
