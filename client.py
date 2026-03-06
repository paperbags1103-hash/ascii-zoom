#!/usr/bin/env python3
import argparse
import asyncio
import curses
import json
import logging
import signal
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed

ASCII_CHARS = "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`. "
ASCII_LUT = np.array(list(ASCII_CHARS), dtype="<U1")
FRAME_WIDTH = 120
FRAME_HEIGHT = 55
TARGET_FPS = 10
MAX_PARTICIPANTS = 8


LOGGER = logging.getLogger("ascii-zoom-client")


@dataclass
class PeerState:
    name: str
    frame_lines: List[str]
    muted: bool = False


@dataclass
class ChatMessage:
    name: str
    text: str
    own: bool = False


class CameraASCII:
    def __init__(self) -> None:
        try:
            self.cap = cv2.VideoCapture(0)
            self.available = self.cap.isOpened()
        except Exception:
            self.cap = None
            self.available = False
        self.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        self.sharpen_kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()

    def _placeholder(self, text: str) -> List[str]:
        lines = [" " * FRAME_WIDTH for _ in range(FRAME_HEIGHT)]
        banner = f" {text} "
        start_row = FRAME_HEIGHT // 2
        start_col = max(0, (FRAME_WIDTH - len(banner)) // 2)
        row_chars = list(lines[start_row])
        for i, c in enumerate(banner[: FRAME_WIDTH - start_col]):
            row_chars[start_col + i] = c
        lines[start_row] = "".join(row_chars)
        return lines

    def read_ascii(self, muted: bool) -> List[str]:
        if muted:
            return self._placeholder("CAMERA MUTED")

        if not self.available or self.cap is None:
            return self._placeholder("NO CAMERA")

        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.available = False
            return self._placeholder("NO CAMERA")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (FRAME_WIDTH, FRAME_HEIGHT), interpolation=cv2.INTER_AREA)
        gray = self.clahe.apply(gray)
        edges = cv2.Canny(gray, 50, 150)
        gray = cv2.addWeighted(gray, 0.7, edges, 0.3, 0)
        gray = cv2.filter2D(gray, -1, self.sharpen_kernel)
        gray = np.clip(gray, 0, 255).astype(np.uint8)
        idx = (gray.astype(np.float32) * (len(ASCII_CHARS) - 1) / 255).astype(np.int32)
        mapped = ASCII_LUT[idx]
        return ["".join(row.tolist()) for row in mapped]


def fit_addstr(win, y: int, x: int, text: str, attr: int = 0) -> None:
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    available = max_x - x
    if available <= 0:
        return
    try:
        win.addstr(y, x, text[:available], attr)
    except curses.error:
        pass


def calc_grid(count: int) -> Tuple[int, int]:
    if count <= 1:
        return 1, 1
    if count == 2:
        return 1, 2
    if count <= 4:
        return 2, 2
    if count <= 6:
        return 2, 3
    return 2, 4


