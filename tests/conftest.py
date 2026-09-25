"""pytestで動かすときの設定。ROMや記事のダンプがなければ、それを使う試験を飛ばす"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pc1251emu.machine import RomNotFound, find_rom  # noqa: E402

try:
    find_rom("cpu-1251.rom")
    find_rom("bas-1251.rom")
    HAVE_ROM = True
except RomNotFound:
    HAVE_ROM = False

NO_ROM_NEEDED = {"test_switch_knob_matches_label"}


def pytest_collection_modifyitems(config, items):
    from test_basic import DUMP

    for item in items:
        if item.module.__name__ == "test_cpu" or item.name in NO_ROM_NEEDED:
            continue
        if not HAVE_ROM:
            item.add_marker(pytest.mark.skip(reason="ROMがない(実機から読み出してrom/に置く)"))
        elif item.name == "test_pc_interpreter" and not os.path.exists(DUMP):
            item.add_marker(pytest.mark.skip(reason="PC-インタープリタのダンプがない"))
