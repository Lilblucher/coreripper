import socket
import ssl

def get_ssl_info(domain):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=3) as sock:
            with context.wrap_socket(sock, server_hostname= domain) as ssock:
                cert = ssock.getpeercert()
                
                return {"status": "success", "result": cert}
    except Exception as e:
        return {"status": "error", "message": f"SSL/TLS handshake failed: {str(e)}"}