"""
Redirect Checker  follows a URL's redirect chain manually (rather than
letting urllib auto-follow) so each hop's status code and Location header
can be reported individually, not just the final destination.
"""
import socket
import urllib.error
import urllib.parse
import urllib.request

MAX_HOPS = 10


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # tells urlopen not to auto-follow


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def get_redirect_chain(target):
    url = _normalize_url(target)
    if not url:
        return {"status": "error", "message": "Please provide a URL."}

    opener = urllib.request.build_opener(_NoRedirectHandler)
    hops = []
    seen = set()
    current_url = url
    loop_detected = False
    max_hops_reached = False

    for i in range(MAX_HOPS):
        if current_url in seen:
            loop_detected = True
            break
        seen.add(current_url)

        req = urllib.request.Request(current_url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
        try:
            with opener.open(req, timeout=10) as response:
                hops.append({"url": current_url, "status_code": response.status, "location": None})
                break
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location")
            hops.append({"url": current_url, "status_code": e.code, "location": location})
            is_redirect = 300 <= e.code < 400 and location
            if not is_redirect:
                break
            current_url = urllib.parse.urljoin(current_url, location)
            if i == MAX_HOPS - 1:
                max_hops_reached = True
        except (urllib.error.URLError, socket.timeout) as e:
            if not hops:
                return {"status": "error", "message": f"Could not reach {current_url}: {getattr(e, 'reason', e)}"}
            hops.append({"url": current_url, "status_code": None, "location": None, "note": f"Request failed: {getattr(e, 'reason', e)}"})
            break
        except Exception as e:
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    return {
        "status": "success",
        "result": {
            "original_url": url,
            "hop_count": len(hops),
            "hops": hops,
            "final_url": current_url,
            "loop_detected": loop_detected,
            "max_hops_reached": max_hops_reached,
        },
    }
