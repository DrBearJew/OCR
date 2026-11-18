import base64
import io

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.services import ocr_glm
from app.services.paddle_vl_ik import GRID, MAX_PIXELS, MIN_PIXELS, grid_size


@pytest.mark.parametrize('original', [(574, 1071), (36, 25), (1, 100_000), (10_000, 10_000)])
def test_grid_is_aligned_and_bounded(original):
    w, h = grid_size(*original)
    assert w % GRID == h % GRID == 0
    assert MIN_PIXELS <= w * h <= MAX_PIXELS


def test_ik_pipeline_uses_native_profile_and_preserves_quantities(tmp_path, monkeypatch):
    path = tmp_path / 'page.png'
    Image.new('RGB', (500, 250), 'white').save(path)
    provider = ocr_glm.PaddleVLLlamaCppOCRProvider(Settings(paddle_vl_ik_profile=True))
    monkeypatch.setattr(provider, '_validate_multimodal_config', lambda: None)
    calls = []
    finish = 'stop'

    def post(url, *, json, **kwargs):
        assert url.endswith('/v1/chat/completions')
        calls.append(json)
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': '1\n1\n1\n1\n1'}, 'finish_reason': finish}],
        })

    monkeypatch.setattr(ocr_glm.httpx, 'post', post)
    results = provider.extract_text_batch([str(path), str(path)])
    assert len(calls) == 2
    for result, request in zip(results, calls, strict=True):
        assert result.text == '1\n1\n1\n1\n1'
        assert request['repeat_penalty'] == 1.0 and request['cache_prompt'] is False
        image, cue = request['messages'][0]['content']
        assert cue == {'type': 'text', 'text': 'OCR:'}
        with Image.open(io.BytesIO(base64.b64decode(image['image_url']['url'].split(',')[1]))) as prepared:
            assert prepared.size == grid_size(500, 250)

    finish = 'length'
    with pytest.raises(ocr_glm.OCRProviderError, match='generation limit'):
        provider.extract_text(str(path))
