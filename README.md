# ASCII Zoom 🎥

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

```
   _   ___  ____ ___ ___   ____  ____  ____  __  __
  /_\ / __||  __/|_ _|_ _| |_  / / __ \/ __ \|  \/  |
 / _ \\__ \| |__  | | | |   / / / /_/ // /_/ /| |\/| |
/_/ \_\___/|____||___|___| /___/ \____/ \____/ |_|  |_|
```

**Terminal-based ASCII video conferencing.**  
See your friends as ASCII art. No app install needed.

---

## ✨ Features

- 🎥 **Live webcam → ASCII art** in real-time
- 💬 **Text chat** built-in (no separate app needed)
- 🌐 **Browser client** — works on iPhone, iPad, any browser (no install)
- 💻 **Terminal client** — Python CLI for maximum hacker vibes
- 🏠 **Multi-room** — create unlimited private rooms with a room name
- 👥 **Up to 8 participants** per room
- 🔒 **No accounts** — just a room name and your name
- 🆓 **Free** — hosted on Render.com free tier

---

## 🚀 Quick Start (Browser)

Just open in any browser — no installation needed:

**https://ascii-zoom.onrender.com**

1. Enter a room name (e.g. `myroom`) — anyone with the same name joins your room
2. Enter your display name
3. Click **Join** → allow camera access
4. Share the room name with friends

> Works on iPhone Safari, iPad, Chrome, Firefox, Edge.

---

## 💻 Terminal Client (Python)

For the full hacker terminal experience:

```bash
# Install dependencies
pip install opencv-python websockets

# macOS/Linux
pip install opencv-python websockets
python3 client.py --server wss://ascii-zoom.onrender.com --room myroom --name "YourName"

# Windows (extra step needed)
pip install opencv-python websockets windows-curses
curl -o client.py https://raw.githubusercontent.com/paperbags1103-hash/ascii-zoom/master/client.py
python client.py --server wss://ascii-zoom.onrender.com --room myroom --name "YourName"
```

### Terminal Controls

| Key | Action |
|-----|--------|
| `Q` | Quit |
| `M` | Mute/unmute camera |
| `Enter` | Focus chat input |
| `Esc` | Cancel chat input |

---

## 🐳 Self-Hosting with Docker

```bash
git clone https://github.com/paperbags1103-hash/ascii-zoom.git
cd ascii-zoom
docker build -t ascii-zoom .
docker run --rm -p 8765:8765 ascii-zoom
```

Connect with your own server:
```bash
python3 client.py --server ws://localhost:8765 --room myroom --name "YourName"
# or browser: http://localhost:8765
```

---

## ☁️ Deploy to Fly.io

```bash
fly launch --name ascii-zoom-yourname
fly deploy
```

---

## 🏗️ Architecture

```
Browser/Terminal Client
        ↕ WebSocket (wss://)
   aiohttp Server
        ↕ asyncio broadcast
   All participants in room
```

- **Server**: Python + aiohttp (WebSocket + HTTP in one process)
- **Client (terminal)**: Python + OpenCV + curses
- **Client (browser)**: Vanilla JS + getUserMedia + Canvas
- **Image processing**: CLAHE contrast enhancement + Canny edge detection + sharpening kernel
- **Protocol**: JSON messages (`join`, `frame`, `chat`, `participant_join`, `participant_leave`)
- **Frame size**: 120×55 chars per participant

---

## 🔧 How It Works

1. Each client captures webcam frames (10 FPS)
2. Frames are converted to ASCII using a 70-character grayscale gradient
3. Contrast is enhanced with CLAHE + edge detection to make faces pop
4. ASCII frames are sent to the server via WebSocket
5. Server broadcasts each participant's frame to all others in the room
6. Each client renders the grid of participants in real-time

---

## 📦 Requirements

**Server**: Python 3.9+, aiohttp  
**Terminal client**: Python 3.9+, opencv-python, websockets, numpy  
**Browser client**: Modern browser with `getUserMedia` support (Chrome, Safari, Firefox)

---

## 📄 License

MIT © 2026 gorba
