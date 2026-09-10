# VTT Prototype

Minimal virtual tabletop: a shared map with draggable tokens, a dice roller,
and chat — synced live over a WebSocket to everyone in the same "room".
No accounts, no persistence, no rules engine. Point of this scaffold is to
get something you and a few friends can click around in tonight, then grow
features only as you actually miss them.

## Architecture

```
frontend (React + Vite, port 5173)  <--WebSocket-->  backend (FastAPI, port 8000)
        |                                                    |
   renders board,                                     holds room state
   tokens, dice, chat                                 in memory, rebroadcasts
                                                        every event to all
                                                        clients in the room
```

- **One room = one shared board.** Anyone who opens the app with the same
  room name joins the same session. There's no room list or matchmaking —
  you just tell your friends the room name (e.g. "table1") like a Discord
  voice channel.
- **Server is the source of truth.** Every token move, dice roll, and chat
  message is sent to the backend, which updates its in-memory state and
  broadcasts the result back to *all* connected clients (including the
  sender). Clients never trust their own optimistic state past a round
  trip — this avoids drift between players.
- **State is in-memory only.** Restarting the backend wipes the board.
  That's fine for a prototype; swap in the same SQLite pattern the stock
  dashboard already uses (`watchlist.db`) whenever persistence matters.

## Run it

```bash
# backend
cd vtt-prototype/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# frontend (separate terminal)
cd vtt-prototype/frontend
npm install
npm run dev
```

Open `http://localhost:5173`, set a room name and your player name, and
share the URL (or a Cloudflare tunnel, same trick as `start.bat --tunnel`
in the main project) with your group.

## What's here

| Piece | What it does |
|---|---|
| Board | Grid background, drag tokens with pointer events, double-click to remove |
| Add token | Label + color, drops it in the middle of the board |
| Dice roller | d4–d100, configurable count, result posted to chat |
| Chat | Plain text, broadcast to the room |

## Natural next steps (don't build these until you miss them)

1. **Persistence** — SQLite-backed rooms so a backend restart doesn't wipe
   the board, same pattern as `stock-dashboard-backend/main.py`'s watchlist.
2. **Map images** — let the GM upload/paste a background image instead of
   the plain grid; store as a static file, reference by URL in room state.
3. **Fog of war** — a canvas overlay only the GM can paint/erase; hide
   tokens under unrevealed fog for non-GM clients.
4. **Character sheets** — a per-token data blob (HP, stats) editable in a
   side panel; nothing here yet ties a token to a character.
5. **GM-only controls** — right now anyone can move any token or roll for
   anyone; add a simple GM flag (first client to join a room, or a shared
   password) before it matters for your group.
6. **Initiative tracker** — sort tokens by a rolled/entered initiative
   value, highlight whose turn it is.
