import socket
from concurrent.futures import ThreadPoolExecutor

def scan_port(ip, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            result = s.connect_ex((ip, port))
            if result == 0:
                try:
                    service = socket.getservbyport(port, "tcp")
                except OSError:
                    service = "Unknown"

                return {
                    "port": port,
                    "status": "open",
                    "service": service
                }
    except OSError:
        pass
    return None


def scan_ports(domain):
    try:
        target_ip = socket.gethostbyname(domain)
    except socket.gaierror:
        return {
            "status": "error",
            "message": f"Could not resolve domain: {domain}"
        }

    common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 3389, 8080]

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda port: scan_port(target_ip, port), common_ports))

    # Build a lookup of port -> open-port info, so we can report every
    # scanned port (open AND closed), not just the open ones.
    open_by_port = {r["port"]: r for r in results if r}

    ports = []
    for port in common_ports:
        open_info = open_by_port.get(port)
        if open_info:
            ports.append({
                "port": port,
                "protocol": "TCP",
                "service": open_info["service"],
                "state": "open",
            })
        else:
            try:
                service = socket.getservbyport(port, "tcp")
            except OSError:
                service = "Unknown"
            ports.append({
                "port": port,
                "protocol": "TCP",
                "service": service,
                "state": "closed",
            })

    open_count = len(open_by_port)

    return {
        "status": "success",
        "result": {
            "domain": domain,
            "ip": target_ip,
            "ports_scanned": len(common_ports),
            "open_count": open_count,
            "closed_count": len(common_ports) - open_count,
            "ports": ports,
        }
    }


print(scan_ports("google.com"))