class CursesUI:
    def __init__(self, room: str, name: str) -> None:
        self.room = room
        self.name = name
        self.stdscr = None
        self.pad = None
        self.last_render = 0.0

    def init(self) -> None:
        self.stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        self.stdscr.keypad(True)
        self.stdscr.nodelay(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
            curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
            curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    def close(self) -> None:
        if self.stdscr is None:
            return
        self.stdscr.keypad(False)
        curses.nocbreak()
        curses.echo()
        curses.endwin()

    def poll_key(self) -> int:
        if self.stdscr is None:
            return -1
        try:
            return self.stdscr.getch()
        except curses.error:
            return -1

    def render(
        self,
        my_id: str,
        my_frame: List[str],
        peers: Dict[str, PeerState],
        chat_messages: List[ChatMessage],
        chat_input_mode: bool,
        chat_input: str,
        muted: bool,
        connected: bool,
    ) -> None:
        if self.stdscr is None:
            return

        now = time.time()
        if now - self.last_render < 1.0 / TARGET_FPS:
            return
        self.last_render = now

        h, w = self.stdscr.getmaxyx()
        if self.pad is None or self.pad.getmaxyx() != (h, w):
            self.pad = curses.newpad(max(h, 1), max(w, 1))

        self.pad.erase()
        green = curses.color_pair(1) if curses.has_colors() else 0
        cyan = curses.color_pair(2) if curses.has_colors() else 0
        yellow = curses.color_pair(3) if curses.has_colors() else 0

        total_participants = min(len(peers) + 1, MAX_PARTICIPANTS)
        title = (
            f" ASCII ZOOM | Room: {self.room} | Participants: {total_participants}/{MAX_PARTICIPANTS} "
        )
        fit_addstr(self.pad, 0, 0, "┌" + "─" * max(0, w - 2) + "┐", green)
        fit_addstr(self.pad, 1, 0, "│" + title.ljust(max(0, w - 2))[: max(0, w - 2)] + "│", cyan)
        fit_addstr(self.pad, 2, 0, "├" + "─" * max(0, w - 2) + "┤", green)

        usable_top = 3
        chat_top = max(usable_top, h - 9)
        grid_bottom = max(usable_top, chat_top - 1)
        usable_height = max(1, grid_bottom - usable_top + 1)

        participant_items = [(my_id, PeerState(name=f"{self.name} (You)", frame_lines=my_frame, muted=muted))]
        for pid, peer in list(peers.items())[: MAX_PARTICIPANTS - 1]:
            participant_items.append((pid, peer))

        rows, cols = calc_grid(len(participant_items))
        tile_w = max(12, w // cols)
        tile_h = max(6, usable_height // rows)

        for idx, (_, peer) in enumerate(participant_items):
            r = idx // cols
            c = idx % cols
            x0 = c * tile_w
            y0 = usable_top + r * tile_h
            x1 = min(w - 1, x0 + tile_w - 1)
            y1 = min(grid_bottom, y0 + tile_h - 1)
            if y1 <= y0 or x1 <= x0:
                continue

            fit_addstr(self.pad, y0, x0, "┌" + "─" * max(0, x1 - x0 - 1) + "┐", green)
            for yy in range(y0 + 1, y1):
                fit_addstr(self.pad, yy, x0, "│", green)
                fit_addstr(self.pad, yy, x1, "│", green)
            fit_addstr(self.pad, y1, x0, "└" + "─" * max(0, x1 - x0 - 1) + "┘", green)

            label = f" [{peer.name}{' - muted' if peer.muted else ''}] "
            fit_addstr(self.pad, y0, x0 + 2, label, yellow)

            content_w = max(1, x1 - x0 - 1)
            content_h = max(1, y1 - y0 - 1)
            start_y = y0 + 1
            for line_idx in range(min(content_h, len(peer.frame_lines))):
                line = peer.frame_lines[line_idx]
                fit_addstr(self.pad, start_y + line_idx, x0 + 1, line[:content_w], green)

        fit_addstr(self.pad, chat_top, 0, "├" + "─" * max(0, w - 2) + "┤", green)

        recent = chat_messages[-5:]
        msg_y = chat_top + 1
        for i in range(5):
            if i < len(recent):
                item = recent[i]
                text = f"[{item.name}] {item.text}"
                color = cyan if item.own else green
                fit_addstr(self.pad, msg_y + i, 1, text, color)
            else:
                fit_addstr(self.pad, msg_y + i, 1, "", green)

        chat_line = f"Chat> {chat_input}" if chat_input_mode else "Press Enter to chat (Esc to cancel)"
        fit_addstr(self.pad, h - 3, 1, chat_line, yellow if chat_input_mode else cyan)

        status = "Connected" if connected else "Reconnecting..."
        controls = (
            f" [Q] Quit  [M] Mute Camera ({'ON' if muted else 'OFF'})"
            f"  [Enter] Chat  Status: {status} "
        )
        fit_addstr(self.pad, h - 2, 0, "├" + "─" * max(0, w - 2) + "┤", green)
        fit_addstr(self.pad, h - 1, 0, "│" + controls.ljust(max(0, w - 2))[: max(0, w - 2)] + "│", cyan)

        self.pad.noutrefresh(0, 0, 0, 0, h - 1, w - 1)
        curses.doupdate()


class ASCIIZoomClient:
    def __init__(self, server: str, room: str, name: str) -> None:
        self.server = server.rstrip("/")
        self.room = room
        self.name = name
        self.running = True
        self.muted = False
        self.connected = False
        self.my_id = "local"
        self.peers: Dict[str, PeerState] = {}
        self.chat_messages: List[ChatMessage] = []
        self.chat_input_mode = False
        self.chat_input = ""
        self.ws = None
        self.my_frame = [" " * FRAME_WIDTH for _ in range(FRAME_HEIGHT)]
        self.ui = CursesUI(room=room, name=name)
        self.camera = CameraASCII()

    def _room_url(self) -> str:
        parsed = urlparse(self.server)
        if parsed.scheme not in ("ws", "wss"):
            raise ValueError("Server must begin with ws:// or wss://")
        return f"{self.server}/room/{self.room}"

    async def _send_frames(self, ws) -> None:
        frame_interval = 1.0 / TARGET_FPS
        while self.running and self.connected:
            self.my_frame = self.camera.read_ascii(self.muted)
            payload = {
                "type": "frame",
                "frame": "\n".join(self.my_frame),
                "muted": self.muted,
            }
            try:
                await ws.send(json.dumps(payload))
            except ConnectionClosed:
                break
            await asyncio.sleep(frame_interval)

    async def _recv_messages(self, ws) -> None:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(data, dict):
                continue

            msg_type = data.get("type")
            if msg_type == "welcome":
                self.my_id = data.get("id", self.my_id)
                self.peers = {}
                for p in data.get("participants", []):
                    pid = p.get("id")
                    if pid and pid != self.my_id:
                        self.peers[pid] = PeerState(
                            name=str(p.get("name", "Anonymous")),
                            frame_lines=[" " * FRAME_WIDTH for _ in range(FRAME_HEIGHT)],
                        )
            elif msg_type == "participant_join":
                p = data.get("participant", {})
                pid = p.get("id")
                if pid and pid != self.my_id:
                    self.peers[pid] = PeerState(
                        name=str(p.get("name", "Anonymous")),
                        frame_lines=[" " * FRAME_WIDTH for _ in range(FRAME_HEIGHT)],
                    )
            elif msg_type == "participant_leave":
                pid = data.get("id")
                if pid in self.peers:
                    self.peers.pop(pid, None)
            elif msg_type == "frame":
                pid = data.get("id")
                if not pid or pid == self.my_id:
                    continue
                frame_text = str(data.get("frame", ""))
                lines = frame_text.splitlines()
                if len(lines) < FRAME_HEIGHT:
                    lines.extend([" " * FRAME_WIDTH for _ in range(FRAME_HEIGHT - len(lines))])
                lines = [(line + (" " * FRAME_WIDTH))[:FRAME_WIDTH] for line in lines[:FRAME_HEIGHT]]
                default_name = self.peers.get(pid, PeerState("Anonymous", [])).name
                name = str(data.get("name", default_name))
                muted = bool(data.get("muted", False))
                self.peers[pid] = PeerState(name=name, frame_lines=lines, muted=muted)
            elif msg_type == "chat":
                pid = str(data.get("id", ""))
                name = str(data.get("name", "Anonymous"))
                text = str(data.get("text", "")).strip()
                if text:
                    self.chat_messages.append(ChatMessage(name=name, text=text[:300], own=(pid == self.my_id)))
                    self.chat_messages = self.chat_messages[-50:]
            elif msg_type == "error":
                LOGGER.warning("Server error: %s", data.get("message", "unknown error"))

    async def _send_chat(self, text: str) -> None:
        if not self.ws or not self.connected:
            return
        try:
            await self.ws.send(json.dumps({"type": "chat", "text": text[:500]}))
        except ConnectionClosed:
            pass

    async def _ui_loop(self) -> None:
        while self.running:
            key = self.ui.poll_key()
            if self.chat_input_mode:
                if key in (27,):  # ESC
                    self.chat_input_mode = False
                    self.chat_input = ""
                elif key in (10, 13, curses.KEY_ENTER):
                    text = self.chat_input.strip()
                    if text:
                        await self._send_chat(text)
                    self.chat_input_mode = False
                    self.chat_input = ""
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    self.chat_input = self.chat_input[:-1]
                elif 32 <= key <= 126:
                    if len(self.chat_input) < 300:
                        self.chat_input += chr(key)
            else:
                if key in (ord("q"), ord("Q")):
                    self.running = False
                    break
                if key in (ord("m"), ord("M")):
                    self.muted = not self.muted
                elif key in (10, 13, curses.KEY_ENTER):
                    self.chat_input_mode = True
                    self.chat_input = ""
            self.ui.render(
                self.my_id,
                self.my_frame,
                self.peers,
                self.chat_messages,
                self.chat_input_mode,
                self.chat_input,
                self.muted,
                self.connected,
            )
            await asyncio.sleep(0.02)

    async def run(self) -> None:
        self.ui.init()

        loop = asyncio.get_running_loop()

        def stop_signal() -> None:
            self.running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_signal)
            except NotImplementedError:
                pass

        ui_task = asyncio.create_task(self._ui_loop())

        try:
            while self.running:
                try:
                    room_url = self._room_url()
                    async with websockets.connect(room_url, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
                        self.ws = ws
                        self.connected = True
                        await ws.send(json.dumps({"type": "join", "name": self.name}))
                        sender = asyncio.create_task(self._send_frames(ws))
                        receiver = asyncio.create_task(self._recv_messages(ws))
                        done, pending = await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
                        for task in pending:
                            task.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        for task in done:
                            err = task.exception()
                            if err and not isinstance(err, ConnectionClosed):
                                raise err
                except (ConnectionClosed, OSError, asyncio.TimeoutError, ValueError):
                    self.connected = False
                    await asyncio.sleep(2)
                finally:
                    self.connected = False
                    self.ws = None
        finally:
            self.running = False
            ui_task.cancel()
            try:
                await ui_task
            except asyncio.CancelledError:
                pass
            self.camera.close()
            self.ui.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASCII Zoom terminal client")
    parser.add_argument("--server", default="ws://localhost:8765", help="WebSocket server base URL")
    parser.add_argument("--room", required=True, help="Room name")
    parser.add_argument("--name", required=True, help="Display name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = ASCIIZoomClient(server=args.server, room=args.room, name=args.name)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
