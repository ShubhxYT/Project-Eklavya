"""Pipecat dev-runner entrypoint.

Run with:
    uv run bot.py
"""

from eklavya.app import _load_twilio_ice_servers, app, bot  # noqa: F401

if __name__ == "__main__":
    _load_twilio_ice_servers()

    from pipecat.runner.run import main

    main()
