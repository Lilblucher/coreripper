"""Which spec fields are tracked per hardware type, and their display
labels  used by hardware.ai_knowledge to know which fields to hash for
HardwareAIProfile.source_spec_hash invalidation. Deliberately a curated list
(not raw model._meta introspection), so internal bookkeeping fields (id,
created_at, updated_at) and reverse relations (laptops, articles) never leak
in by accident.
"""
from .models import CPU, GPU, Laptop, MobileSoC

TRACKED_SPEC_FIELDS = {
    "cpu": (
        CPU,
        [
            ("manufacturer", "Manufacturer"),
            ("generation", "Generation"),
            ("architecture", "Architecture"),
            ("socket", "Socket"),
            ("cores", "Cores"),
            ("threads", "Threads"),
            ("cache_mb", "Cache (MB)"),
            ("base_clock_ghz", "Base Clock (GHz)"),
            ("boost_clock_ghz", "Boost Clock (GHz)"),
            ("tdp_watts", "TDP (W)"),
            ("process_node_nm", "Process Node (nm)"),
            ("release_date", "Release Date"),
        ],
    ),
    "gpu": (
        GPU,
        [
            ("manufacturer", "Manufacturer"),
            ("vram_gb", "VRAM (GB)"),
            ("cuda_or_stream_cores", "CUDA / Stream Cores"),
            ("ray_tracing", "Ray Tracing"),
            ("power_draw_watts", "Power Draw (W)"),
            ("recommended_psu_watts", "Recommended PSU (W)"),
            ("display_outputs", "Display Outputs"),
            ("release_date", "Release Date"),
        ],
    ),
    "laptop": (
        Laptop,
        [
            ("manufacturer", "Manufacturer"),
            ("cpu", "CPU"),
            ("gpu", "GPU"),
            ("ram_gb", "RAM (GB)"),
            ("storage_gb", "Storage (GB)"),
            ("display", "Display"),
            ("refresh_rate_hz", "Refresh Rate (Hz)"),
            ("battery_whr", "Battery (Wh)"),
            ("weight_kg", "Weight (kg)"),
            ("release_date", "Release Date"),
        ],
    ),
    "mobile_soc": (
        MobileSoC,
        [
            ("manufacturer", "Manufacturer"),
            ("cpu_architecture", "CPU Architecture"),
            ("gpu", "GPU"),
            ("ai_engine", "AI Engine"),
            ("fabrication_process_nm", "Fabrication Process (nm)"),
            ("release_date", "Release Date"),
        ],
    ),
}
