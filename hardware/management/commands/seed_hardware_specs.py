"""Manual fallback data path for hardware/providers/manager.py's primary,
Wikidata-backed sync. Starter dataset of publicly known specs (manufacturer
spec sheets), entered by hand  NOT scraped from GSMArena/Notebookcheck/
PassMark. Every row here has external_id=None, marking it as hand-curated
rather than provider-synced (see hardware/models.py's own field comments);
a later sync_hardware_specs run matches by name+manufacturer instead of
duplicating a row Wikidata also happens to know about.

Idempotent like blog.seed_blog: get_or_create keyed on name, so re-running
never duplicates. AI-knowledge generation is a separate, gated step (only
runs when a device has no HardwareAIProfile yet, or its tracked specs
changed since the last generation)  re-running this command never re-spends
an AI call on a device that's already been profiled.

Scores (performance/value/portability/efficiency) hardcoded below are
CoreRipper's own curation, not sourced from any benchmark site  see the
module docstring in hardware/models.py for why these are curated-only
fields a provider sync must never overwrite.
"""
from django.core.management.base import BaseCommand

from hardware import ai_knowledge
from hardware.models import CPU, GPU, Laptop, MobileSoC

CPUS = [
    {"name": "Ryzen 9 9950X", "manufacturer": "AMD", "generation": "Zen 5", "architecture": "Zen 5",
     "socket": "AM5", "cores": 16, "threads": 32, "cache_mb": 80, "base_clock_ghz": 4.3,
     "boost_clock_ghz": 5.7, "tdp_watts": 170, "process_node_nm": 4, "release_date": "2024-08-15",
     "performance_score": 96, "value_score": 62, "efficiency_score": 70},
    {"name": "Ryzen 7 9800X3D", "manufacturer": "AMD", "generation": "Zen 5", "architecture": "Zen 5",
     "socket": "AM5", "cores": 8, "threads": 16, "cache_mb": 96, "base_clock_ghz": 4.7,
     "boost_clock_ghz": 5.2, "tdp_watts": 120, "process_node_nm": 4, "release_date": "2024-11-07",
     "performance_score": 90, "value_score": 78, "efficiency_score": 75},
    {"name": "Core i9-14900K", "manufacturer": "Intel", "generation": "14th Gen (Raptor Lake Refresh)",
     "architecture": "Raptor Lake", "socket": "LGA1700", "cores": 24, "threads": 32, "cache_mb": 36,
     "base_clock_ghz": 3.2, "boost_clock_ghz": 6.0, "tdp_watts": 253, "process_node_nm": 10,
     "release_date": "2023-10-17", "performance_score": 94, "value_score": 55, "efficiency_score": 48},
    {"name": "Core i5-14600K", "manufacturer": "Intel", "generation": "14th Gen (Raptor Lake Refresh)",
     "architecture": "Raptor Lake", "socket": "LGA1700", "cores": 14, "threads": 20, "cache_mb": 24,
     "base_clock_ghz": 3.5, "boost_clock_ghz": 5.3, "tdp_watts": 181, "process_node_nm": 10,
     "release_date": "2023-10-17", "performance_score": 82, "value_score": 76, "efficiency_score": 55},
    {"name": "Ryzen 5 7600", "manufacturer": "AMD", "generation": "Zen 4", "architecture": "Zen 4",
     "socket": "AM5", "cores": 6, "threads": 12, "cache_mb": 32, "base_clock_ghz": 3.8,
     "boost_clock_ghz": 5.1, "tdp_watts": 65, "process_node_nm": 5, "release_date": "2023-01-10",
     "performance_score": 68, "value_score": 85, "efficiency_score": 78},
    {"name": "Core Ultra 9 285K", "manufacturer": "Intel", "generation": "Core Ultra 200S (Arrow Lake)",
     "architecture": "Arrow Lake", "socket": "LGA1851", "cores": 24, "threads": 24, "cache_mb": 36,
     "base_clock_ghz": 3.7, "boost_clock_ghz": 5.7, "tdp_watts": 125, "process_node_nm": 3,
     "release_date": "2024-10-24", "performance_score": 91, "value_score": 58, "efficiency_score": 74},
    {"name": "Ryzen 9 7950X3D", "manufacturer": "AMD", "generation": "Zen 4", "architecture": "Zen 4",
     "socket": "AM5", "cores": 16, "threads": 32, "cache_mb": 144, "base_clock_ghz": 4.2,
     "boost_clock_ghz": 5.7, "tdp_watts": 120, "process_node_nm": 5, "release_date": "2023-02-28",
     "performance_score": 93, "value_score": 60, "efficiency_score": 72},
    {"name": "Core i7-14700K", "manufacturer": "Intel", "generation": "14th Gen (Raptor Lake Refresh)",
     "architecture": "Raptor Lake", "socket": "LGA1700", "cores": 20, "threads": 28, "cache_mb": 33,
     "base_clock_ghz": 3.4, "boost_clock_ghz": 5.6, "tdp_watts": 253, "process_node_nm": 10,
     "release_date": "2023-10-17", "performance_score": 88, "value_score": 68, "efficiency_score": 51},
    {"name": "Ryzen 5 9600X", "manufacturer": "AMD", "generation": "Zen 5", "architecture": "Zen 5",
     "socket": "AM5", "cores": 6, "threads": 12, "cache_mb": 32, "base_clock_ghz": 3.9,
     "boost_clock_ghz": 5.4, "tdp_watts": 65, "process_node_nm": 4, "release_date": "2024-08-15",
     "performance_score": 72, "value_score": 74, "efficiency_score": 80},
    {"name": "Core i3-14100", "manufacturer": "Intel", "generation": "14th Gen (Raptor Lake Refresh)",
     "architecture": "Raptor Lake", "socket": "LGA1700", "cores": 4, "threads": 8, "cache_mb": 12,
     "base_clock_ghz": 3.5, "boost_clock_ghz": 4.7, "tdp_watts": 60, "process_node_nm": 10,
     "release_date": "2023-10-17", "performance_score": 48, "value_score": 80, "efficiency_score": 65},
]

