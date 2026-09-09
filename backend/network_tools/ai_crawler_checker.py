"""
AI-Crawler / robots.txt / llms.txt Checker  fetches a domain's robots.txt
and evaluates it against a maintained list of known AI-crawler user-agents,
using the same stdlib urllib.robotparser semantics as robots_checker.py.
Also checks for the presence of an llms.txt file, and offers a pure
client-side llms.txt skeleton generator (ported to JS in the frontend page 
no lookups needed for that half).

Pure stdlib (urllib)  no external dependencies.
"""
import http.client
import socket
import urllib.error
import urllib.request
import urllib.robotparser

_MAX_BYTES = 500_000

KNOWN_AI_CRAWLERS = [
    "GPTBot", "ChatGPT-User", "ClaudeBot", "Claude-Web", "anthropic-ai",
    "PerplexityBot", "Google-Extended", "CCBot", "cohere-ai",
    "Applebot-Extended", "Bytespider", "Amazonbot",
]


def _normalize_domain(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _fetch_text(url, timeout=10):
    """Returns (found, raw_text_or_None, error_message_or_None)."""
    req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            try:
                raw_bytes = response.read(_MAX_BYTES)
            except http.client.IncompleteRead as e:
                raw_bytes = e.partial
            return True, raw_bytes.decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None, None
        return False, None, f"Server returned {e.code} {e.reason}."
    except (urllib.error.URLError, socket.timeout) as e:
        return False, None, f"Could not reach the server: {getattr(e, 'reason', e)}"
    except Exception as e:
        return False, None, f"Unexpected error: {str(e)}"


def _rule_source_for(parser, bot):
    """Which block of the robots.txt decided this bot's outcome."""
    bot_lower = bot.lower()
    for entry in parser.entries:
        if any(ua.lower() == bot_lower for ua in entry.useragents):
            return f"explicit 'User-agent: {bot}' block"
    if parser.default_entry is not None:
        return "wildcard 'User-agent: *' block"
    return "no matching rule (default allow)"


def check_ai_crawlers(target):
    base_url = _normalize_domain(target)
    if not base_url:
        return {"status": "error", "message": "Please provide a domain."}

    robots_url = base_url.rstrip("/") + "/robots.txt"
    llms_url = base_url.rstrip("/") + "/llms.txt"

    robots_found, robots_raw, robots_error = _fetch_text(robots_url)
    if robots_error:
        return {"status": "error", "message": f"Could not fetch robots.txt: {robots_error}"}

    matrix = []
    if robots_found:
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(robots_raw.splitlines())
        for bot in KNOWN_AI_CRAWLERS:
            allowed = parser.can_fetch(bot, "/")
            matrix.append({
                "bot": bot,
                "status": "allowed" if allowed else "blocked",
                "decided_by": _rule_source_for(parser, bot),
            })
    else:
        for bot in KNOWN_AI_CRAWLERS:
            matrix.append({
                "bot": bot,
                "status": "not_mentioned",
                "decided_by": "no robots.txt found  allowed by convention",
            })

    blocked_count = sum(1 for row in matrix if row["status"] == "blocked")
    allowed_count = len(matrix) - blocked_count

    llms_found, llms_raw, _ = _fetch_text(llms_url)
    llms_valid = bool(llms_found and llms_raw and llms_raw.strip() and "#" in llms_raw)

    if blocked_count == 0:
        summary = f"All {len(matrix)} known AI crawlers are allowed to access this site."
    elif blocked_count == len(matrix):
        summary = f"All {len(matrix)} known AI crawlers are blocked from this site."
    else:
        summary = f"{blocked_count} of {len(matrix)} known AI crawlers are blocked; {allowed_count} are allowed."

    return {
        "status": "success",
        "result": {
            "domain": base_url,
            "robots_txt_found": robots_found,
            "matrix": matrix,
            "summary": summary,
            "llms_txt_found": bool(llms_found),
            "llms_txt_valid": llms_valid,
        },
    }
