from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .credentials import interactive_setup
from .manaba import ManabaClient
from .portal import PortalAuthenticator
from .webforms import AuthenticationError


def keyring_setup() -> None:
    interactive_setup()


def login_test() -> None:
    parser = argparse.ArgumentParser(description="Test CIT Campus authentication without starting MCP.")
    parser.add_argument("target", choices=["portal", "manaba"])
    parser.add_argument("--force", action="store_true", help="Ignore cached session cookies.")
    parser.add_argument("--trace", action="store_true", help="Print a sanitized authentication state trace.")
    parser.add_argument("--debug-html", help="Write the final returned HTML for local debugging. This may contain personal data.")
    args = parser.parse_args()

    if args.target == "portal":
        authenticator = PortalAuthenticator()
        try:
            result = authenticator.login(force=args.force)
        except AuthenticationError as exc:
            print(f"Portal login FAILED: {exc}", file=sys.stderr)
            if args.trace and authenticator.trace:
                print("Sanitized auth trace:", file=sys.stderr)
                print(json.dumps(authenticator.trace, ensure_ascii=False, indent=2), file=sys.stderr)
            if args.debug_html and authenticator.last_response is not None:
                Path(args.debug_html).write_bytes(authenticator.last_response.content)
                print(f"Wrote final response HTML to {args.debug_html}", file=sys.stderr)
            raise SystemExit(2) from exc

        print(f"Portal login OK: {result.response.url}")
        print(f"Session restored: {result.restored}")
        if args.trace and authenticator.trace:
            print("Sanitized auth trace:")
            print(json.dumps(authenticator.trace, ensure_ascii=False, indent=2))
        if args.debug_html:
            Path(args.debug_html).write_bytes(result.response.content)
            print(f"Wrote {args.debug_html}")
        return

    client = ManabaClient()
    client.connect(force=args.force)
    courses = client.list_courses()
    print(f"manaba login OK: {len(courses)} course links detected")
