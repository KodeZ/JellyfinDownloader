"""Main entry point for JellyfinDownloader."""

import argparse
import sys
import getpass
import logging
import requests
from urllib.parse import urlparse

from .config import load_config, save_config
from .api import jget, authenticate
from .ui import handle_series, handle_movies, settings_menu


def _configure_logging():
    """Route jellydown.* loggers to stdout for the classic CLI.

    Plain message format keeps output indistinguishable from the previous
    print()-based UX. The TUI will install its own handler instead.
    """
    root = logging.getLogger("jellydown")
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False


def authentication_flow(base):
    print("\nAuthentication required.")
    print("1. Login with Username/Password (recommended)")
    print("2. Enter API Key manually")
    print("Note: Username/password is used only once to generate an access token.")
    api_key = ""
    while not api_key:
        choice = input("Select [1/2]: ").strip()
        if choice == "1":
            username = input("Username: ").strip()
            password = getpass.getpass("Password: ")
            token = authenticate(base, username, password)
            if token:
                api_key = token
                print("Login successful.")
            else:
                print("Login failed, please try again or use API key.")
        elif choice == "2":
            api_key = input("API key: ").strip()
        else:
            print("Invalid choice. Please enter 1 or 2.")
    return api_key


def determine_user_id(base, api_key):
    try:
        me = jget(base, "/Users/Me", api_key)
        user_id = me.get("Id")
        if not user_id:
            print("Could not determine UserId from /Users/Me")
            sys.exit(1)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 and base:
            print("\nAuthentication failed: Invalid or expired API key/token. Trying to get a new one.")
            api_key = authentication_flow(base)
            me = jget(base, "/Users/Me", api_key)
            user_id = me.get("Id")
            return me, user_id, api_key
        raise

    return me, user_id, api_key


def _resolve_server_and_auth(cfg):
    """Resolve server URL + auth, prompting on the console as needed.

    Runs before any UI starts so both the TUI and the classic CLI share the
    same auth flow. Returns (base, api_key, user_id, me).
    """
    base = (cfg.get("server_url") or "").strip()
    if not base:
        base = input("Jellyfin server URL (e.g. http://192.168.0.1:8096): ").strip()

    if not base.startswith(("http://", "https://")):
        base = "http://" + base

    parsed = urlparse(base)
    if not parsed.port:
        add_port = input("No port specified. Add default port 8096? (Y/n): ").strip().lower()
        if add_port != 'n':
            base = f"{parsed.scheme}://{parsed.hostname}:8096{parsed.path}"

    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        api_key = authentication_flow(base)

    me, user_id, api_key = determine_user_id(base, api_key)

    cfg["server_url"] = base
    cfg["api_key"] = api_key
    save_config(cfg)

    print(f"\nConnected as: {me.get('Name','(unknown)')}  UserId: {user_id}")
    return base, api_key, user_id, me


def _classic_main_loop(base, api_key, user_id, cfg):
    """The previous text-menu UI, kept under --classic for scripting."""
    while True:
        print("\n--- Main Menu ---")
        print("1. Series")
        print("2. Movies")
        print("3. Settings")
        print("q. Quit")

        choice = input("Select an option: ").strip().lower()

        if choice == "1":
            handle_series(base, api_key, user_id, cfg)
        elif choice == "2":
            handle_movies(base, api_key, user_id, cfg)
        elif choice == "3":
            settings_menu(cfg)
        elif choice == "q":
            sys.exit(0)
        else:
            print("Invalid choice.")


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(prog="jellydown")
    parser.add_argument(
        "--classic", action="store_true",
        help="Use the legacy text-menu CLI instead of the TUI.",
    )
    args = parser.parse_args()

    _configure_logging()
    cfg = load_config()
    base, api_key, user_id, _me = _resolve_server_and_auth(cfg)

    if args.classic:
        _classic_main_loop(base, api_key, user_id, cfg)
        return

    from .tui import JellydownApp
    JellydownApp(base, api_key, user_id, cfg).run()


if __name__ == "__main__":
    main()
