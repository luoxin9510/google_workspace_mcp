"""Spike test - verify tab operations + markdown writer against a real Google Doc.

This exercises the critical path:
1. OAuth against the user's Google Cloud Project (credentials.json)
2. Docs API - insert a tab via batchUpdate createDocumentTab request
3. Markdown writer - convert a real markdown file to batchUpdate requests
4. Docs API - apply the requests to the new tab
5. Fetch the doc to confirm the tab was populated

Usage:
    python scripts/spike/spike_tab_operations.py

Environment:
    GOOGLE_CLIENT_SECRET_PATH - path to OAuth 2.0 Desktop client JSON
    USER_GOOGLE_EMAIL - the account to authenticate as (for cache keying)

The OAuth token is cached at ~/.workspace-mcp/spike_token.json so subsequent
runs do not require re-consent.
"""

import json
import os
import pathlib
import sys
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Make the fork's modules importable so we can use the markdown writer
FORK_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FORK_ROOT))

from gdocs.docs_markdown_writer import markdown_to_docs_requests  # noqa: E402


SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
TOKEN_CACHE = pathlib.Path.home() / ".workspace-mcp" / "spike_token.json"

# Target doc for the spike. Set via env var so the script is portable -
# any fork contributor can run it against their own scratch Google Doc.
# Matches the env-var convention used by tests/integration/test_update_tab_from_markdown.py.
TARGET_DOC_ID = os.environ.get("INTEGRATION_TEST_DOC_ID", "")
if not TARGET_DOC_ID:
    sys.exit(
        "ERROR - set INTEGRATION_TEST_DOC_ID to a Google Doc ID the spike can "
        "create and delete tabs on. Manually create a scratch Doc in Drive, "
        "copy its ID from the URL, then re-run."
    )
SAMPLE_MD = """# Spike Test Tab

This is a **spike** test verifying that the fork's extended markdown writer
can populate a tab in a real Google Doc.

## What this tests

- OAuth against a user-provided GCP client

- Docs API createDocumentTab request

- Markdown writer emitting tab-targeted batchUpdate requests

- Docs API batchUpdate applying those requests into the tab

If you can read this nicely formatted text, the spike succeeded.

## A code example

```python
from gdocs.docs_markdown_writer import markdown_to_docs_requests
requests = markdown_to_docs_requests(my_markdown, tab_id="t.0.1")
```

That's the main integration point.
"""


def get_credentials() -> Credentials:
    """Run OAuth flow or load cached credentials."""
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET_PATH")
    if not client_secret:
        sys.exit("ERROR - set GOOGLE_CLIENT_SECRET_PATH env var to your credentials.json path")

    creds = None
    if TOKEN_CACHE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_CACHE), SCOPES)
        except Exception as e:
            print(f"Could not load cached token ({e}); re-authenticating")
            creds = None

    if creds and creds.valid:
        print(f"Using cached OAuth token from {TOKEN_CACHE}")
        return creds

    if creds and creds.expired and creds.refresh_token:
        print("Refreshing expired OAuth token")
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Refresh failed ({e}); re-authenticating from scratch")
            creds = None

    if not creds:
        print("Opening browser for OAuth consent...")
        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)

    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(creds.to_json())
    os.chmod(TOKEN_CACHE, 0o600)
    print(f"Saved OAuth token to {TOKEN_CACHE}")
    return creds


def main() -> None:
    creds = get_credentials()
    docs = build("docs", "v1", credentials=creds)

    print(f"\nTarget doc - https://docs.google.com/document/d/{TARGET_DOC_ID}/edit")

    print("\nStep 1 - Create a new tab")
    create_response = docs.documents().batchUpdate(
        documentId=TARGET_DOC_ID,
        body={
            "requests": [
                {
                    "addDocumentTab": {
                        "tabProperties": {
                            "title": f"Spike Test {int(time.time())}",
                            "index": 0,
                        },
                    }
                }
            ]
        },
    ).execute()
    print(f"  Raw response keys - {list(create_response.keys())}")
    reply = create_response["replies"][0]
    print(f"  Reply keys - {list(reply.keys())}")
    # Try both possible response field names
    tab_id = None
    for key in ("addDocumentTab", "createDocumentTab"):
        if key in reply:
            tab_id = reply[key].get("tabProperties", {}).get("tabId")
            print(f"  Found tab under '{key}'")
            break
    if not tab_id:
        print(f"  Raw reply - {json.dumps(reply, indent=2)}")
        sys.exit("ERROR - could not extract tab_id from response")
    print(f"  Created tab - tab_id={tab_id}")

    print("\nStep 2 - Generate markdown -> batchUpdate requests")
    md_requests = markdown_to_docs_requests(SAMPLE_MD, tab_id=tab_id)
    print(f"  Writer produced {len(md_requests)} requests")
    print(f"  Request types - {sorted(set(list(r.keys())[0] for r in md_requests))}")

    print("\nStep 3 - Apply requests to the tab")
    apply_response = docs.documents().batchUpdate(
        documentId=TARGET_DOC_ID,
        body={"requests": md_requests},
    ).execute()
    print(f"  batchUpdate returned {len(apply_response.get('replies', []))} replies")

    print("\nStep 4 - Verify by reading the doc back")
    doc = docs.documents().get(
        documentId=TARGET_DOC_ID,
        includeTabsContent=True,
    ).execute()
    tabs = doc.get("tabs", [])
    target_tab = None
    for t in tabs:
        if t.get("tabProperties", {}).get("tabId") == tab_id:
            target_tab = t
            break
    if not target_tab:
        print(f"  WARNING - could not find tab_id={tab_id} in doc.tabs; doc may be stale")
    else:
        body = target_tab.get("documentTab", {}).get("body", {})
        content = body.get("content", [])
        char_count = 0
        for elem in content:
            for run in elem.get("paragraph", {}).get("elements", []):
                char_count += len(run.get("textRun", {}).get("content", ""))
        print(f"  Tab body has {len(content)} structural elements, {char_count} characters")

    print(f"\n{'='*70}")
    print("SPIKE COMPLETE")
    print(f"{'='*70}")
    print(f"Open in browser to verify - https://docs.google.com/document/d/{TARGET_DOC_ID}/edit")
    print(f"Look for the tab named 'Spike Test ...' and check its content renders correctly.")


if __name__ == "__main__":
    main()