GPUS = [
    {"name": "GeForce RTX 4090", "manufacturer": "NVIDIA", "vram_gb": 24, "cuda_or_stream_cores": 16384,
     "ray_tracing": True, "power_draw_watts": 450, "recommended_psu_watts": 850,
     "display_outputs": "3x DisplayPort 1.4a, 1x HDMI 2.1", "release_date": "2022-10-12",
     "performance_score": 99, "value_score": 45},
    {"name": "GeForce RTX 4080 Super", "manufacturer": "NVIDIA", "vram_gb": 16, "cuda_or_stream_cores": 10240,
     "ray_tracing": True, "power_draw_watts": 320, "recommended_psu_watts": 750,
     "display_outputs": "3x DisplayPort 1.4a, 1x HDMI 2.1", "release_date": "2024-01-31",
     "performance_score": 90, "value_score": 55},
    {"name": "GeForce RTX 4070 Super", "manufacturer": "NVIDIA", "vram_gb": 12, "cuda_or_stream_cores": 7168,
     "ray_tracing": True, "power_draw_watts": 220, "recommended_psu_watts": 650,
     "display_outputs": "3x DisplayPort 1.4a, 1x HDMI 2.1", "release_date": "2024-01-17",
     "performance_score": 80, "value_score": 74},
    {"name": "GeForce RTX 4060", "manufacturer": "NVIDIA", "vram_gb": 8, "cuda_or_stream_cores": 3072,
     "ray_tracing": True, "power_draw_watts": 115, "recommended_psu_watts": 550,
     "display_outputs": "3x DisplayPort 1.4a, 1x HDMI 2.1", "release_date": "2023-06-29",
     "performance_score": 60, "value_score": 78},
    {"name": "Radeon RX 7900 XTX", "manufacturer": "AMD", "vram_gb": 24, "cuda_or_stream_cores": 6144,
     "ray_tracing": True, "power_draw_watts": 355, "recommended_psu_watts": 800,
     "display_outputs": "2x DisplayPort 2.1, 1x HDMI 2.1, 1x USB-C", "release_date": "2022-12-13",
     "performance_score": 92, "value_score": 60},
    {"name": "Radeon RX 7800 XT", "manufacturer": "AMD", "vram_gb": 16, "cuda_or_stream_cores": 3840,
     "ray_tracing": True, "power_draw_watts": 263, "recommended_psu_watts": 700,
     "display_outputs": "2x DisplayPort 2.1, 1x HDMI 2.1, 1x USB-C", "release_date": "2023-09-06",
     "performance_score": 78, "value_score": 76},
    {"name": "Radeon RX 7600", "manufacturer": "AMD", "vram_gb": 8, "cuda_or_stream_cores": 2048,
     "ray_tracing": True, "power_draw_watts": 165, "recommended_psu_watts": 550,
     "display_outputs": "2x DisplayPort 2.1, 1x HDMI 2.1", "release_date": "2023-05-25",
     "performance_score": 55, "value_score": 72},
    {"name": "GeForce RTX 4060 Ti", "manufacturer": "NVIDIA", "vram_gb": 8, "cuda_or_stream_cores": 4352,
     "ray_tracing": True, "power_draw_watts": 160, "recommended_psu_watts": 550,
     "display_outputs": "3x DisplayPort 1.4a, 1x HDMI 2.1", "release_date": "2023-05-24",
     "performance_score": 67, "value_score": 65},
    {"name": "Arc B580", "manufacturer": "Intel", "vram_gb": 12, "cuda_or_stream_cores": 2560,
     "ray_tracing": True, "power_draw_watts": 190, "recommended_psu_watts": 600,
     "display_outputs": "3x DisplayPort 2.1, 1x HDMI 2.1", "release_date": "2024-12-13",
     "performance_score": 62, "value_score": 82},
    {"name": "GeForce RTX 4070 Ti Super", "manufacturer": "NVIDIA", "vram_gb": 16, "cuda_or_stream_cores": 8448,
     "ray_tracing": True, "power_draw_watts": 285, "recommended_psu_watts": 700,
     "display_outputs": "3x DisplayPort 1.4a, 1x HDMI 2.1", "release_date": "2024-01-24",
     "performance_score": 86, "value_score": 62},
]

