import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from network_tools.dns_lookup import dns_lookup


def test_dns_lookup_returns_ip_for_known_domain():
    result = dns_lookup("example.com")
    assert "example.com" in result
    assert "93.184.216.34" in result
