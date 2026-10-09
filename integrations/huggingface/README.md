# Endpoint Hugging Face para Leadsicon

Este código se ejecuta en **Hugging Face Inference Endpoints con GPU**. Render guarda favoritos en Supabase y avisa al endpoint; no instales estas dependencias en el servicio web ni en su worker.

El handler usa tres modelos:

| Proceso | Modelo |
| --- | --- |
| Palabras y tiempos originales | `openai/whisper-large-v3-turbo` |
| Separación de voces | `pyannote/speaker-diarization-3.1` |
| Descripción de imágenes de cada escena | `Qwen/Qwen2.5-VL-3B-Instruct` |

## Desplegar

1. Crea un repositorio **privado de modelos** en Hugging Face. Sube a su raíz todos los archivos del paquete generado por `build_bundle.py`, explicado abajo. No copies el `requirements.txt` de la web. Consulta el [contrato oficial de custom handlers](https://huggingface.co/docs/inference-endpoints/guides/custom_handler) y las [dependencias personalizadas](https://huggingface.co/docs/inference-endpoints/guides/custom_dependencies).
2. Desde tu cuenta acepta las condiciones de acceso de [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) y [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0), dependiente del anterior. Revisa también las licencias y condiciones de Whisper/Qwen para el uso que harás.
3. Crea un Inference Endpoint desde ese repositorio. Selecciona **Custom** como tarea y acceso **Protected**, que exige un token y permite llamadas HTTPS desde Render. La opción **Private** usa conectividad privada y requiere una configuración de red adicional; no es la opción prevista aquí.
4. Selecciona una GPU. Recomendación inicial: al menos **24 GB de VRAM**; no se ha medido el rendimiento ni la memoria real de esta combinación. No está implementada cuantización. Revisa el precio y la disponibilidad antes de contratarla. No se ha creado ni contratado ningún endpoint desde este proyecto.
5. Configura en el endpoint un secreto `HF_MODEL_TOKEN` de una cuenta que tenga acceso a ambos modelos de pyannote y lectura de los repositorios necesarios. Se usa para descargar modelos; no se incluye en las respuestas. El primer arranque descarga y carga los tres modelos y puede tardar varios minutos. Espera a que el endpoint esté listo antes de procesar videos.
6. Copia la URL raíz HTTPS del endpoint. Crea un token de alcance mínimo que permita invocarlo. Configura ese token como `HF_TOKEN` en Render; puede ser distinto del token de descarga de modelos. Nunca pongas tokens en Git ni en el chat.

## Supabase directo: sin worker separado en Render

El endpoint de Hugging Face ahora contiene un procesador de tareas que lee la cola de Supabase, descarga los videos, ejecuta los modelos localmente y guarda las transcripciones **directamente en Supabase**. También puede importar los runs de Apify y subir los archivos a Drive cuando lo conectes. Render solo atiende la web, guarda el favorito y avisa al endpoint mediante una petición breve. No envía su contraseña de base de datos ni los secretos de Google por esa petición.

Prepara el paquete completo antes de subirlo al repositorio de modelos:

```sh
python integrations/huggingface/build_bundle.py --output /tmp/leadsicon-hf-deploy
```

Usa un directorio nuevo fuera del checkout. Sube **todos** los archivos generados a la raíz del repositorio privado de modelos. El paquete incluye `handler.py`, `alignment.py`, `remote_processor.py`, las dependencias del endpoint y los módulos ligeros de persistencia, validación, descarga y Drive. No contiene credenciales. No alcanza con subir solo el handler antiguo de inferencia.

En **el servicio web de Render**, configura:

| Variable | Valor |
| --- | --- |
| `DATABASE_URL` | Conexión privada de Supabase, como hasta ahora |
| `TRANSCRIPTION_PROVIDER` | `huggingface` |
| `HF_PROCESSING_MODE` | `remote` (predeterminado para Hugging Face) |
| `HF_TOKEN` | Token que permite invocar el endpoint protegido |
| `HF_TRANSCRIPTION_ENDPOINT` | URL raíz HTTPS del endpoint |
| `APIFY_TOKEN` | Para iniciar las búsquedas del scraper |

En **el endpoint de Hugging Face**, configura estos secretos/variables antes del despliegue:

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | **La misma base Supabase** que usa Render; conexión privada del propietario de las tablas |
| `HF_MODEL_TOKEN` | Acceso de lectura a modelos y condiciones de pyannote aceptadas |
| `APIFY_TOKEN` | Importar resultados completos de los runs de búsqueda |
| `HF_REMOTE_PROCESSING_ENABLED` | `1` por defecto cuando existe `DATABASE_URL`; `0` desactiva el procesador integrado |

**Mantén al menos una réplica activa y deshabilita el escalado a cero del endpoint.** El proceso en segundo plano no cuenta como una petición HTTP continua. Un endpoint suspendido no puede consultar la cola ni guardar nuevos resultados. Esto no requiere un Background Worker de Render, pero la GPU activa de Hugging Face sigue teniendo costo. No se creó ni contrató ningún recurso automáticamente.

Para Drive, cuando lo autorices en la web, añade también al endpoint `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` y el **mismo** `DRIVE_ENCRYPTION_SECRET` de Render. La autorización cifrada está en Supabase; el endpoint la lee y renueva el acceso. La URI de retorno sigue apuntando a la web de Render. Drive no es requisito para transcribir ni guardar los textos: sus tareas quedan bloqueadas hasta conectarlo. Los archivos pendientes siguen sujetos al límite de caché temporal y a posibles enlaces originales caducados.

Para desactivar solo la inferencia, usa `HF_TRANSCRIPTION_ENABLED=0` tanto en Render como en el endpoint; los jobs de transcripción quedan bloqueados y no se llama a los modelos.

El procesador arranca tras cargar los modelos, recupera tareas pendientes de Supabase y revisa la cola cada cinco segundos. Dar like y reintentar desde la web también envían una señal de activación autenticada con `{inputs: {action: "process_pending", schema_version: 1}}`. Su respuesta solo confirma aceptación, no finalización. Si no se confirma la señal, el favorito y sus tareas **ya permanecen guardados en Supabase**; el endpoint activo recupera la cola sin repetir el inicio de un Actor. La ficha refleja el estado y la transcripción cuando están disponibles.

Los jobs interrumpidos recuperan su lease después de 30 minutos. Las transcripciones ya guardadas no se vuelven a inferir al recuperar el mismo job. Los fallos de modelos, formato, saldo o descargas necesitan reintento explícito; no hay fallback pagado a Kie. Si reinicias el endpoint, su procesador vuelve a conectar la cola. Una caída o una petición interrumpida después de empezar inferencia puede requerir revisar los logs y el consumo antes de reintentar.

Se conserva el modo anterior: `HF_PROCESSING_MODE=worker` en Render usa el worker separado y las peticiones de video por API. Para ese modo, desactiva el procesador integrado con `HF_REMOTE_PROCESSING_ENABLED=0` o no configures `DATABASE_URL` en el endpoint. No necesitas cambiar el chat de Kie para usar Hugging Face.

## Flujo y límites

Like → descarga del MP4 → llamada al endpoint protegido → voz/hablantes/escenas en Supabase → visualización en Biblioteca → subida de videos y JSON a Drive.

En el modo directo a Supabase, la web solo envía la señal de activación; el endpoint lee la URL del video de la base, la valida y lo descarga desde una CDN admitida. El modo anterior de inferencia por API sigue aceptando MP4 en Base64 dentro de `inputs`, con `schema_version=1`; el token va solo en Authorization. El cliente admite únicamente URLs raíz HTTPS de `*.endpoints.huggingface.cloud` y no sigue redirecciones con credenciales. No sirve sustituir la URL por un endpoint de Whisper estándar: no produciría diarización y escenas.

El endpoint decodifica audio mono a 16 kHz, obtiene tiempos por palabra y asigna cada palabra a la voz con mayor solapamiento en los turnos de pyannote. Agrupa palabras consecutivas del mismo hablante. Los números de persona son etiquetas estables dentro de ese video, no identidades reales. Voces solapadas se etiquetan como tales; si no hay turno reconocible, se conserva «Sin identificar».

La diarización de audio **no determina si la persona habla en cámara o es VoiceOver**. Esos segmentos quedan con `role=unknown`, para no inventar una correspondencia entre voz y rostro. No se reconocen personas ni se infieren rasgos personales. Los modelos pueden equivocarse en palabras y voces; las transcripciones automáticas se guardan pendientes de revisión.

FFmpeg detecta cambios visuales con umbral 0.30 y también divide tomas largas. Se describen dos fotogramas por intervalo, hasta 24 intervalos por defecto, en español. Es análisis por muestreo: puede omitir acciones rápidas entre fotogramas. No se usa el texto transcrito para inventar las escenas. Un video sin audio sigue produciendo descripciones visuales.

Límites iniciales:

- MP4 de hasta **20 MiB**. `HF_MAX_VIDEO_BYTES` permite ajustarlo; usa el mismo límite en Render y en el endpoint y comprueba que el servicio acepte el tamaño del JSON resultante. Base64 aumenta el payload aproximadamente un tercio. No se comprime ni modifica tu video automáticamente.
- Hasta **180 segundos**, configurables con `HF_MAX_DURATION_SECONDS` en el endpoint.
- Máximo 200 segmentos por capa. Si faltan tiempos utilizables, falla el análisis en lugar de guardar tiempos inventados.
- Cliente con timeout de diez minutos y espera de arranque de hasta 60 segundos mediante `X-Scale-Up-Timeout`. El proveedor puede imponer límites más cortos. Si agota la espera, la inferencia puede continuar: revisa el endpoint antes de reintentar.
- Los videos y el audio intermedio del handler se almacenan en un directorio temporal eliminado al terminar. El video se envía a Hugging Face para procesarlo; revisa sus políticas de tratamiento y registros para tu cuenta.

Los tres modelos se cargan una vez por réplica; un lock procesa un video a la vez para limitar picos de memoria. El modo directo requiere una réplica activa y no admite escalado a cero para trabajo continuo; revisa cómo factura Hugging Face esa configuración. No se ha garantizado operación gratuita.

## Validación realizada

Las pruebas offline verifican autenticación, formato, límites, timestamps, alineación de hablantes, ventanas de escenas, guardado desde un proceso separado del endpoint, recuperación ante caídas de base de datos, Supabase/Drive simulados y ausencia de inferencias duplicadas por jobs ya guardados. Se resolvieron las dependencias mediante `pip install --dry-run --ignore-installed -r integrations/huggingface/requirements.txt`, sin instalar modelos en Render.

También se probó con un MP4 sintético real la decodificación, ausencia de audio, detección de un corte y extracción de imágenes; el modelo visual se simuló. **La carga de modelos y la inferencia GPU real no se han ejecutado.** Después de desplegar, valida un video corto con varias voces y cambios de escena y revisa los resultados en la ficha antes de procesar en lote.
