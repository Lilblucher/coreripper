import json
import urllib.request
import socket

def get_ip_info(domain):
    try:
        # First resolve the domain to an IP
        ip = socket.gethostbyname(domain)
        # Query a free geolocation API
        url = f"http://ip-api.com/json/{ip}"
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode())
            return {"status": "success", "result": data}
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch IP details: {str(e)}"}