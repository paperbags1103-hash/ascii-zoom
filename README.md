# ASCII Zoom 🎥

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

```text
   ___   _____  _____ ___ ___   ____   ____   ____  __  __
  / _ | / ___/ / ___/|_ _|_ _| /_  /  / __ \ / __ \|  \/  |
 / __ |/ /__  / /__   | | | |   / /_ / /_/ // /_/ /| |\/| |
/_/ |_|\___/  \___/  |___|___| /___/ \____/ \____/ |_|  |_|

Terminal-based ASCII video conferencing
```

Terminal-based ASCII video conferencing.

## Demo Screenshot

```text
┌──────────────────────────────────────────────────────────────┐
│ ASCII ZOOM | Room: dev-room | Participants: 2/8             │
├──────────────────────────────────────────────────────────────┤
│┌────────────────────────────┐┌──────────────────────────────┐│
││ [gorba (You)]              ││ [friend]                     ││
││$$@@BB%%88&&MM##**ooaahhkk  ││  ..''^^",,;;ii!!~~--__++<<  ││
││ddppqqwwZZ00QQLLCCJJUUYYXX  ││  (({{[[??//\\||11ttffrrnn   ││
││zzccvvuunnxxrrjjfftt/\\|()  ││  WWM##**oahkbdpqwmZO0QLCJU   ││
│└────────────────────────────┘└──────────────────────────────┘│
├──────────────────────────────────────────────────────────────┤
│ [Q] Quit  [M] Mute Camera (OFF)  Status: Connected          │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Start server

```bash
python3 server.py --host 0.0.0.0 --port 8765
```

3. Join room

```bash
python3 client.py --server ws://localhost:8765 --room myroom --name "gorba"
```

## Public Server Option

Deploy the server on Fly.io (`fly.toml` included) and share the URL:

```bash
python3 client.py --server wss://<your-fly-app>.fly.dev --room myroom --name "guest"
```

## Self-Hosting With Docker

```bash
docker build -t ascii-zoom .
docker run --rm -p 8765:8765 ascii-zoom
```

## Controls

- `Q`: Quit
- `M`: Mute/unmute camera

## How It Works

OpenCV + WebRTC-style real-time capture idea -> WebSocket transport -> curses terminal renderer.

Each client captures webcam frames, converts grayscale pixels to ASCII characters, and streams the result to others in the same room.

## Contributing

Issues and pull requests are welcome.

1. Fork the repo
2. Create a feature branch
3. Add or update tests where needed
4. Open a pull request with a clear description

## License

Licensed under the MIT License. See `LICENSE`.
