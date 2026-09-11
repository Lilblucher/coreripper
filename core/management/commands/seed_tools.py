from django.core.management.base import BaseCommand

from core.models import Tool

# Dev tools run entirely client-side (browser JS)  no server operation to gate,
# so they carry no tool_key. Tier 'local' (free-tier eligible) for consistency.
DEV_TOOLS = [
    ("JSON Formatter", "dev-tools/json_formatter.html"),
    ("JSON Validator", "dev-tools/json_validator.html"),
    ("JSON Minifier", "dev-tools/json_minifier.html"),
    ("Base64 Encode / Decode", "dev-tools/base64.html"),
    ("URL Encode / Decode", "dev-tools/url_encode_decode.html"),
    ("HTML Encode / Decode", "dev-tools/html_encode_decode.html"),
    ("HTML Formatter", "dev-tools/html_formatter.html"),
    ("CSS Formatter", "dev-tools/css_formatter.html"),
    ("JavaScript Formatter", "dev-tools/js_formatter.html"),
    ("SQL Formatter", "dev-tools/sql_formatter.html"),
    ("XML Formatter", "dev-tools/xml_formatter.html"),
    ("YAML Formatter", "dev-tools/yaml_formatter.html"),
    ("Password Generator", "dev-tools/password_generator.html"),
    ("Password Strength Checker", "dev-tools/password_strength_checker.html"),
    ("JWT Decoder", "dev-tools/jwt_decoder.html"),
    ("Hash Generator", "dev-tools/hash_generator.html"),
    ("Regex Tester", "dev-tools/regex_tester.html"),
    ("Word Counter", "dev-tools/word_counter.html"),
    ("Character Counter", "dev-tools/character_counter.html"),
    ("Slug Generator", "dev-tools/slug_generator.html"),
    ("Case Converter", "dev-tools/case_converter.html"),
    ("Color Picker", "dev-tools/color_picker.html"),
    ("HEX ↔ RGB Converter", "dev-tools/hex_rgb_converter.html"),
    ("CSS Gradient Generator", "dev-tools/css_gradient_generator.html"),
    ("UUID Generator", "dev-tools/uuid_generator.html"),
    ("Timestamp Converter", "dev-tools/timestamp_converter.html"),
    ("Markdown Preview", "dev-tools/markdown_preview.html"),
    ("Email Header Analyzer", "dev-tools/email_header_analyzer.html"),
    ("Password Breach Checker", "dev-tools/password_breach_checker.html"),
]

# AI tools all hit core/llm.py (real per-call cost) → tier 'api' (Premium only).
# They dispatch through core's own views, not /api/toolbox/, so tool_key stays
# blank for now  Stage 1 gates the network toolbox; AI-view gating is separate.
AI_TOOLS = [
    ("Citation Formatter", "ai-tools/citation_formatter.html"),
    ("Coding Helper", "ai-tools/coding_helper.html"),
    ("Explain My Feedback Tutor", "ai-tools/feedback_tutor.html"),
    ("Grammar & Clarity Checker", "ai-tools/grammar_checker.html"),
    ("Lecture Transcript", "ai-tools/lecture_transcript.html"),
    ("Math Solver", "ai-tools/math_solver.html"),
    ("Paraphrase Similarity Checker", "ai-tools/paraphrase_checker.html"),
    ("PDF / Reading Summarizer", "ai-tools/pdf_summarizer.html"),
    ("Quiz / Flashcard Generator", "ai-tools/quiz_generator.html"),
    ("Readability & Tone Analyzer", "ai-tools/readability_analyzer.html"),
]

