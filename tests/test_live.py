import os
from datetime import date
from pathlib import Path

import pytest

from ticket_scanner.config import get_settings
from ticket_scanner.extractor import extractor_from_settings
from ticket_scanner.image import preprocess


@pytest.mark.live
async def test_real_ticket():
    path = os.environ.get("LIVE_TICKET_IMAGE")
    if not path or not get_settings().aistudio_key:
        pytest.skip("falta LIVE_TICKET_IMAGE o AISTUDIO_KEY")
    r = await extractor_from_settings(get_settings()).extract(
        preprocess(Path(path).read_bytes(), 2048), date.today()
    )
    assert r.response.total_cents > 0 and r.response.items
    print(r.response.model_dump_json(indent=2))
