import socket
import urllib.request
import json

def get_ip_geo_info(target):
    """
    Resolves a target domain or IP, queries a geolocation API,
    and returns structured location and provider metadata.
    """
    # 1. Sanitize input and resolve target to an IP address if a domain was provided
    try:
        target_ip = socket.gethostbyname(target.strip())
    except socket.gaierror:
        return {"status": "error", "message": "Invalid domain or IP address formatting."}

    # 2. Query the geolocation API endpoint
    # We explicitly request the JSON structure matching your frontend keys
    url = f"http://ip-api.com/json/{target_ip}"
    
    try:
        # Use Python's built-in urllib to make an insulated HTTP request
        req = urllib.request.Request(url, headers={'User-Agent': 'CoreLoomSuite/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            api_data = json.loads(response.read().decode('utf-8'))
            
        # 3. Parse and validate the response payload
        if api_data.get("status") == "success":
            return {
                "status": "success",
                "result": {
                    "query": api_data.get("query"),           # Actual resolved IP
                    "city": api_data.get("city", "N/A"),
                    "regionName": api_data.get("regionName", "N/A"),
                    "country": api_data.get("country", "N/A"),
                    "isp": api_data.get("isp", "N/A")
                }
            }
        else:
            error_msg = api_data.get("message", "API lookup rejected destination.")
            return {"status": "error", "message": f"Geolocation failed: {error_msg}"}
            
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"Network gateway timed out: {str(e.reason)}"}
    except Exception as e:
        return {"status": "error", "message": f"Internal mapping failure: {str(e)}"}