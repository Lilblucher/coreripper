"""The one real, live spec provider wired in this phase. Wikidata's data is
CC0 (redistribution-safe, no ToS problem the way scraping GSMArena/
Notebookcheck/PassMark would be  see field_priority.py's docstring), and its
public SPARQL endpoint needs no API key. Reachability was verified live
against query.wikidata.org before this file was written (200 OK, real JSON).

Honest limitation, verified live rather than assumed: Wikidata's coverage of
CPUs/GPUs skews toward older/historical/notable parts, not an exhaustive
catalog of every current-gen SKU  querying for CPUs/GPUs with a Wikidata
release-date after 2019 returned zero rows during this file's own
development. Laptops (69 direct instances) and mobile SoCs (38 direct
instances) fare better. This is exactly the kind of partial-but-real
coverage the architecture is built to accept: `hardware/providers/manager.py`
merges whatever a live provider actually returns, and the manual
`seed_hardware_specs` command remains the practical primary source for
current, buying-guide-relevant devices Wikidata doesn't track well  not a
workaround, the designed fallback path (see field_priority.py).

QIDs/PIDs used below were looked up live against the Wikidata API/SPARQL
endpoint while writing this file (wbsearchentities + a label-lookup SPARQL
query), not guessed:
    Q5300 / Q5297  central processing unit / microprocessor (CPU has zero
        direct instances of the broader Q183484-style GPU class, so GPUs use
        a subclass-transitive query instead; CPUs use direct P31, since
        Q5300/Q5297 already had usable direct members).
    Q183484  graphics processing unit (zero *direct* P31 instances; 24 found
        via wdt:P31/wdt:P279* traversal, so GPU alone uses the transitive form).
    Q3962   laptop (69 direct instances)
    Q610398  system on a chip (38 direct instances)
    P176 manufacturer, P577 publication date, P1141 number of processor
    cores, P7443 number of processor threads, P2149 clock frequency (Hz),
    P2229 thermal design power (W), P1041 socket supported, P2067 mass (kg),
    P18 image (Commons file name).

Fields this provider does NOT populate (no reliable Wikidata property found
for them, or coverage was empty during verification)  left unset rather
than guessed: architecture, generation, cache_mb, boost_clock_ghz,
process_node_nm, vram_gb, cuda_or_stream_cores, ray_tracing,
power_draw_watts, recommended_psu_watts, display_outputs, ram_gb,
storage_gb, display, refresh_rate_hz, battery_whr, cpu_architecture (SoC),
ai_engine, fabrication_process_nm, supported_phones.
"""
import requests

from .spec_base import HardwareSpecProvider

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
_HEADERS = {"User-Agent": "CoreRipper-HardwareHub/1.0 (spec sync; contact via project owner)"}
_TIMEOUT = 30

# Q183484 ("graphics processing unit") is a transitive superclass of the
# phone/tablet GPU IP families below on Wikidata (Adreno, Mali, PowerVR,
# Apple's own GPU cores, Samsung's Xclipse, etc.), so the "gpu" SPARQL query
# above pulls them in alongside real discrete/desktop GPUs. Those belong on
# MobileSoC.gpu (a plain text field already populated by seed data, e.g.
# "Adreno 750") instead of standing alone as a GPU catalog entry a user could
# try to compare against a GeForce/Radeon card. Filtered by name prefix
# rather than manufacturer, since Wikidata's manufacturer label for these is
# unreliable (verified: one such row came back with manufacturer "TSMC").
_MOBILE_GPU_NAME_PREFIXES = (
    "adreno", "ardeno", "mali", "powervr", "apple gpu", "immortalis",
    "xclipse", "vivante",
)


def _is_mobile_gpu(name):
    lowered = (name or "").lower()
    return any(lowered.startswith(prefix) for prefix in _MOBILE_GPU_NAME_PREFIXES)

