"""Small JSON client for the API tests."""

import json
import urllib.error
import urllib.request


def call(method: str, url: str, body: dict | None = None):
    """Return (status, parsed JSON body)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())
