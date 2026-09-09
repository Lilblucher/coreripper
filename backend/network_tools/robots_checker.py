"""
Robots.txt Tester  fetches a domain's robots.txt and tests whether a given
path is allowed for a given user-agent, using Python's stdlib
urllib.robotparser (the same rule semantics real crawlers implement).
"""
import http.client
import socket
import urllib.error
import urllib.request
import urllib.robotparser

_MAX_BYTES = 500_000


def _normalize_domain(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def test_robots_txt(target, path="/", user_agent="*"):
    base_url = _normalize_domain(target)
    if not base_url:
        return {"status": "error", "message": "Please provide a domain."}

    path = (path or "/").strip() or "/"
    user_agent = (user_agent or "*").strip() or "*"

    robots_url = base_url.rstrip("/") + "/robots.txt"

    req = urllib.request.Request(robots_url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            try:
                raw_bytes = response.read(_MAX_BYTES)
            except http.client.IncompleteRead as e:
                raw_bytes = e.partial
            raw = raw_bytes.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {
                "status": "success",
                "result": {
                    "domain": base_url,
                    "robots_txt_found": False,
                    "raw_robots_txt": None,
                    "path_tested": path,
                    "user_agent_tested": user_agent,
                    "allowed": True,  # missing robots.txt = allow everything, by convention
                    "note": "No robots.txt found  by convention, crawlers treat a missing file as 'allow everything'.",
                },
            }
        return {"status": "error", "message": f"Server returned {e.code} {e.reason} fetching robots.txt."}
    except (urllib.error.URLError, socket.timeout) as e:
        return {"status": "error", "message": f"Could not reach {base_url}: {getattr(e, 'reason', e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(raw.splitlines())

    test_url = base_url.rstrip("/") + "/" + path.lstrip("/")
    allowed = parser.can_fetch(user_agent, test_url)

    return {
        "status": "success",
        "result": {
            "domain": base_url,
            "robots_txt_found": True,
            "raw_robots_txt": raw,
            "path_tested": path,
            "user_agent_tested": user_agent,
            "allowed": allowed,
            "note": None,
        },
    }
