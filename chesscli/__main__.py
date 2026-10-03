import argparse
import asyncio


def main() -> None:
    parser = argparse.ArgumentParser(prog="chess-cli", description="Chess in your terminal.")
    parser.add_argument("--ascii", action="store_true", help="use letters instead of unicode chess pieces")
    sub = parser.add_subparsers(dest="command")
    srv = sub.add_parser("server", help="run the multiplayer relay server")
    srv.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to accept LAN connections")
    srv.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.command == "server":
        from .server import run
        try:
            asyncio.run(run(args.host, args.port))
        except KeyboardInterrupt:
            pass
    else:
        from .app import ChessApp
        ChessApp(ascii_only=args.ascii).run()


if __name__ == "__main__":
    main()
