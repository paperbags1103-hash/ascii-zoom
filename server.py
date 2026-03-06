#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import signal
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

import websockets
from websockets.exceptions import ConnectionClosed


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOGGER = logging.getLogger("ascii-zoom-server")
MAX_FRAME_CHARS = 6000


@dataclass
class Participant:
    participant_id: str
    name: str
    websocket: websockets.WebSocketServerProtocol


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
            room = self.rooms.get(room_id)
            if room is None:
                room = Room(room_id=room_id)
                self.rooms[room_id] = room
            room.participants[participant.participant_id] = participant
            return room

    async def leave(self, room_id: str, participant_id: str) -> Optional[Room]:
        async with self.lock:
            room = self.rooms.get(room_id)
            if room is None:
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


def extract_room_id(path: str) -> Optional[str]:
    if not path.startswith("/room/"):
        return None
    room_id = path.split("/room/", 1)[1].strip().split("/", 1)[0]
    if not room_id:
        return None
    return room_id[:64]


async def safe_send(ws: websockets.WebSocketServerProtocol, payload: dict) -> bool:
    try:
        await ws.send(json.dumps(payload))
        return True
    except ConnectionClosed:
        return False
    except Exception:
        LOGGER.exception("failed to send payload")
        return False


async def broadcast(room: Room, payload: dict, exclude_id: Optional[str] = None) -> None:
    if not room.participants:
        return

    dead_ids = []
    sends = []
    for pid, participant in room.participants.items():
        if exclude_id is not None and pid == exclude_id:
            continue
        sends.append((pid, asyncio.create_task(safe_send(participant.websocket, payload))))

    for pid, task in sends:
        ok = await task
        if not ok:
            dead_ids.append(pid)

    if dead_ids:
        for pid in dead_ids:
            await ROOM_MANAGER.leave(room.room_id, pid)


async def handle_client(websocket: websockets.WebSocketServerProtocol, path: Optional[str] = None) -> None:
    participant_id = uuid.uuid4().hex[:8]
    room_id = ""
    participant_name = "Anonymous"
    joined = False

    try:
        actual_path = path or getattr(websocket, "path", "")
        room_id = extract_room_id(actual_path) or ""
        if not room_id:
            await safe_send(websocket, {"type": "error", "message": "Invalid path. Use /room/<room_id>"})
            await websocket.close(code=1008, reason="invalid path")
            return

        raw_join = await asyncio.wait_for(websocket.recv(), timeout=10)
        try:
            join_msg = json.loads(raw_join)
        except json.JSONDecodeError:
            await safe_send(websocket, {"type": "error", "message": "Invalid JSON in join message"})
            await websocket.close(code=1002, reason="invalid json")
            return

        if not isinstance(join_msg, dict) or join_msg.get("type") != "join":
            await safe_send(websocket, {"type": "error", "message": "First message must be join"})
            await websocket.close(code=1008, reason="missing join")
            return

        participant_name = str(join_msg.get("name", "Anonymous")).strip()[:32] or "Anonymous"
        participant = Participant(participant_id=participant_id, name=participant_name, websocket=websocket)
        room = await ROOM_MANAGER.join(room_id, participant)
        joined = True

        LOGGER.info("join room=%s participant=%s(%s)", room_id, participant_name, participant_id)

        await safe_send(
            websocket,
            {
                "type": "welcome",
                "id": participant_id,
                "room": room_id,
                "participants": [
                    {"id": p.participant_id, "name": p.name}
                    for p in room.participants.values()
                ],
            },
        )

        await broadcast(
            room,
            {
                "type": "participant_join",
                "participant": {"id": participant_id, "name": participant_name},
            },
            exclude_id=participant_id,
        )

        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                await safe_send(websocket, {"type": "error", "message": "Invalid JSON message"})
                continue

            if not isinstance(data, dict):
                continue

            msg_type = data.get("type")
            if msg_type == "frame":
                frame = str(data.get("frame", ""))[:MAX_FRAME_CHARS]
                muted = bool(data.get("muted", False))
                current_room = await ROOM_MANAGER.get_room(room_id)
                if current_room is None:
                    continue
                await broadcast(
                    current_room,
                    {
                        "type": "frame",
                        "id": participant_id,
                        "name": participant_name,
                        "frame": frame,
                        "muted": muted,
                    },
                    exclude_id=participant_id,
                )
            elif msg_type == "ping":
                await safe_send(websocket, {"type": "pong"})
            elif msg_type == "leave":
                break

    except asyncio.TimeoutError:
        LOGGER.info("timeout waiting join")
    except ConnectionClosed:
        pass
    except Exception:
        LOGGER.exception("unexpected server error")
    finally:
        if joined:
            room = await ROOM_MANAGER.leave(room_id, participant_id)
            if room is not None:
                await broadcast(room, {"type": "participant_leave", "id": participant_id})
            LOGGER.info("leave room=%s participant=%s(%s)", room_id, participant_name, participant_id)


async def run_server(host: str, port: int) -> None:
    stop = asyncio.Future()

    def _stop() -> None:
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    async with websockets.serve(handle_client, host, port, max_size=2**20, ping_interval=20, ping_timeout=20):
        LOGGER.info("ASCII Zoom server running on ws://%s:%s", host, port)
        await stop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASCII Zoom websocket server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
