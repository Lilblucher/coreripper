"""Declarative priority table  the actual "provider manager" logic. For
each (type_key, field), an ordered list of provider keys says which source
to prefer when more than one supplies a value for the same device. Only
`wikidata` (and the implicit `manual` curation path, which always yields to
a live provider once one exists for that field  see manager.py) are wired
in today.

GSMArena, Notebookcheck, and PassMark are declared here (documented, not
hardcoded elsewhere) but map to an empty provider list, exactly like
VideoCardz/IGN in hardware/providers/sources.py:
- GSMArena: no public API for structured specs (only its RSS feed, already
  used by hardware/providers/rss_provider.py for article ingestion  a feed
  of headlines is not the same thing as structured display/battery/camera
  spec data, and GSMArena's spec pages have no API/export).
- Notebookcheck: no public API or licensed data export found.
- PassMark: no public API; its downloadable CSVs are for personal/non-
  commercial use per PassMark's own terms, not redistribution on a public
  site.
None of these are scraped. If a real, compliant access path to any of them
appears later (a licensing deal, an official API), add its provider key to
LIVE_PROVIDERS and slot it into the relevant priority lists below  no
model or manager.py change needed.

Priority lists reflect the spec's own reasoning (GSMArena's own display/
camera data would be considered authoritative for phones, Notebookcheck's
battery/keyboard testing for laptops, PassMark for CPU/GPU benchmark
figures)  written now so adding a provider later is genuinely a config
change, not a rewrite, even though only `wikidata` can act on any of it yet.
"""
from .wikidata_provider import WikidataProvider

# Only entries with at least one live provider actually influence a sync;
# the rest are read by `deferred_provider_keys()` purely for documentation/
# admin-visibility purposes (e.g. showing "not yet available" in the admin).
FIELD_PRIORITY = {
    "cpu": {
        "manufacturer": ["wikidata"],
        "cores": ["wikidata"],
        "threads": ["wikidata"],
        "base_clock_ghz": ["wikidata"],
        "tdp_watts": ["wikidata"],
        "socket": ["wikidata"],
        "release_date": ["wikidata"],
        "architecture": ["wikidata"],
        "generation": ["wikidata"],
        "cache_mb": ["wikidata"],
        "boost_clock_ghz": ["wikidata"],
        "process_node_nm": ["wikidata"],
        "benchmarks": ["passmark", "wikidata"],
        "image": ["wikidata"],
    },
    "gpu": {
        "manufacturer": ["wikidata"],
        "release_date": ["wikidata"],
        "vram_gb": ["wikidata"],
        "cuda_or_stream_cores": ["wikidata"],
        "ray_tracing": ["wikidata"],
        "power_draw_watts": ["wikidata"],
        "recommended_psu_watts": ["wikidata"],
        "display_outputs": ["wikidata"],
        "benchmarks": ["passmark", "wikidata"],
        "image": ["wikidata"],
    },
    "laptop": {
        "manufacturer": ["wikidata"],
        "release_date": ["wikidata"],
        "weight_kg": ["wikidata"],
        "display": ["gsmarena", "wikidata"],
        "battery_whr": ["notebookcheck", "wikidata"],
        "ram_gb": ["wikidata"],
        "storage_gb": ["wikidata"],
        "refresh_rate_hz": ["wikidata"],
        "image": ["wikidata"],
    },
    "mobile_soc": {
        "manufacturer": ["wikidata"],
        "release_date": ["wikidata"],
        "cpu_architecture": ["wikidata"],
        "gpu": ["gsmarena", "wikidata"],
        "ai_engine": ["wikidata"],
        "fabrication_process_nm": ["wikidata"],
        "image": ["wikidata"],
    },
}

# The only providers actually instantiated/callable today. Keyed by
# provider_key so manager.py can look one up by name from FIELD_PRIORITY's
# ordered lists.
LIVE_PROVIDERS = {
    "wikidata": WikidataProvider(),
}


def priority_for(type_key, field_name):
    """Ordered provider-key list for a field, filtered to providers that are
    actually live today  a documented-but-unwired key (e.g. "gsmarena")
    is silently skipped, never treated as an error."""
    configured = FIELD_PRIORITY.get(type_key, {}).get(field_name, [])
    return [key for key in configured if key in LIVE_PROVIDERS]
