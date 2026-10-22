"""One-time setup: save the Garmin Personal API key where Garmin's client looks for it.

The key is read without echoing it, written readable only by you, and never
printed or logged.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from garmin_personal_api import GarminPersonalApiError, PersonalApiAuthenticator
from garmin_personal_api.constants import DEFAULT_API_KEY_FILE

KEY_PAGE = "https://connect.garmin.com/app/settings/personalApiToken"


def save_key(key: str, path: Path) -> None:
    """Write the key with owner-only permissions, replacing any old one."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    os.chmod(path, 0o600)  # in case the file already existed with looser permissions


def check_key(key: str) -> str | None:
    """Ask Garmin for a token. Returns None if the key works, or the error."""
    try:
        with PersonalApiAuthenticator() as auth:
            auth.obtain_token(key)
    except GarminPersonalApiError as e:
        return str(e)
    return None


def setup(path: Path | None = None) -> int:
    path = (path or DEFAULT_API_KEY_FILE).expanduser()
    print("easy-or-not reads your runs with a Garmin Personal API key.")
    print(f"Create one at {KEY_PAGE}")
    print("(Garmin shows it once, so copy it before closing the page.)")
    print()
    key = getpass.getpass("Paste your key (it will not be shown): ").strip()
    if not key:
        print("No key entered; nothing saved.")
        return 1

    save_key(key, path)
    print(f"Saved to {path}, readable only by you.")
    print("Checking it with Garmin...")
    error = check_key(key)
    if error:
        print(f"Garmin did not accept it: {error}")
        print("Check you copied the whole key, then run easy-or-not setup again.")
        return 1
    print("Key works. Now run: easy-or-not")
    return 0
