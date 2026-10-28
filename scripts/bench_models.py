"""Compara modelos de Ollama leyendo las fotos de un directorio (herramienta manual).

Uso: uv run python scripts/bench_models.py <modelo> [<modelo>...] [--images DIR] [--ollama URL]
"""

import argparse
import asyncio
import time
from datetime import date
from pathlib import Path

import httpx

from ticket_scanner.config import Settings
from ticket_scanner.extractor import NotAReceipt, extractor_from_settings
from ticket_scanner.image import preprocess


async def run_photo(extractor, path: Path) -> dict:
    """Extrae una foto y resume el resultado; las excepciones no paran el bucle."""
    data = preprocess(path.read_bytes(), 2048)
    start = time.perf_counter()
    try:
        res = await extractor.extract([data], date.today())
        estado = res.response.status
    except NotAReceipt as exc:
        res, estado = exc.result, "no_ticket"
    except Exception as exc:
        res, estado = None, f"error: {type(exc).__name__}"
    row = {"foto": path.name, "estado": estado, "s": time.perf_counter() - start}
    if res:
        r = res.response
        row |= {
            "avisos": ",".join(w.code for w in r.warnings) or "-",
            "total": f"{r.total_cents / 100:.2f}",
            "lineas": len(r.items),
            "tokens": res.output_tokens,
        }
    return row


async def bench_model(http: httpx.AsyncClient, url: str, model: str, photos: list[Path]) -> list[dict]:
    tags = (await http.get(f"{url}/api/tags")).json()["models"]
    if model not in {t["name"] for t in tags}:
        print(f"{model}: no descargado (ollama pull {model})")
        return []
    settings = Settings(
        api_key="bench",
        ticket_model=f"ollama:{model}",
        ticket_retry_model="",
        ticket_fallback_model="",
        ollama_base_url=f"{url}/v1",
    )
    extractor = extractor_from_settings(settings)
    rows = []
    for i, path in enumerate(photos):
        print(f"{model}: {path.name}...", flush=True)
        row = await run_photo(extractor, path)
        row["modelo"] = model
        if i == 0:
            row["foto"] += " (en frío)"  # incluye la carga del modelo en memoria
        rows.append(row)
    # VRAM con el modelo cargado; luego se descarga para no falsear el siguiente
    ps = (await http.get(f"{url}/api/ps")).json()["models"]
    vram = next((m["size_vram"] / 1e9 for m in ps if m["name"] == model), None)
    for row in rows:
        row["vram"] = "?" if vram is None else f"{vram:.1f}"
    await http.post(f"{url}/api/generate", json={"model": model, "keep_alive": 0})
    return rows


async def main() -> None:
    ap = argparse.ArgumentParser(description="Compara modelos de Ollama con fotos de tickets.")
    ap.add_argument("models", nargs="+", metavar="modelo")
    ap.add_argument("--images", type=Path, default=Path("tests/eval/tickets"))
    ap.add_argument("--ollama", default="http://127.0.0.1:11434", help="URL base de Ollama")
    args = ap.parse_args()
    url = args.ollama.rstrip("/")
    photos = sorted(p for p in args.images.iterdir() if p.is_file())

    rows = []
    async with httpx.AsyncClient(timeout=30) as http:
        for model in args.models:
            rows += await bench_model(http, url, model, photos)

    print("\n| modelo | foto | estado | avisos | total | líneas | tokens | s | VRAM GB |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['modelo']} | {r['foto']} | {r['estado']} | {r.get('avisos', '-')} "
            f"| {r.get('total', '-')} | {r.get('lineas', '-')} | {r.get('tokens', '-')} "
            f"| {r['s']:.1f} | {r['vram']} |"
        )


asyncio.run(main())
