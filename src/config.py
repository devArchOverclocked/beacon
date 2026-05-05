from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Config:
    sharepoint_root_url: str = ""
    refresh_interval_hours: int = 4
    hotkey: str = "ctrl+space"
    open_in_browser: bool = False

    # ---------------------------------------------------------------------------
    # Derived paths
    # ---------------------------------------------------------------------------

    @property
    def app_dir(self) -> Path:
        """Return %APPDATA%/Beacon on Windows; fall back to ~/.Beacon elsewhere."""
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Beacon"
        return Path.home() / ".Beacon"

    @property
    def db_path(self) -> Path:
        return self.app_dir / "beacon.db"

    @property
    def session_path(self) -> Path:
        """Playwright storage-state JSON written after interactive login."""
        return self.app_dir / "session.json"

    @property
    def config_path(self) -> Path:
        return self.app_dir / "config.json"

    # ---------------------------------------------------------------------------
    # Business logic helpers
    # ---------------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True when the user has supplied a SharePoint root URL."""
        return bool(self.sharepoint_root_url.strip())

    # ---------------------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------------------

    @classmethod
    def load(cls) -> "Config":
        """Load config from disk.  Returns a default instance when the file is
        missing or unreadable."""
        instance = cls()
        config_file = instance.config_path
        if not config_file.exists():
            return instance
        try:
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            # Only overwrite fields that are actually present in the file so
            # that newly added fields keep their dataclass defaults.
            for key in (
                "sharepoint_root_url",
                "refresh_interval_hours",
                "hotkey",
                "open_in_browser",
            ):
                if key in raw:
                    setattr(instance, key, raw[key])
        except Exception:
            # Corrupt file — return defaults
            pass
        return instance

    def save(self) -> None:
        """Persist current config to disk, creating the app directory if needed."""
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(asdict(self), indent=2), encoding="utf-8"
        )