MOBILE_SOCS = [
    {"name": "Snapdragon 8 Gen 3", "manufacturer": "Qualcomm", "cpu_architecture": "1x Cortex-X4 + 5x Cortex-A720 + 2x Cortex-A520",
     "gpu": "Adreno 750", "ai_engine": "Hexagon NPU", "fabrication_process_nm": 4, "release_date": "2023-10-24",
     "performance_score": 95, "efficiency_score": 78},
    {"name": "Apple A18 Pro", "manufacturer": "Apple", "cpu_architecture": "2x performance + 4x efficiency (6-core)",
     "gpu": "Apple GPU (6-core)", "ai_engine": "16-core Neural Engine", "fabrication_process_nm": 3,
     "release_date": "2024-09-20", "performance_score": 97, "efficiency_score": 88},
    {"name": "Dimensity 9300+", "manufacturer": "MediaTek", "cpu_architecture": "4x Cortex-X4 + 4x Cortex-A720",
     "gpu": "Immortalis-G720 MC12", "ai_engine": "MediaTek APU 790", "fabrication_process_nm": 4,
     "release_date": "2024-05-22", "performance_score": 92, "efficiency_score": 75},
    {"name": "Snapdragon 8s Gen 3", "manufacturer": "Qualcomm", "cpu_architecture": "1x Cortex-X4 + 4x Cortex-A720 + 3x Cortex-A520",
     "gpu": "Adreno 735", "ai_engine": "Hexagon NPU", "fabrication_process_nm": 4, "release_date": "2024-03-18",
     "performance_score": 84, "efficiency_score": 72},
    {"name": "Exynos 2400", "manufacturer": "Samsung", "cpu_architecture": "1x Cortex-X4 + 2x Cortex-A720 + 3x Cortex-A720 + 4x Cortex-A520",
     "gpu": "Xclipse 940", "ai_engine": "Samsung NPU", "fabrication_process_nm": 4, "release_date": "2024-01-17",
     "performance_score": 88, "efficiency_score": 70},
    {"name": "Tensor G4", "manufacturer": "Google", "cpu_architecture": "1x Cortex-X4 + 3x Cortex-A720 + 4x Cortex-A520",
     "gpu": "Mali-G715 Immortalis", "ai_engine": "Google Tensor TPU", "fabrication_process_nm": 4,
     "release_date": "2024-08-13", "performance_score": 80, "efficiency_score": 68},
    {"name": "Dimensity 8300", "manufacturer": "MediaTek", "cpu_architecture": "4x Cortex-A720 + 4x Cortex-A520",
     "gpu": "Mali-G615 MC6", "ai_engine": "MediaTek APU 780", "fabrication_process_nm": 4,
     "release_date": "2023-11-06", "performance_score": 76, "efficiency_score": 74},
    {"name": "Snapdragon 7+ Gen 3", "manufacturer": "Qualcomm", "cpu_architecture": "1x Cortex-X4 + 4x Cortex-A720 + 3x Cortex-A520",
     "gpu": "Adreno 720", "ai_engine": "Hexagon NPU", "fabrication_process_nm": 4, "release_date": "2024-04-23",
     "performance_score": 74, "efficiency_score": 73},
    {"name": "Apple A17 Pro", "manufacturer": "Apple", "cpu_architecture": "2x performance + 4x efficiency (6-core)",
     "gpu": "Apple GPU (6-core)", "ai_engine": "16-core Neural Engine", "fabrication_process_nm": 3,
     "release_date": "2023-09-22", "performance_score": 91, "efficiency_score": 82},
    {"name": "Snapdragon 8 Gen 2", "manufacturer": "Qualcomm", "cpu_architecture": "1x Cortex-X3 + 4x Cortex-A715 + 3x Cortex-A510",
     "gpu": "Adreno 740", "ai_engine": "Hexagon NPU", "fabrication_process_nm": 4, "release_date": "2022-11-15",
     "performance_score": 85, "efficiency_score": 70},
    {"name": "Snapdragon 8 Elite", "manufacturer": "Qualcomm", "cpu_architecture": "2x Oryon Prime + 6x Oryon Performance",
     "gpu": "Adreno 830", "ai_engine": "Hexagon NPU", "fabrication_process_nm": 3, "release_date": "2024-10-21",
     "performance_score": 99, "efficiency_score": 84},
    {"name": "Dimensity 9400", "manufacturer": "MediaTek", "cpu_architecture": "1x Cortex-X925 + 3x Cortex-X4 + 4x Cortex-A720",
     "gpu": "Immortalis-G925 MC12", "ai_engine": "MediaTek APU 895", "fabrication_process_nm": 3,
     "release_date": "2024-10-30", "performance_score": 96, "efficiency_score": 80},
    {"name": "Exynos 2200", "manufacturer": "Samsung", "cpu_architecture": "1x Cortex-X2 + 3x Cortex-A710 + 4x Cortex-A510",
     "gpu": "Xclipse 920 (AMD RDNA2)", "ai_engine": "Samsung NPU", "fabrication_process_nm": 4,
     "release_date": "2022-02-09", "performance_score": 78, "efficiency_score": 62},
    {"name": "Exynos 1380", "manufacturer": "Samsung", "cpu_architecture": "1x Cortex-A78 + 3x Cortex-A78 + 4x Cortex-A55",
     "gpu": "Mali-G68 MP5", "ai_engine": "Samsung NPU", "fabrication_process_nm": 5,
     "release_date": "2023-03-14", "performance_score": 60, "efficiency_score": 68},
    {"name": "Tensor G3", "manufacturer": "Google", "cpu_architecture": "1x Cortex-X3 + 4x Cortex-A715 + 4x Cortex-A510",
     "gpu": "Mali-G715 Immortalis", "ai_engine": "Google Tensor TPU", "fabrication_process_nm": 4,
     "release_date": "2023-10-04", "performance_score": 76, "efficiency_score": 64},
    {"name": "Kirin 9000s", "manufacturer": "HiSilicon", "cpu_architecture": "1x TaiShan V120 + 3x Cortex-A720 + 4x Cortex-A520",
     "gpu": "Maleoon 910", "ai_engine": "Da Vinci NPU", "fabrication_process_nm": 7,
     "release_date": "2023-08-29", "performance_score": 72, "efficiency_score": 58},
    {"name": "Apple A16 Bionic", "manufacturer": "Apple", "cpu_architecture": "2x performance + 4x efficiency (6-core)",
     "gpu": "Apple GPU (5-core)", "ai_engine": "16-core Neural Engine", "fabrication_process_nm": 4,
     "release_date": "2022-09-16", "performance_score": 87, "efficiency_score": 80},
]

