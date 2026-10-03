# cli-chess

Chess in your terminal. Play locally, against Stockfish, or online with a game code.
Works on Linux and Windows (use Windows Terminal; add `--ascii` if pieces look wrong).

## Install & run

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
chess-cli            # menu
chess-cli --ascii    # letters instead of unicode pieces
```

## Playing

- **Typed moves** (always available): `e4`, `Nf3`, `exd5`, `O-O`, `e8=Q`, `e2e4`, `e2 e4`, `nf3`
- **Mouse**: click a piece, then a highlighted square. **Keyboard**: `Tab` to focus the board,
  arrow keys + `Enter`/`Space` to select. Typing a letter while the board is focused jumps to the move box.
- **Commands** (type in the move box): `undo`, `flip`, `resign`, `draw`, `decline`, `save` (writes a PGN
  to the current directory), `menu`, `help`. `Ctrl+B` also goes back to the menu.

## Stockfish (optional)

Not bundled. It's found via, in order: the `STOCKFISH_PATH` env var, `stockfish_path` in the config file
(`~/.config/chess-cli/config.json`, `%APPDATA%\chess-cli\config.json` on Windows), then your `PATH`.
On Arch it's available from the AUR; or download a binary from https://stockfishchess.org and point
`STOCKFISH_PATH` at it.

## Multiplayer

One player runs the relay server and exposes it with a tunnel; both players then connect to it.

```bash
chess-cli server                         # listens on ws://127.0.0.1:8765
cloudflared tunnel --url http://localhost:8765   # prints https://<random>.trycloudflare.com
```

In the menu, enter the tunnel URL (the host can leave the default `ws://localhost:8765`), then
**Online: create game** to get a 4-letter code, and the other player enters it under **Online: join game**.
On a LAN, skip the tunnel: run `chess-cli server --host 0.0.0.0` and use `ws://<host-ip>:8765`.
The server validates every move, so clients can't cheat or desync.

## Tests

```bash
pip install -e '.[dev]' && pytest
```
