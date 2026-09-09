"""Provider interface for hardware/gaming content ingestion.

Per the spec's own instruction  "do not hardcode any specific provider" 
this file defines the shape every future source integrates against
(official manufacturer announcements, driver release notes, benchmark
databases, Steam news, Unreal Engine announcements, Linux hardware news,
etc.) without committing to any of them. No concrete provider is wired in:
none of those sources have been evaluated for reliability/ToS/API-key
requirements yet, and this project's established practice (see
network_tools' STUB_TOOLS pattern, news' honest "Coming Soon" stubs) is to
never fake an external integration that isn't actually connected.

To add a real source later: subclass HardwareSourceProvider, implement
fetch(), and add an instance to hardware.providers.registry.PROVIDERS. That
one list is the only thing hardware/tasks.py::aggregate_hardware_content
reads  nothing else needs to change.
"""
from abc import ABC, abstractmethod


class HardwareSourceProvider(ABC):
    """One ingestion source. `fetch()` returns a list of plain dicts shaped
    like news/services.py's candidate items, so a future aggregation task
    can reuse the same dedup/scoring/AI-drafting pipeline shape:
    {
        "title": str,
        "url": str,               # used for de-duplication against
                                   # HardwareArticleSource.url
        "source_name": str,
        "category": str,          # one of hardware.models.CATEGORY_CHOICES
        "excerpt": str,
        "subject_hint": dict | None,  # e.g. {"type": "cpu", "name": "..."}
                                       # for a future auto-linking pass to
                                       # hardware.models.CPU/GPU/Laptop/MobileSoC
    }
    """

    #: Human-readable name shown in admin/logs, e.g. "Steam News".
    name = "Unnamed Provider"

    @abstractmethod
    def fetch(self):
        """Return a list of candidate item dicts (see class docstring).
        Must not raise for a single bad entry  skip it and keep going;
        the caller (aggregate_hardware_content) also isolates a whole
        provider failing so one dead feed can't block the others."""
        raise NotImplementedError