# Network tools: (name, path, tool_key, tier).
#   tool_key = the /api/toolbox/?tool=… dispatch key (blank = frontend-only).
#   tier     = 'local' (free-tier eligible) or 'api' (Premium only).
# API tools: ip_info/ip_geo (ip-api.com), asn_lookup (RIR data), reverse_ip
# (HackerTarget), web_screenshot (headless-browser infra cost).
# Judgment calls resolved this session: mac_lookup=local (offline OUI DB is
# primary), ip_blacklist=local (DNSBL is close to the tool's own job),
# asn_lookup=api. uptime_check=local (current build is a one-shot check, not the
# scheduled-history version)  flip in admin if the scheduled version lands.
NETWORK_TOOLS = [
    ("DNS Lookup", "net_tools.html#lookupToolSection", "dns", "local"),
    ("DNS Propagation Checker", "networking/dns_propagation.html", "dns_propagation", "local"),
    ("Reverse DNS (PTR)", "networking/reverse_dns.html", "reverse_dns", "local"),
    ("Nameserver Lookup", "networking/nameserver_lookup.html", "nameserver_lookup", "local"),
    ("DNSSEC Checker", "networking/dnssec_checker.html", "dnssec_check", "local"),
    ("DNS Record Generator", "networking/dns_record_generator.html", "", "local"),
    ("MX Lookup", "networking/mx_lookup.html", "mx_lookup", "local"),
    ("SPF Checker", "networking/spf_checker.html", "spf_check", "local"),
    ("DKIM Checker", "networking/dkim_checker.html", "dkim_check", "local"),
    ("DMARC Checker", "networking/dmarc_checker.html", "dmarc_check", "local"),
    ("SSL Certificate Checker", "networking/ssl_cert_checker.html", "ssl_info", "local"),
    ("HTTP Headers Viewer", "net_tools.html#lookupToolSection", "headers", "local"),
    ("Security Headers Checker", "networking/securityheader.html", "security_headers", "local"),
    ("Redirect Checker", "networking/redirect_checker.html", "redirect_check", "local"),
    ("HTTP Status Checker", "networking/http_status_checker.html", "http_status", "local"),
    ("SSL Expiration Checker", "networking/sslchecker.html", "ssl_expiration", "local"),
    ("TLS Version Checker", "networking/tls.html", "tls_check", "local"),
    ("Website Uptime Checker", "networking/uptime_checker.html", "uptime_check", "local"),
    ("Open Graph Checker", "networking/open_graph_checker.html", "og_check", "local"),
    ("Robots.txt Tester", "networking/robots_checker.html", "robots_check", "local"),
    ("Sitemap Validator", "networking/sitemap_validator.html", "sitemap_validate", "local"),
    ("IP Information", "net_tools.html#lookupToolSection", "ip_info", "api"),
    ("WHOIS Lookup", "net_tools.html#lookupToolSection", "whois", "local"),
    ("Ping Tool", "networking/ping_tool.html", "ping", "local"),
    ("Traceroute", "networking/traceroute.html", "traceroute", "local"),
    ("Port Scanner", "networking/port_scanner.html", "port_scan", "local"),
    ("IP Geolocation", "networking/ip_geolocation.html", "ip_geo", "api"),
    ("ASN Lookup", "networking/asn.htm", "asn_lookup", "api"),
    ("Reverse IP Lookup", "networking/reverse_ip.htm", "reverse_ip", "api"),
    ("IP Blacklist Checker", "networking/ip_blacklist.htm", "ip_blacklist", "local"),
    ("Scam Detector", "networking/scam_detector.html", "scam_detector", "local"),
    ("MAC Address Lookup", "networking/mac_lookup.html", "mac_lookup", "local"),
    ("CORS Checker", "networking/core_checker.html", "cors_check", "local"),
    ("Website Screenshot Tool", "networking/web_screenshot.html", "web_screenshot", "api"),
    ("Subnet Calculator", "networking/subnet_calculator.html", "", "local"),
    ("CIDR Calculator", "networking/cidr_calculator.html", "", "local"),
    ("Security Grade", "networking/security_grade.html", "security_grade", "local"),
    ("AI-Crawler Checker", "networking/ai_crawler_checker.html", "ai_crawler_check", "local"),
    ("IPv6 Readiness", "networking/ipv6_readiness.html", "ipv6_readiness", "local"),
    ("Email Deliverability Wizard", "networking/email_deliverability_wizard.html", "", "local"),
]

# Tools registered ahead of being functional  deliberately not in the
# (name, path, tool_key, tier) groups above since those always seed as
# status="operational". Each entry here carries its own explicit status so
# the catalog/admin can show it as "coming soon" without a fake result.
# Per this project's honesty convention: never fake a result while blocked
# on something external (here, a paid HIBP API key not yet purchased).
STUB_TOOLS = [
    {
        "name": "Email/Domain Breach Check",
        "category": "network-tools",
        "path": "networking/breach_email_check.html",
        "tool_key": "breach_email_check",
        "tier": "api",
        "status": "degraded",
        "notes": "Needs a paid Have I Been Pwned API key in .env before the dispatcher branch can be built. Do not fake results  see PHASE1_BREAKOUT_FEATURES_IMPLEMENTATION.md §4b.",
    },
]


class Command(BaseCommand):
    help = "Seed the tools registry with every real tool currently on the site (idempotent)."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        # Normalize every group into (name, path, tool_key, tier).
        groups = [
            ("dev-tools", [(n, p, "", "local") for n, p in DEV_TOOLS]),
            ("ai-tools", [(n, p, "", "api") for n, p in AI_TOOLS]),
            ("network-tools", NETWORK_TOOLS),
        ]

        for category, tools in groups:
            for name, path, tool_key, tier in tools:
                tool, created = Tool.objects.get_or_create(
                    name=name,
                    category=category,
                    defaults={"path": path, "tool_key": tool_key, "tier": tier},
                )
                if created:
                    created_count += 1
                    continue
                # Keep existing rows in sync with the seed (path/tool_key/tier),
                # but never clobber an admin's manual tier override... except the
                # seed is the source of truth on first rollout, so set it here.
                changed = []
                if tool.path != path:
                    tool.path = path
                    changed.append("path")
                if tool.tool_key != tool_key:
                    tool.tool_key = tool_key
                    changed.append("tool_key")
                if tool.tier != tier:
                    tool.tier = tier
                    changed.append("tier")
                if changed:
                    tool.save(update_fields=changed + ["updated_at"])
                    updated_count += 1

        for stub in STUB_TOOLS:
            tool, created = Tool.objects.get_or_create(
                name=stub["name"],
                category=stub["category"],
                defaults={
                    "path": stub["path"],
                    "tool_key": stub["tool_key"],
                    "tier": stub["tier"],
                    "status": stub["status"],
                    "notes": stub["notes"],
                },
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Seeded tools registry: {created_count} created, {updated_count} updated."))