# Laptops FK to CPU/GPU by name  seeded after CPUs/GPUs exist.
LAPTOPS = [
    {"name": "ThinkPad X1 Carbon Gen 12", "manufacturer": "Lenovo", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 32, "storage_gb": 1024, "display": "14\" 2880x1800 OLED", "refresh_rate_hz": 60,
     "battery_whr": 57, "weight_kg": 1.12, "release_date": "2024-03-01",
     "performance_score": 78, "portability_score": 92, "value_score": 55},
    {"name": "Dell XPS 15 9530", "manufacturer": "Dell", "cpu": "Core i9-14900K", "gpu": "GeForce RTX 4070 Super",
     "ram_gb": 32, "storage_gb": 1024, "display": "15.6\" 3456x2160 OLED", "refresh_rate_hz": 60,
     "battery_whr": 86, "weight_kg": 1.92, "release_date": "2023-05-01",
     "performance_score": 88, "portability_score": 60, "value_score": 52},
    {"name": "ASUS ROG Zephyrus G14", "manufacturer": "ASUS", "cpu": "Ryzen 9 9950X", "gpu": "GeForce RTX 4070 Super",
     "ram_gb": 32, "storage_gb": 1024, "display": "14\" 2560x1600 165Hz", "refresh_rate_hz": 165,
     "battery_whr": 76, "weight_kg": 1.5, "release_date": "2024-02-01",
     "performance_score": 90, "portability_score": 74, "value_score": 68},
    {"name": "HP EliteBook 840 G11", "manufacturer": "HP", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "14\" 1920x1200 IPS", "refresh_rate_hz": 60,
     "battery_whr": 51, "weight_kg": 1.36, "release_date": "2024-04-01",
     "performance_score": 65, "portability_score": 85, "value_score": 70},
    {"name": "Lenovo Legion Pro 7i", "manufacturer": "Lenovo", "cpu": "Core i9-14900K", "gpu": "GeForce RTX 4090",
     "ram_gb": 32, "storage_gb": 2048, "display": "16\" 2560x1600 240Hz", "refresh_rate_hz": 240,
     "battery_whr": 99, "weight_kg": 2.5, "release_date": "2024-01-01",
     "performance_score": 97, "portability_score": 40, "value_score": 58},
    {"name": "MacBook Pro 14 (M-class, Apple silicon era)", "manufacturer": "Apple", "cpu": None, "gpu": None,
     "ram_gb": 18, "storage_gb": 512, "display": "14.2\" 3024x1964 Mini-LED", "refresh_rate_hz": 120,
     "battery_whr": 70, "weight_kg": 1.55, "release_date": "2023-10-01",
     "performance_score": 89, "portability_score": 80, "value_score": 48},
    {"name": "Dell Latitude 5440", "manufacturer": "Dell", "cpu": "Core i5-14600K", "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "14\" 1920x1080 IPS", "refresh_rate_hz": 60,
     "battery_whr": 54, "weight_kg": 1.56, "release_date": "2023-06-01",
     "performance_score": 60, "portability_score": 80, "value_score": 78},
    {"name": "ASUS Zenbook 14 OLED", "manufacturer": "ASUS", "cpu": "Ryzen 7 9800X3D", "gpu": None,
     "ram_gb": 16, "storage_gb": 1024, "display": "14\" 2880x1800 OLED", "refresh_rate_hz": 90,
     "battery_whr": 75, "weight_kg": 1.2, "release_date": "2024-05-01",
     "performance_score": 70, "portability_score": 88, "value_score": 80},
    {"name": "Acer Nitro V 15", "manufacturer": "Acer", "cpu": "Ryzen 5 7600", "gpu": "GeForce RTX 4060",
     "ram_gb": 16, "storage_gb": 512, "display": "15.6\" 1920x1080 144Hz", "refresh_rate_hz": 144,
     "battery_whr": 57, "weight_kg": 2.1, "release_date": "2023-08-01",
     "performance_score": 68, "portability_score": 62, "value_score": 84},
    {"name": "HP ZBook Firefly 14 G11", "manufacturer": "HP", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 32, "storage_gb": 1024, "display": "14\" 1920x1200 IPS", "refresh_rate_hz": 60,
     "battery_whr": 56, "weight_kg": 1.36, "release_date": "2024-04-01",
     "performance_score": 76, "portability_score": 84, "value_score": 60},
    {"name": "Lenovo ThinkPad T14 Gen 5", "manufacturer": "Lenovo", "cpu": "Ryzen 5 7600", "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "14\" 1920x1200 IPS", "refresh_rate_hz": 60,
     "battery_whr": 57, "weight_kg": 1.38, "release_date": "2024-02-01",
     "performance_score": 58, "portability_score": 83, "value_score": 82},
    {"name": "MSI Stealth 16 Studio", "manufacturer": "MSI", "cpu": "Core i9-14900K", "gpu": "GeForce RTX 4080 Super",
     "ram_gb": 32, "storage_gb": 2048, "display": "16\" 2560x1600 240Hz", "refresh_rate_hz": 240,
     "battery_whr": 99, "weight_kg": 2.1, "release_date": "2024-01-01",
     "performance_score": 93, "portability_score": 55, "value_score": 55},
    {"name": "Framework Laptop 13", "manufacturer": "Framework", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 32, "storage_gb": 1024, "display": "13.5\" 2256x1504 IPS", "refresh_rate_hz": 60,
     "battery_whr": 61, "weight_kg": 1.3, "release_date": "2024-06-01",
     "performance_score": 72, "portability_score": 82, "value_score": 74},
    {"name": "Razer Blade 14", "manufacturer": "Razer", "cpu": "Ryzen 9 7950X3D", "gpu": "GeForce RTX 4070 Super",
     "ram_gb": 32, "storage_gb": 1024, "display": "14\" 2560x1600 240Hz", "refresh_rate_hz": 240,
     "battery_whr": 68, "weight_kg": 1.84, "release_date": "2024-02-01",
     "performance_score": 87, "portability_score": 65, "value_score": 50},
    {"name": "Acer Swift Go 14", "manufacturer": "Acer", "cpu": "Core i5-14600K", "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "14\" 2880x1800 OLED", "refresh_rate_hz": 90,
     "battery_whr": 65, "weight_kg": 1.34, "release_date": "2023-09-01",
     "performance_score": 62, "portability_score": 86, "value_score": 82},
    {"name": "MacBook Air 15 (M3)", "manufacturer": "Apple", "cpu": None, "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "15.3\" 2880x1864 IPS", "refresh_rate_hz": 60,
     "battery_whr": 66.5, "weight_kg": 1.51, "release_date": "2024-03-08",
     "performance_score": 75, "portability_score": 86, "value_score": 62},
    {"name": "MacBook Pro 16 (M3 Max)", "manufacturer": "Apple", "cpu": None, "gpu": None,
     "ram_gb": 36, "storage_gb": 1024, "display": "16.2\" 3456x2234 Mini-LED", "refresh_rate_hz": 120,
     "battery_whr": 100, "weight_kg": 2.16, "release_date": "2023-11-07",
     "performance_score": 95, "portability_score": 55, "value_score": 40},
    {"name": "Microsoft Surface Laptop 6", "manufacturer": "Microsoft", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 32, "storage_gb": 1024, "display": "13.8\" 2304x1536 PixelSense", "refresh_rate_hz": 60,
     "battery_whr": 53.8, "weight_kg": 1.34, "release_date": "2024-06-18",
     "performance_score": 73, "portability_score": 84, "value_score": 58},
    {"name": "Samsung Galaxy Book4 Pro", "manufacturer": "Samsung", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "14\" 2880x1800 AMOLED", "refresh_rate_hz": 120,
     "battery_whr": 63, "weight_kg": 1.17, "release_date": "2024-01-01",
     "performance_score": 74, "portability_score": 90, "value_score": 56},
    {"name": "HP Spectre x360 14", "manufacturer": "HP", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 16, "storage_gb": 1024, "display": "14\" 2880x1800 OLED", "refresh_rate_hz": 60,
     "battery_whr": 68, "weight_kg": 1.36, "release_date": "2024-03-01",
     "performance_score": 74, "portability_score": 82, "value_score": 60},
    {"name": "HP Pavilion Plus 14", "manufacturer": "HP", "cpu": "Core i5-14600K", "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "14\" 2880x1800 OLED", "refresh_rate_hz": 90,
     "battery_whr": 68, "weight_kg": 1.4, "release_date": "2023-10-01",
     "performance_score": 63, "portability_score": 84, "value_score": 78},
    {"name": "Dell XPS 13 Plus", "manufacturer": "Dell", "cpu": "Core i5-14600K", "gpu": None,
     "ram_gb": 16, "storage_gb": 512, "display": "13.4\" 1920x1200 IPS", "refresh_rate_hz": 60,
     "battery_whr": 55, "weight_kg": 1.26, "release_date": "2023-05-01",
     "performance_score": 61, "portability_score": 88, "value_score": 62},
    {"name": "Lenovo Yoga 9i", "manufacturer": "Lenovo", "cpu": "Core Ultra 9 285K", "gpu": None,
     "ram_gb": 16, "storage_gb": 1024, "display": "14\" 2880x1800 OLED", "refresh_rate_hz": 60,
     "battery_whr": 75, "weight_kg": 1.4, "release_date": "2024-02-01",
     "performance_score": 73, "portability_score": 82, "value_score": 58},
    {"name": "ASUS Vivobook Pro 15", "manufacturer": "ASUS", "cpu": "Ryzen 5 9600X", "gpu": "GeForce RTX 4060",
     "ram_gb": 16, "storage_gb": 512, "display": "15.6\" 1920x1080 144Hz", "refresh_rate_hz": 144,
     "battery_whr": 70, "weight_kg": 1.7, "release_date": "2024-04-01",
     "performance_score": 66, "portability_score": 72, "value_score": 80},
]


