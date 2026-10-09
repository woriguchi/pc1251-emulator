"""pytestで動かすときの設定。ROMやPC-インタープリタのダンプがなければ、それを使う試験を飛ばす"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pc1251emu.machine import RomNotFound, find_rom  # noqa: E402


def _have(model: str) -> bool:
    try:
        find_rom(f"cpu-{model}.rom")
        find_rom(f"bas-{model}.rom")
        return True
    except RomNotFound:
        return False


HAVE_ROM = _have("1251")
HAVE_ROM_1245 = _have("1245")

NO_ROM_NEEDED = {
    "test_switch_knob_matches_label",
    "test_version",
    "test_lcd_ram_mirrors",
    "test_sound_queue_keeps_up",
}


def pytest_collection_modifyitems(config, items):
    from test_basic import DUMP

    for item in items:
        if item.module.__name__ == "test_cpu" or item.name in NO_ROM_NEEDED:
            continue
        if item.module.__name__ == "test_pc1245":
            if not HAVE_ROM_1245:
                item.add_marker(pytest.mark.skip(reason="PC-1245のROMがない(rom/cpu-1245.romなど)"))
            elif "interpreter" in item.name and not os.path.exists(DUMP):
                item.add_marker(pytest.mark.skip(reason="PC-インタープリタのダンプがない"))
            continue
        if not HAVE_ROM:
            item.add_marker(pytest.mark.skip(reason="ROMがない(実機から読み出してrom/に置く)"))
        elif item.name == "test_pc_interpreter" and not os.path.exists(DUMP):
            item.add_marker(pytest.mark.skip(reason="PC-インタープリタのダンプがない"))
