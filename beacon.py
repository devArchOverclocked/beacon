import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ui.app import BeaconApp


def main() -> int:
    app = BeaconApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
