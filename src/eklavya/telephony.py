"""Place one or more outbound Twilio calls into the Pipecat bot."""

import argparse
import os
from urllib.parse import urlsplit, urlunsplit
from xml.sax.saxutils import quoteattr

from dotenv import load_dotenv
from twilio.rest import Client


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value


def twilio_client() -> Client:
    account_sid = require_env("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    api_key_sid = os.getenv("TWILIO_API_KEY_SID")
    api_key_secret = os.getenv("TWILIO_API_KEY_SECRET")

    # Account credentials are the most broadly compatible option, including
    # trial accounts. A deployed service can omit TWILIO_AUTH_TOKEN to use the
    # more narrowly scoped API key instead.
    if auth_token:
        return Client(account_sid, auth_token)

    if api_key_sid and api_key_secret:
        return Client(api_key_sid, api_key_secret, account_sid)

    raise RuntimeError(
        "Set TWILIO_AUTH_TOKEN or both TWILIO_API_KEY_SID and "
        "TWILIO_API_KEY_SECRET in .env"
    )


def media_stream_url(public_url: str) -> str:
    """Convert the bot's public HTTP origin into its telephony WebSocket URL."""
    parsed = urlsplit(public_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("PIPECAT_PUBLIC_URL must be a full http(s) URL")

    websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
    websocket_path = f"{parsed.path.rstrip('/')}/ws"
    return urlunsplit((websocket_scheme, parsed.netloc, websocket_path, "", ""))


def main() -> None:
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description="Call E.164 phone numbers and connect them to the Pipecat bot."
    )
    parser.add_argument(
        "to",
        nargs="+",
        help="One or more destination numbers in E.164 format, such as +15551234567",
    )
    args = parser.parse_args()

    websocket_url = media_stream_url(require_env("PIPECAT_PUBLIC_URL"))
    from_number = require_env("TWILIO_PHONE_NUMBER")
    client = twilio_client()

    # Supplying TwiML inline lets the Pipecat runner remain in multi-transport
    # mode, where the browser UI and Twilio's /ws stream work simultaneously.
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Connect><Stream url={quoteattr(websocket_url)} />"
        "</Connect></Response>"
    )

    for destination in args.to:
        if not destination.startswith("+"):
            raise ValueError(f"Destination must use E.164 format: {destination!r}")

        call = client.calls.create(
            to=destination,
            from_=from_number,
            twiml=twiml,
        )
        print(f"Queued call {call.sid} ({call.status})")


if __name__ == "__main__":
    main()
