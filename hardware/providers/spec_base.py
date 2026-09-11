"""Provider interface for hardware SPEC data (CPU/GPU/Laptop/MobileSoC rows),
parallel to (not replacing) spec_base.py's sibling base.py, which covers
article/news ingestion. Same "don't hardcode a single source" philosophy as
base.py's own docstring, but for structured spec fields rather than articles.

To add a real spec source later: subclass HardwareSpecProvider, implement
fetch(type_key), and add it to hardware.providers.field_priority's live
provider registry. See field_priority.py's own docstring for why most
candidate sources (GSMArena/Notebookcheck/PassMark) are declared but not
wired in today  no public API, and scraping their HTML would violate ToS,
the same reasoning that already keeps VideoCardz/IGN out of sources.py.
"""
from abc import ABC, abstractmethod


class HardwareSpecProvider(ABC):
    """One structured spec source. `fetch(type_key)` returns a list of plain
    dicts, one per device this provider knows about for that type_key:
    {
        "external_id": str,        # this provider's own stable id (e.g. a
                                    # Wikidata QID)  used by manager.py to
                                    # match the same device across providers
                                    # and across repeated syncs.
        "name": str,
        "manufacturer": str,
        "source_url": str,         # provenance link, stored per-field in
                                    # HardwareFieldSource.
        # ...plus whichever of the target model's own fields this provider
        # can supply (a provider need not supply every field  manager.py
        # merges partial records from multiple providers per field.py's
        # priority table).
    }

    Must not raise for a single bad/unparseable entry  skip it and keep
    going; the caller (manager.py::sync_type) also isolates a whole provider
    failing so one dead source can't block the others.
    """

    #: Machine key used in field_priority.py's priority lists and stored as
    #: HardwareFieldSource.provider_key, e.g. "wikidata".
    key = "unnamed"

    #: Human-readable name shown in admin/logs, e.g. "Wikidata".
    name = "Unnamed Provider"

    @abstractmethod
    def fetch(self, type_key):
        """Return a list of candidate device dicts (see class docstring) for
        one of "cpu"/"gpu"/"laptop"/"mobile_soc". Return [] for a type_key
        this provider doesn't cover."""
        raise NotImplementedError
