import platform
import re
import socket
import subprocess

from .ping_tool import is_valid_target

MAX_HOPS = 20
QUERIES_PER_HOP = 3
TIMEOUT_PER_HOP_SECONDS = 2

# Matches a hop reply segment like "33.028 ms" or a timed-out probe "*"
_RTT_RE = re.compile(r'(\d+\.\d+)\s*ms|\*')

# Matches "hop-1.isp.net (192.168.1.1)  33.028 ms  33.712 ms  11.334 ms"
_HOST_IP_RE = re.compile(r'^(\S+)\s+\(([^)]+)\)\s*(.*)$')


def _parse_hop_line(line):
    m = re.match(r'^\s*(\d+)\s+(.*)$', line)
    if not m:
        return None

    hop_num = int(m.group(1))
    rest = m.group(2).strip()

    if not rest or rest.startswith('*'):
        return {"hop": hop_num, "hostname": None, "ip": None, "rtts": [None, None, None]}

    host_match = _HOST_IP_RE.match(rest)
    if host_match:
        hostname, ip, times_part = host_match.groups()
        if hostname == ip:
            hostname = None  # no reverse DNS available for this hop
    else:
        hostname, ip, times_part = None, None, rest

    rtts = []
    for match in _RTT_RE.finditer(times_part):
        rtts.append(float(match.group(1)) if match.group(1) else None)
    while len(rtts) < QUERIES_PER_HOP:
        rtts.append(None)

    return {"hop": hop_num, "hostname": hostname, "ip": ip, "rtts": rtts[:QUERIES_PER_HOP]}


def get_traceroute(target):
    if not is_valid_target(target):
        return {"status": "error", "message": f"'{target}' is not a valid hostname or IP address."}

    if platform.system().lower() == 'windows':
        return {
            "status": "error",
            "message": "Traceroute is currently only supported when the server runs on Linux/macOS."
        }

    try:
        cmd = [
            'traceroute',
            '-m', str(MAX_HOPS),
            '-q', str(QUERIES_PER_HOP),
            '-w', str(TIMEOUT_PER_HOP_SECONDS),
            target,
        ]
        timeout_budget = MAX_HOPS * QUERIES_PER_HOP * TIMEOUT_PER_HOP_SECONDS // 3 + 15
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_budget)
        output = result.stdout

        if not output:
            return {"status": "error", "message": f"No traceroute output for '{target}'."}

        hops = []
        for line in output.splitlines():
            hop = _parse_hop_line(line)
            if hop:
                hops.append(hop)

        if not hops:
            return {"status": "error", "message": f"Could not trace a route to '{target}'."}

        try:
            dest_ip = socket.gethostbyname(target)
        except socket.gaierror:
            dest_ip = None

        reached = bool(dest_ip and hops[-1]["ip"] == dest_ip)

        return {
            "status": "success",
            "result": {
                "target": target,
                "destination_ip": dest_ip,
                "hop_count": len(hops),
                "reached": reached,
                "hops": hops,
            }
        }

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Traceroute to '{target}' timed out."}
    except FileNotFoundError:
        return {"status": "error", "message": "The 'traceroute' command is not available on this server."}
    except Exception as e:
        return {"status": "error", "message": f"Traceroute failed: {str(e)}"}