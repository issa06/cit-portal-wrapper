from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .credentials import interactive_setup
from .errors import public_error
from .manaba import ManabaClient
from .portal import PortalAuthenticator


def keyring_setup() -> None:
    try:
        interactive_setup()
    except Exception:
        print("Keychain setup failed; check Keychain access permissions.", file=sys.stderr)
        raise SystemExit(2) from None


def _private_html(path: str, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)


def login_test() -> None:
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description="Test CIT Campus authentication without starting MCP.")
    parser.add_argument("target", choices=["portal", "manaba"])
    parser.add_argument("--force", action="store_true", help="Ignore cached session cookies.")
    parser.add_argument("--trace", action="store_true", help="Print a sanitized authentication state trace.")
    parser.add_argument(
        "--debug-html", help="Write the final returned HTML for local debugging. This may contain personal data."
    )
    args = parser.parse_args()

    if args.target == "portal":
        authenticator = PortalAuthenticator()
        try:
            result = authenticator.login(force=args.force)
        except Exception as exc:
            print(json.dumps({"error": public_error(exc)}), file=sys.stderr)
            if args.trace and authenticator.trace:
                print("Sanitized auth trace:", file=sys.stderr)
                print(json.dumps(authenticator.trace, ensure_ascii=False, indent=2), file=sys.stderr)
            if args.debug_html and authenticator.last_response is not None:
                _private_html(args.debug_html, authenticator.last_response.content)
                print("Wrote private local debug HTML.", file=sys.stderr)
            raise SystemExit(2) from None

        print("Portal login OK")
        print(f"Session restored: {result.restored}")
        if args.trace and authenticator.trace:
            print("Sanitized auth trace:")
            print(json.dumps(authenticator.trace, ensure_ascii=False, indent=2))
        if args.debug_html:
            _private_html(args.debug_html, result.response.content)
            print("Wrote private local debug HTML.")
        return

    client = ManabaClient()
    try:
        client.connect(force=args.force)
        client.list_courses()
        print("manaba login OK")
    except Exception as exc:
        print(json.dumps({"error": public_error(exc)}), file=sys.stderr)
        raise SystemExit(2) from None