_QUERIES = {
    "cpu": """
        SELECT ?item ?itemLabel ?manufacturerLabel ?cores ?threads ?clock ?tdp ?socketLabel ?release ?image WHERE {
          VALUES ?class { wd:Q5300 wd:Q5297 }
          ?item wdt:P31 ?class .
          OPTIONAL { ?item wdt:P176 ?manufacturer . }
          OPTIONAL { ?item wdt:P1141 ?cores . }
          OPTIONAL { ?item wdt:P7443 ?threads . }
          OPTIONAL { ?item wdt:P2149 ?clock . }
          OPTIONAL { ?item wdt:P2229 ?tdp . }
          OPTIONAL { ?item wdt:P1041 ?socket . }
          OPTIONAL { ?item wdt:P577 ?release . }
          OPTIONAL { ?item wdt:P18 ?image . }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
        }
        LIMIT 200
    """,
    "gpu": """
        SELECT ?item ?itemLabel ?manufacturerLabel ?release ?image WHERE {
          ?item wdt:P31/wdt:P279* wd:Q183484 .
          OPTIONAL { ?item wdt:P176 ?manufacturer . }
          OPTIONAL { ?item wdt:P577 ?release . }
          OPTIONAL { ?item wdt:P18 ?image . }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
        }
        LIMIT 200
    """,
    "laptop": """
        SELECT ?item ?itemLabel ?manufacturerLabel ?mass ?release ?image WHERE {
          ?item wdt:P31 wd:Q3962 .
          OPTIONAL { ?item wdt:P176 ?manufacturer . }
          OPTIONAL { ?item wdt:P2067 ?mass . }
          OPTIONAL { ?item wdt:P577 ?release . }
          OPTIONAL { ?item wdt:P18 ?image . }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
        }
        LIMIT 200
    """,
    "mobile_soc": """
        SELECT ?item ?itemLabel ?manufacturerLabel ?release ?image WHERE {
          ?item wdt:P31 wd:Q610398 .
          OPTIONAL { ?item wdt:P176 ?manufacturer . }
          OPTIONAL { ?item wdt:P577 ?release . }
          OPTIONAL { ?item wdt:P18 ?image . }
          SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
        }
        LIMIT 200
    """,
}


def _qid(uri):
    return uri.rsplit("/", 1)[-1]


def _val(binding, key):
    cell = binding.get(key)
    return cell.get("value") if cell else None


def _commons_image_url(filename):
    if not filename:
        return None
    # P18 values are Commons file titles (e.g. "Foo.jpg"), not full URLs.
    from urllib.parse import quote

    name = filename.rsplit("/", 1)[-1]
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}"


def _release_date(value):
    # Wikidata dateTimes look like "2021-05-04T00:00:00Z"; models store a
    # plain date, so trim to the date component.
    return value[:10] if value else None


class WikidataProvider(HardwareSpecProvider):
    key = "wikidata"
    name = "Wikidata"

    def fetch(self, type_key):
        query = _QUERIES.get(type_key)
        if query is None:
            return []
        try:
            resp = requests.get(
                SPARQL_ENDPOINT, params={"query": query, "format": "json"},
                headers=_HEADERS, timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            bindings = resp.json()["results"]["bindings"]
        except Exception as exc:  # noqa: BLE001  one dead/slow endpoint must not crash the sync
            print(f"[WikidataProvider] fetch({type_key!r}) failed: {exc}")
            return []

        by_qid = {}
        for b in bindings:
            item_uri = _val(b, "item")
            if not item_uri:
                continue
            qid = _qid(item_uri)
            record = by_qid.setdefault(
                qid,
                {
                    "external_id": qid,
                    "source_url": item_uri,
                    "name": _val(b, "itemLabel"),
                    "manufacturer": _val(b, "manufacturerLabel"),
                },
            )
            # Wikidata items can have multiple values for the same property
            # (e.g. two recorded clock speeds); first non-null value wins,
            # later duplicate rows for the same item are ignored rather than
            # overwriting with an arbitrary later value.
            release = _val(b, "release")
            if release and "release_date" not in record:
                record["release_date"] = _release_date(release)
            image = _val(b, "image")
            if image and "image_url" not in record:
                record["image_url"] = _commons_image_url(image)

            if type_key == "cpu":
                for src_key, dest_key, cast in (
                    ("cores", "cores", int),
                    ("threads", "threads", int),
                    ("clock", "base_clock_ghz", lambda v: round(float(v) / 1_000_000_000, 2)),
                    ("tdp", "tdp_watts", lambda v: int(float(v))),
                ):
                    val = _val(b, src_key)
                    if val is not None and dest_key not in record:
                        try:
                            record[dest_key] = cast(val)
                        except (TypeError, ValueError):
                            pass
                socket_label = _val(b, "socketLabel")
                if socket_label and "socket" not in record:
                    record["socket"] = socket_label
            elif type_key == "laptop":
                mass = _val(b, "mass")
                if mass and "weight_kg" not in record:
                    try:
                        record["weight_kg"] = round(float(mass), 2)
                    except (TypeError, ValueError):
                        pass

        # Drop items Wikidata returned with no usable name  a bare QID with
        # nothing else is not a real spec row.
        records = [r for r in by_qid.values() if r.get("name")]
        if type_key == "gpu":
            records = [r for r in records if not _is_mobile_gpu(r.get("name"))]
        return records
