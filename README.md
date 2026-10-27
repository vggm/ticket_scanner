# ticket_scanner

Servicio HTTP que recibe la foto de un ticket español y devuelve un JSON con comercio, fecha, líneas y total, extraído con un modelo de visión (Gemini por defecto, Ollama como respaldo opcional).

## Configuración

Copia `.env.example` a `.env` y rellena al menos `API_KEY` (clave que exigirá el servicio en `X-API-Key`) y `AISTUDIO_KEY` (clave de Google AI Studio). El contenedor no arranca sin `AISTUDIO_KEY`. El resto de variables están documentadas por sus valores por defecto en `.env.example`.

## Arranque

```bash
podman compose up -d --build
curl -s localhost:8000/health
```

En WSL usa `127.0.0.1` en lugar de `localhost` (p. ej. `curl -s 127.0.0.1:8000/health`).

## Uso

```bash
curl -H "X-API-Key: $API_KEY" -F image=@ticket.jpg localhost:8000/v1/tickets/extract
```

Un ticket largo puede partirse en varias fotos (de 1 a 5): repite el campo `image`, en orden de arriba abajo. Las fotos pueden solaparse; más de 5 devuelve 400 `too_many_images`.

```bash
curl -H "X-API-Key: $API_KEY" -F image=@arriba.jpg -F image=@abajo.jpg localhost:8000/v1/tickets/extract
```

Respuesta (ejemplo):

```json
{
  "status": "ok",
  "warnings": [],
  "store": {"name": "MERCADONA", "tax_id": "A46103834"},
  "date": "2026-10-20",
  "currency": "EUR",
  "total_cents": 190,
  "items": [
    {"description": "LECHE ENTERA", "quantity": 2, "unit_price_cents": 95, "amount_cents": 190}
  ],
  "model": "gemini-3.5-flash-lite"
}
```

(Los campos exactos están definidos en `ticket_scanner/schema.py`.)

## Ollama (respaldo local)

```bash
podman compose --profile ollama up -d
podman compose exec ollama ollama pull qwen3-vl:8b
```

En `.env`: `TICKET_FALLBACK_MODEL=ollama:qwen3-vl:8b` y `OLLAMA_BASE_URL=http://ollama:11434/v1`.

## Tests

```bash
uv run pytest
LIVE_TICKET_IMAGE=ticket.jpg uv run pytest -m live -s   # requiere AISTUDIO_KEY
```
