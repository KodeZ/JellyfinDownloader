"""Main entry point for JellyfinDownloader."""

import sys
import getpass
import requests
from urllib.parse import urlparse

from .config import load_config, save_config
from .api import jget, authenticate
from .ui import handle_series, handle_movies, settings_menu

def main():
    """Main application entry point."""
    cfg = load_config()

    base = (cfg.get("server_url") or "").strip()
    if not base:
        base = input("Jellyfin server URL (e.g. http://192.168.0.1:8096): ").strip()

    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    
    # Check if port is specified
    parsed = urlparse(base)
    if not parsed.port:
        add_port = input("No port specified. Add default port 8096? (Y/n): ").strip().lower()
        if add_port != 'n':
            base = f"{parsed.scheme}://{parsed.hostname}:8096{parsed.path}"

    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        print("\nAuthentication required.")
        print("1. Login with Username/Password (recommended)")
        print("2. Enter API Key manually")
        print("Note: Username/password is used only once to generate an access token.")
        
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

    cfg["server_url"] = base
    cfg["api_key"] = api_key
    save_config(cfg)

    # Determine UserId
    try:
        me = jget(base, "/Users/Me", api_key)
        user_id = me.get("Id")
        if not user_id:
            print("Could not determine UserId from /Users/Me")
            sys.exit(1)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("\nAuthentication failed: Invalid or expired API key/token.")
            print("Please delete jellydown.json and try again to re-authenticate.")
            sys.exit(1)
        raise

    print(f"\nConnected as: {me.get('Name','(unknown)')}  UserId: {user_id}")

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

if __name__ == "__main__":
    main()
