# ticket_scanner

Servicio HTTP que convierte la foto de un ticket de compra español en JSON estructurado: comercio, fecha, líneas de artículos y total, con los importes en céntimos. Está pensado para que cualquier backend o proceso automático lo use como pieza independiente: le envías una foto y recibes datos listos para guardar.

Está probado sobre todo con tickets de supermercado (Mercadona, Lidl, Aldi, Carrefour, Dia...), aunque sirve para cualquier ticket de compra (restaurantes, tiendas...).

## Cómo funciona

```
foto(s) ──► preprocesado ──► modelo principal ──► validación ──► ¿avisos? ──no──► respuesta "ok"
                                                                     │
                                                                    sí
                                                                     ▼
                                                     reintento con modelo más potente
                                                                     │
                                                                     ▼
                                                     se queda el resultado con menos avisos
                                                     (status "revisar" si aún los tiene)
```

1. **Preprocesado.** Acepta JPEG, PNG, WEBP y HEIC/HEIF (fotos de iPhone). Endereza la foto según el EXIF, la reduce a 2048 px por el lado mayor, la convierte a JPEG y elimina los metadatos (ubicación incluida).
2. **Extracción.** Un modelo de visión lee el ticket y rellena un esquema fijo. Por defecto es Gemini 3.5 Flash-Lite (rápido y gratuito dentro de la cuota de Google AI Studio). La librería que habla con los modelos es [Pydantic AI](https://ai.pydantic.dev), así que cambiar de proveedor es cambiar una variable.
3. **Validación.** El modelo puede equivocarse o inventar, así que el servicio comprueba la aritmética del propio ticket: la suma de las líneas debe dar el total, y cantidad × precio debe dar el importe de cada línea (con 1 céntimo de margen). También comprueba que la fecha sea válida y no futura, y recoge si el modelo ha visto la foto borrosa o varios tickets.
4. **Reintento.** Si hay algún aviso, repite la extracción con un modelo más potente (Gemini 3.8 Flash) y devuelve el resultado con menos avisos. Si ese segundo modelo falla o tarda, se devuelve el primero.
5. **Respaldo (opcional).** Si Google no responde o se agota la cuota, puede pasar a un modelo local con Ollama.

Cada llamada al modelo tiene un límite de 60 s, para que una petición no se quede colgada si Gemini está saturado.

## Puesta en marcha

Requisitos: Podman con `podman compose` y una clave gratuita de [Google AI Studio](https://aistudio.google.com/apikey).

```bash
cp .env.example .env
# edita .env: API_KEY y AISTUDIO_KEY como mínimo
podman compose up -d --build
curl -s 127.0.0.1:8000/health
# {"status":"ok","model":"google:gemini-3.5-flash-lite"}
```

En WSL usa `127.0.0.1` en lugar de `localhost`.

### Variables de entorno (`.env`)

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `API_KEY` | (obligatoria) | Contraseña de **tu** servicio: los clientes la envían en la cabecera `X-API-Key`. Invéntala, por ejemplo con `openssl rand -hex 24`. |
| `AISTUDIO_KEY` | — | Clave de Google AI Studio. El servicio la usa para llamar a Gemini. **No es la misma que `API_KEY`.** |
| `TICKET_MODEL` | `google:gemini-3.5-flash-lite` | Modelo principal. |
| `TICKET_RETRY_MODEL` | `google:gemini-3.8-flash` | Modelo del reintento cuando hay avisos. Vacío lo desactiva. |
| `TICKET_FALLBACK_MODEL` | (vacío) | Modelo de respaldo si el proveedor falla, por ejemplo `ollama:qwen3-vl:8b`. |
| `OLLAMA_BASE_URL` | `http://ollama:11434/v1` | Dirección de Ollama. |
| `IMAGE_MAX_SIDE` | `2048` | Lado mayor, en px, al que se reduce cada foto. |
| `MAX_UPLOAD_MB` | `10` | Tamaño máximo de cada foto. |
| `DEBUG_DB_PATH` | `/data/debug.db` | SQLite con el registro de cada petición. |
| `DEBUG_SAVE_IMAGES` | `false` | Si es `true`, guarda las fotos procesadas en `DEBUG_IMAGES_DIR`. |
| `DEBUG_IMAGES_DIR` | `/data/images` | Carpeta de esas fotos. |

Los modelos se escriben como `proveedor:nombre`. Los proveedores admitidos son `google` y `ollama`.

## Uso

```bash
curl -H "X-API-Key: $API_KEY" -F image=@ticket.jpg 127.0.0.1:8000/v1/tickets/extract
```

Si el ticket es largo y no cabe bien en una foto, se puede partir en varias (de 1 a 5): repite el campo `image` en orden, de arriba abajo. Las fotos pueden solaparse, porque las líneas repetidas se cuentan una sola vez.

```bash
curl -H "X-API-Key: $API_KEY" -F image=@arriba.jpg -F image=@abajo.jpg 127.0.0.1:8000/v1/tickets/extract
```

### Respuesta

```json
{
  "status": "ok",
  "warnings": [],
  "store": {"name": "MERCADONA", "tax_id": "A46103834"},
  "date": "2026-10-20",
  "currency": "EUR",
  "total_cents": 345,
  "items": [
    {"description": "LECHE ENTERA", "quantity": 2, "unit_price_cents": 95, "amount_cents": 190},
    {"description": "PLATANO", "quantity": 1.104, "unit_price_cents": 199, "amount_cents": 220},
    {"description": "DTO. TARJETA", "quantity": null, "unit_price_cents": null, "amount_cents": -65}
  ],
  "model": "gemini-3.5-flash-lite"
}
```

| Campo | Significado |
|---|---|
| `status` | `ok` si todo cuadra; `revisar` si hay avisos y conviene que una persona lo mire. |
| `warnings` | Lista de avisos (`code` + `message` en español). Vacía si `status` es `ok`. |
| `store` | Nombre y NIF/CIF del comercio (`null` si no se leen). |
| `date` | Fecha del ticket, `AAAA-MM-DD` (`null` si no se lee). |
| `total_cents` | Total pagado, en céntimos. |
| `items[].quantity` | Unidades, o kg en los productos a peso; `null` si no aparece. |
| `items[].unit_price_cents` | Precio por unidad o por kg; `null` si no aparece. |
| `items[].amount_cents` | Importe de la línea. Los descuentos van como líneas negativas. |
| `model` | Modelo que ha hecho la extracción finalmente. |

Los importes van en céntimos enteros para evitar errores de redondeo: 26,80 € es `2680`.

### Avisos (`status: "revisar"`)

| Código | Cuándo aparece |
|---|---|
| `sum_mismatch` | La suma de las líneas no coincide con el total. |
| `line_mismatch` | En una línea, cantidad × precio no da el importe. |
| `no_items` | No se ha leído ningún artículo. |
| `total_not_positive` | El total no se ha leído o no es positivo. |
| `date_invalid` | No hay fecha o no es válida. |
| `date_future` | La fecha es posterior a hoy (hora de Madrid). |
| `low_quality` | La foto está borrosa, oscura o cortada. Los importes ilegibles se dejan vacíos en vez de inventarlos. |
| `multiple_receipts` | Hay varios tickets en la foto y solo se ha extraído uno. |

Un `revisar` no es un error: la respuesta trae todo lo que se ha podido leer. El cliente decide si lo acepta, lo corrige o pide repetir la foto.

### Errores

Los errores devuelven `{"error": "<código>", "message": "<texto>"}`.

| HTTP | `error` | Causa |
|---|---|---|
| 400 | `invalid_image` | Falta el campo `image`, o el fichero no es una imagen admitida. |
| 400 | `too_many_images` | Más de 5 fotos. |
| 401 | `unauthorized` | `X-API-Key` ausente o incorrecta. |
| 413 | `too_large` | Alguna foto supera `MAX_UPLOAD_MB`. |
| 422 | `not_a_receipt` | La imagen no es un ticket de compra. |
| 503 | `model_unavailable` | El modelo no responde o se ha agotado la cuota. Si Google indica cuánto esperar, va en la cabecera `Retry-After` (segundos). |

## Cómo sacar buenos resultados

- **Una foto por ticket**, de frente, con luz y con el ticket entero y estirado.
- **Tickets largos:** mejor 2 o 3 fotos solapadas que una lejana en la que no se lean las letras.
- **Comprueba `status`:** si integras el servicio en un proceso automático, guarda directamente los `ok` y deja los `revisar` para una revisión manual o para pedir otra foto.
- **Tiempos:** lo normal son entre 3 y 15 s. Si salta el reintento y Gemini está saturado, puede llegar a 1-2 min. Pon un timeout de cliente de al menos 150 s.
- **Cuota gratuita:** Gemini 3.5 Flash-Lite permite unas 500 peticiones al día y 15 por minuto. El reintento con 3.8 Flash solo admite 20 al día: cuando se agota, se devuelve el primer resultado. Los límites exactos están en AI Studio, en la sección *Rate limit*.
- **Privacidad:** la cuota gratuita de Gemini se puede usar para pruebas. Para dar servicio a usuarios del Espacio Económico Europeo, las condiciones de Google exigen el plan de pago, o usar Ollama en local.

## Ollama (modelo local de respaldo)

```bash
podman compose --profile ollama up -d
podman compose exec ollama ollama pull qwen3-vl:8b
```

Después pon en `.env` `TICKET_FALLBACK_MODEL=ollama:qwen3-vl:8b` y reinicia el servicio con `podman compose up -d`. También puedes usarlo como modelo principal (`TICKET_MODEL=ollama:qwen3-vl:8b`) para no depender de Google, aunque es más lento y menos preciso.

## Registro de depuración

Cada petición se guarda en la tabla `extractions` de `/data/debug.db` (en el volumen `data`). Se guardan:
- el hash de las fotos;
- el modelo usado, y si hubo reintento o respaldo;
- los avisos, los tokens consumidos y la latencia;
- la extracción en bruto del modelo y la respuesta.

```bash
podman compose exec api python -c "import sqlite3; [print(r) for r in sqlite3.connect('/data/debug.db').execute('select created_at, http_status, status, model_used, latency_ms, warnings from extractions order by id desc limit 10')]"
```

## Desarrollo

```bash
uv sync
uv run pytest                                              # tests sin red (modelo simulado)
LIVE_TICKET_IMAGE=ticket.jpg uv run pytest -m live -s      # prueba real contra Gemini (requiere AISTUDIO_KEY)
```

```
ticket_scanner/
  api.py          endpoints, autenticación, errores HTTP y registro
  image.py        validación y preprocesado de fotos
  extractor.py    llamada al modelo, reintento y respaldo (Pydantic AI)
  prompt.py       instrucciones para el modelo
  schema.py       esquema de extracción y de respuesta (céntimos)
  validation.py   comprobaciones aritméticas y de coherencia
  debug_log.py    registro en SQLite
  config.py       variables de entorno
```
