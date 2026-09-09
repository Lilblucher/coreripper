import urllib.request

def get_http_headers(domain):
    try:
        # Standardize the URL format
        url = f"http://{domain}" if not domain.startswith(('http://', 'https://')) else domain
        
        # Make a quick request with a 3-second timeout
        with urllib.request.urlopen(url, timeout=3) as response:
            headers = response.info()
            # Convert the headers object into a clean Python dictionary
            return {"status": "success", "result": dict(headers.items())}
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch headers: {str(e)}"}