class Command(BaseCommand):
    help = (
        "Seed a hand-curated starter dataset of publicly known hardware specs "
        "(not scraped). Fallback/bootstrap for hardware/providers/manager.py's "
        "primary Wikidata sync."
    )

    def handle(self, *args, **options):
        cpu_created = self._seed(CPU, CPUS)
        gpu_created = self._seed(GPU, GPUS)
        soc_created = self._seed(MobileSoC, MOBILE_SOCS)
        laptop_created = self._seed_laptops()
        self.stdout.write(self.style.SUCCESS(
            f"CPUs: {cpu_created} created. GPUs: {gpu_created} created. "
            f"Mobile SoCs: {soc_created} created. Laptops: {laptop_created} created."
        ))

    def _seed(self, model, rows):
        created_count = 0
        for row in rows:
            defaults = {k: v for k, v in row.items() if k != "name"}
            obj, created = model.objects.get_or_create(name=row["name"], defaults=defaults)
            if created:
                created_count += 1
                self.stdout.write(f"Created {model.__name__}: {obj.name}")
            self._maybe_generate_profile(obj, self._type_key_for(model))
        return created_count

    def _seed_laptops(self):
        created_count = 0
        for row in LAPTOPS:
            cpu = CPU.objects.filter(name=row["cpu"]).first() if row.get("cpu") else None
            gpu = GPU.objects.filter(name=row["gpu"]).first() if row.get("gpu") else None
            defaults = {k: v for k, v in row.items() if k not in ("name", "cpu", "gpu")}
            defaults["cpu"] = cpu
            defaults["gpu"] = gpu
            obj, created = Laptop.objects.get_or_create(name=row["name"], defaults=defaults)
            if created:
                created_count += 1
                self.stdout.write(f"Created Laptop: {obj.name}")
            self._maybe_generate_profile(obj, "laptop")
        return created_count

    @staticmethod
    def _type_key_for(model):
        return {CPU: "cpu", GPU: "gpu", MobileSoC: "mobile_soc", Laptop: "laptop"}[model]

    def _maybe_generate_profile(self, instance, type_key):
        try:
            profile = ai_knowledge.generate_profile(instance, type_key)
            if profile is not None:
                self.stdout.write(f"  -> AI profile generated for {instance}")
        except Exception as exc:  # noqa: BLE001  a bad AI call must not abort the whole seed run
            self.stderr.write(f"  -> AI profile generation failed for {instance}: {exc}")
