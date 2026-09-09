import platform
import re
import statistics
import subprocess

HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$'
)


def is_valid_target(target):
    """Basic validation so we never hand a garbage/hostile string to subprocess."""
    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', target):
        return all(0 <= int(p) <= 255 for p in target.split('.'))
    return bool(HOSTNAME_RE.match(target))


def get_ping_info(target, count=4):
    if not is_valid_target(target):
        return {"status": "error", "message": f"'{target}' is not a valid hostname or IP address."}

    try:
        is_windows = platform.system().lower() == 'windows'
        count_flag = '-n' if is_windows else '-c'
        timeout_flag = '-w' if is_windows else '-W'
        timeout_value = '2000' if is_windows else '2'  # ms on Windows, seconds on Linux/macOS

        cmd = ['ping', count_flag, str(count), timeout_flag, timeout_value, target]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=count * 3 + 5)
        output = result.stdout

        if not output:
            return {"status": "error", "message": f"No response from '{target}'."}

        # Linux/macOS reply line: "64 bytes from 8.8.8.8: icmp_seq=1 ttl=54 time=64.7 ms"
        pattern = re.compile(r'icmp_seq=(\d+).*?ttl=(\d+).*?time=([\d.]+)', re.IGNORECASE)
        replies = []
        for line in output.splitlines():
            match = pattern.search(line)
            if match:
                seq, ttl, time_ms = match.groups()
                replies.append({"icmp_seq": int(seq), "ttl": int(ttl), "time": float(time_ms)})

        if not replies:
            return {
                "status": "error",
                "message": f"Host '{target}' did not respond to any ping  it may be down or blocking ICMP."
            }

        times = [r["time"] for r in replies]
        loss_pct = round((1 - len(replies) / count) * 100, 1)

        return {
            "status": "success",
            "result": {
                "target": target,
                "replies": replies,
                "min": round(min(times), 2),
                "avg": round(statistics.mean(times), 2),
                "max": round(max(times), 2),
                "loss_pct": loss_pct,
            }
        }

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Ping to '{target}' timed out."}
    except FileNotFoundError:
        return {"status": "error", "message": "The 'ping' command is not available on this server."}
    except Exception as e:
        return {"status": "error", "message": f"Ping failed: {str(e)}"}