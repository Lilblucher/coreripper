"""The single list hardware/tasks.py reads. Populated with 5 real RSS
publications (hardware/providers/sources.py)  Tom's Hardware, TechPowerUp,
VideoCardz, GSMArena, PC Gamer. Add another real source the same way:

    from hardware.providers.registry import PROVIDERS
    from my_module import SteamNewsProvider
    PROVIDERS.append(SteamNewsProvider())
"""
from .sources import ALL_SOURCES

PROVIDERS = list(ALL_SOURCES)


def get_registered_providers():
    return list(PROVIDERS)
