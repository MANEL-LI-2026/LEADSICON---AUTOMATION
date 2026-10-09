# Endpoint Hugging Face para Leadsicon

Este código se ejecuta en **Hugging Face Inference Endpoints con GPU**. Render solo llama a la API; no instales estas dependencias en el servicio web ni en su worker.

El handler usa tres modelos:

| Proceso | Modelo |
| --- | --- |
| Palabras y tiempos originales | `openai/whisper-large-v3-turbo` |
| Separación de voces | `pyannote/speaker-diarization-3.1` |
| Descripción de imágenes de cada escena | `Qwen/Qwen2.5-VL-3B-Instruct` |

## Desplegar

1. Crea un repositorio **privado de modelos** en Hugging Face. Copia `handler.py`, `alignment.py` y este `requirements.txt` en su raíz. No copies el `requirements.txt` de la web. Consulta el [contrato oficial de custom handlers](https://huggingface.co/docs/inference-endpoints/guides/custom_handler) y las [dependencias personalizadas](https://huggingface.co/docs/inference-endpoints/guides/custom_dependencies).
2. Desde tu cuenta acepta las condiciones de acceso de [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) y [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0), dependiente del anterior. Revisa también las licencias y condiciones de Whisper/Qwen para el uso que harás.
3. Crea un Inference Endpoint desde ese repositorio. Selecciona **Custom** como tarea y acceso **Protected**, que exige un token y permite llamadas HTTPS desde Render. La opción **Private** usa conectividad privada y requiere una configuración de red adicional; no es la opción prevista aquí.
4. Selecciona una GPU. Recomendación inicial: al menos **24 GB de VRAM**; no se ha medido el rendimiento ni la memoria real de esta combinación. No está implementada cuantización. Revisa el precio y la disponibilidad antes de contratarla. No se ha creado ni contratado ningún endpoint desde este proyecto.
5. Configura en el endpoint un secreto `HF_MODEL_TOKEN` de una cuenta que tenga acceso a ambos modelos de pyannote y lectura de los repositorios necesarios. Se usa para descargar modelos; no se incluye en las respuestas. El primer arranque descarga y carga los tres modelos y puede tardar varios minutos. Espera a que el endpoint esté listo antes de procesar videos.
6. Copia la URL raíz HTTPS del endpoint. Crea un token de alcance mínimo que permita invocarlo. Configura ese token como `HF_TOKEN` en Render; puede ser distinto del token de descarga de modelos. Nunca pongas tokens en Git ni en el chat.

## Render

Configura estas variables en el **Background Worker** y, para mostrar el estado del proveedor, también en el servicio web:

| Variable | Valor |
| --- | --- |
| `TRANSCRIPTION_PROVIDER` | `huggingface` |
| `HF_TOKEN` | Token privado con permiso para invocar el endpoint protegido |
| `HF_TRANSCRIPTION_ENDPOINT` | URL raíz de tu endpoint, `https://…endpoints.huggingface.cloud` |
| `HF_TRANSCRIPTION_ENABLED` | `1` (predeterminado); `0` desactiva este análisis |

No necesitas `KIE_API_KEY` para usar Hugging Face. El chat de Kie conserva su propia configuración. `TRANSCRIPTION_PROVIDER=kie` permite volver al proveedor anterior. Si omites el selector, una URL `HF_TRANSCRIPTION_ENDPOINT` configurada selecciona Hugging Face; sin ella se conserva Kie. No hay fallback automático a otro proveedor ni reintentos automáticos tras fallos de inferencia.

Se conservan `DATABASE_URL`, `APIFY_TOKEN` y los secretos OAuth de Drive del worker. Su comando continúa siendo `python library_worker.py`. Reinícialo después de cambiar variables. El arranque reactiva tareas de transcripción bloqueadas por falta de configuración; los fallos de proveedor, permisos o formato requieren revisión y reintento explícito desde la ficha.

## Flujo y límites

Like → descarga del MP4 → llamada al endpoint protegido → voz/hablantes/escenas en Supabase → visualización en Biblioteca → subida de videos y JSON a Drive.

La llamada envía el MP4 en Base64 dentro de `inputs`, con `schema_version=1`; el token va solo en Authorization. El cliente admite únicamente URLs raíz HTTPS de `*.endpoints.huggingface.cloud` y no sigue redirecciones con credenciales. No sirve sustituir la URL por un endpoint de Whisper estándar: no produciría diarización y escenas.

El endpoint decodifica audio mono a 16 kHz, obtiene tiempos por palabra y asigna cada palabra a la voz con mayor solapamiento en los turnos de pyannote. Agrupa palabras consecutivas del mismo hablante. Los números de persona son etiquetas estables dentro de ese video, no identidades reales. Voces solapadas se etiquetan como tales; si no hay turno reconocible, se conserva «Sin identificar».

La diarización de audio **no determina si la persona habla en cámara o es VoiceOver**. Esos segmentos quedan con `role=unknown`, para no inventar una correspondencia entre voz y rostro. No se reconocen personas ni se infieren rasgos personales. Los modelos pueden equivocarse en palabras y voces; las transcripciones automáticas se guardan pendientes de revisión.

FFmpeg detecta cambios visuales con umbral 0.30 y también divide tomas largas. Se describen dos fotogramas por intervalo, hasta 24 intervalos por defecto, en español. Es análisis por muestreo: puede omitir acciones rápidas entre fotogramas. No se usa el texto transcrito para inventar las escenas. Un video sin audio sigue produciendo descripciones visuales.

Límites iniciales:

- MP4 de hasta **20 MiB**. `HF_MAX_VIDEO_BYTES` permite ajustarlo; usa el mismo límite en Render y en el endpoint y comprueba que el servicio acepte el tamaño del JSON resultante. Base64 aumenta el payload aproximadamente un tercio. No se comprime ni modifica tu video automáticamente.
- Hasta **180 segundos**, configurables con `HF_MAX_DURATION_SECONDS` en el endpoint.
- Máximo 200 segmentos por capa. Si faltan tiempos utilizables, falla el análisis en lugar de guardar tiempos inventados.
- Cliente con timeout de diez minutos y espera de arranque de hasta 60 segundos mediante `X-Scale-Up-Timeout`. El proveedor puede imponer límites más cortos. Si agota la espera, la inferencia puede continuar: revisa el endpoint antes de reintentar.
- Los videos y el audio intermedio del handler se almacenan en un directorio temporal eliminado al terminar. El video se envía a Hugging Face para procesarlo; revisa sus políticas de tratamiento y registros para tu cuenta.

Los tres modelos se cargan una vez por réplica; un lock procesa un video a la vez para limitar picos de memoria. Un endpoint con escalado a cero puede necesitar varios minutos para arrancar. Eso reduce tiempo de GPU activa pero añade espera; revisa cómo factura Hugging Face tu configuración. No se ha garantizado operación gratuita.

## Validación realizada

Las pruebas offline verifican autenticación, formato, límites, timestamps, alineación de hablantes, ventanas de escenas, integración con Supabase/Drive simulados y ausencia de cargos duplicados por jobs ya guardados. Se resolvieron las dependencias mediante `pip install --dry-run --ignore-installed -r integrations/huggingface/requirements.txt`, sin instalar modelos en Render.

También se probó con un MP4 sintético real la decodificación, ausencia de audio, detección de un corte y extracción de imágenes; el modelo visual se simuló. **La carga de modelos y la inferencia GPU real no se han ejecutado.** Después de desplegar, valida un video corto con varias voces y cambios de escena y revisa los resultados en la ficha antes de procesar en lote.
