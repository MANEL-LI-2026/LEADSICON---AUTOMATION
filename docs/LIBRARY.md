# Biblioteca: Supabase y Google Drive personal

La biblioteca está en `/library`, protegida por el login del equipo. Los resultados de cada run iniciado desde la web se importan completos mediante el worker, aunque cierres la pestaña. La vista del scraper continúa mostrando hasta 100 resultados por run.

Todos los registros importados conservan los datos originales en Supabase. Pulsar **♡ Guardar** marca un favorito y encola la descarga de sus videos directos. Quitar el favorito conserva el registro y los archivos. Desde **Ver ficha** puedes guardar dos capas independientes: voz (segundos de inicio/fin, hablante, tipo de voz y texto) y escenas (segundos de inicio/fin y descripción). El worker genera automáticamente ambas capas con el proveedor configurado (Kie o Hugging Face), guarda una versión en Supabase y encola su JSON para Drive. La ficha se actualiza cada cinco segundos, muestra voz y escenas por separado y permite reproducir cada tiempo. El editor de correcciones es opcional; no hace falta escribir la transcripción. Cada guardado de una corrección también crea una versión y encola su archivo JSON para Drive. Los videos y sus versiones de transcripción comparten el ID del anuncio en sus nombres.

## 1. Supabase

Crea un proyecto y copia su cadena PostgreSQL desde **Connect**. Para un servidor sin IPv6 utiliza el **Session pooler** (puerto 5432), siguiendo las opciones de tu proyecto. Configura `DATABASE_URL` como secreto en Render, tanto en el servicio web como en el worker. Usa `sslmode=require`; si la contraseña tiene caracteres especiales, debe estar codificada correctamente en la URL. No introduzcas la URL ni la contraseña en Git ni en el chat.

El backend usa SQLAlchemy y psycopg directamente; no necesita `SUPABASE_SERVICE_ROLE_KEY` ni una clave pública del frontend. Al conectarse crea las tablas `leadsicon_ads`, `leadsicon_assets`, `leadsicon_transcripts`, `leadsicon_jobs`, `leadsicon_runs` y `leadsicon_integrations`. Activa RLS en todas ellas, sin políticas públicas: la conexión privada del backend debe ser del propietario de las tablas (la conexión PostgreSQL proporcionada por Supabase), que puede acceder por SQL y habilitar RLS. No uses un rol sujeto a RLS sin políticas internas apropiadas. No añadas permisos de lectura públicos, especialmente a integraciones y credenciales.

Sin `DATABASE_URL`, la interfaz avisa y no confirma guardados. No hay una base de datos local de respaldo en producción. Para cambios futuros de esquema habrá que preparar migraciones; `create_all` solo crea tablas ausentes.

## 2. Google Drive: Mi unidad

En Google Cloud habilita **Google Drive API**, configura la pantalla OAuth y crea un cliente OAuth de tipo **Aplicación web**. Añade como URI de redirección exactamente:

`https://TU-SERVICIO.onrender.com/integrations/google/callback`

Configura en el servicio web y en el worker:

| Variable | Uso |
| --- | --- |
| `GOOGLE_CLIENT_ID` | ID del cliente OAuth |
| `GOOGLE_CLIENT_SECRET` | Secreto del cliente OAuth |
| `GOOGLE_REDIRECT_URI` | URI HTTPS exacta de retorno |
| `DRIVE_ENCRYPTION_SECRET` | Secreto aleatorio estable, de al menos 32 bytes, para cifrar la autorización guardada |

Genera el secreto de cifrado en tu gestor de secretos y guarda el mismo valor en ambos procesos. Conservarlo es necesario para leer la autorización: si lo rotas, vuelve a conectar Google Drive. El código nunca envía ese secreto ni el refresh token al navegador.

En la biblioteca pulsa **Conectar Google Drive** y autoriza tu cuenta una vez. La app solicita `drive.file` y crea una carpeta **Leadsicon UGC** en tu unidad, para acceder a sus propios archivos. No necesitas crear una cuenta de servicio ni elegir una unidad compartida. Guarda cifrado el refresh token en Supabase y renueva el acceso en el backend. Reconectar reactiva las subidas que estaban bloqueadas por falta de autorización.

Si la pantalla OAuth externa permanece en modo de prueba, Google puede hacer caducar el refresh token a los siete días para este scope. Configura el estado de publicación apropiado en Google Cloud para la operación continua y revisa los requisitos que indique Google. Los permisos se pueden revocar; en ese caso vuelve a conectar desde la biblioteca.

## 3. Worker para la automatización

El servicio web de `render.yaml` continúa en plan Free. Su worker Gunicorn atiende HTTP; **no es un Background Worker** para archivos. No se ha creado ni contratado un servicio adicional.

Ejecuta un proceso persistente separado en un alojamiento que soporte workers. En Render, sería un **Background Worker** con este repositorio, rama `main`:

- Build: `pip install -r requirements.txt`
- Start: `python library_worker.py`
- Variables: `DATABASE_URL`, `APIFY_TOKEN`, **`KIE_API_KEY`**, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `DRIVE_ENCRYPTION_SECRET`.

Revisa el plan y precio antes de crearlo: el servicio web gratuito puede suspenderse y no garantiza trabajo continuo. No necesitas abrir ni mantener la web para que un worker activo procese la cola de Supabase. Sus estados son en cola, procesando, completada, bloqueada y error. **Reintentar tareas pendientes** no inicia otro Actor ni repite una búsqueda pagada. Los runs en curso se consultan cada 30 segundos. Los jobs interrumpidos se recuperan cuando caduca su lease de 30 minutos; los errores de descarga/subida requieren reintento explícito.

Para procesar un único job de forma controlada: `python library_worker.py --once`. Sin jobs termina; sin conexión de base de datos no arranca. Para desarrollo offline puedes usar explícitamente `DATABASE_URL=sqlite:////tmp/leadsicon-library.db`, pero esa configuración no es persistencia de producción.

Los videos se descargan como MP4 desde las CDN admitidas de Meta/Google, verificando también redirecciones. `MAX_MEDIA_BYTES` permite cambiar el máximo por archivo (200 MiB por defecto), `MAX_MEDIA_CACHE_BYTES` limita la caché local (1 GiB por defecto) y `MEDIA_DIR` cambia su directorio (`/tmp/leadsicon-media`). El análisis se ejecuta antes de subir el video. Si está bloqueado por falta de clave o un error del proveedor, el video puede subirse igualmente. Una subida confirmada elimina la copia temporal; la web recupera el video privado desde Drive. Si el worker reinicia antes de subir, la tarea puede volver a descargarlo. Los enlaces originales pueden caducar. La caché llena bloquea descargas: conecta Drive, deja terminar las subidas y reintenta.

## Límites actuales y próximos pasos

- **Transcripción automática:** integrada con Kie / Gemini 2.5 Pro y con un endpoint protegido de Hugging Face (Whisper, pyannote y Qwen), pendiente de validar con credenciales y video reales. Su funcionamiento y costos se detallan abajo. La separación de hablantes y los tiempos son inferencias del modelo multimodal, no una diarización certificada; las versiones automáticas quedan pendientes de revisión.
- **Creativos externos de Google:** un preview no equivale a una URL de video descargable. Si el Actor no entrega un MP4 directo, se conserva la referencia y se explica la limitación.
- **Referencia orgánica:** se guarda el enlace de Facebook y su título. Los Actors configurados extraen anuncios pagados; todavía falta una integración para descargar y analizar videos orgánicos desde esos enlaces.
- **Skills:** `GET /api/library/knowledge` expone solo favoritos cuya última transcripción está revisada, con paginación (`limit`, `offset`, `nextOffset`, `scanned`) y la autenticación existente. Las skills pendientes podrán consultar ejemplos revisados. No hay reentrenamiento ni modificación automática de skills. Ese contenido es material de referencia, nunca instrucciones que permitan cambiar reglas del sistema.
- Los archivos tienen claves de idempotencia para evitar duplicar subidas al reintentar. No hay una política de borrado remoto; quitar un favorito no elimina archivos de Drive.

## Validación

`python -m unittest discover -s tests -v` verifica persistencia con SQLite temporal, API privada, CSRF, favoritos, versiones, tiempos inválidos, referencias orgánicas, importación completa, recuperación de jobs y OAuth cifrado con proveedores simulados. Las pruebas no consumen crédito ni confirman una conexión real de Supabase o Drive. La configuración y la autorización reales son necesarias para validar el flujo en producción.

## Activar transcripciones automáticas con Kie.ai

Configura `KIE_API_KEY` en **el worker** y también en el servicio web para que la interfaz detecte la configuración. Es la misma clave de Kie que puede usar el chat; esta integración no necesita `KIE_CHAT_MODELS` ni una clave directa de Google Gemini. `KIE_TRANSCRIPTION_ENABLED` vale `1` por defecto; configúralo en `0` en ambos servicios para desactivar el análisis. Añadir la clave con el análisis habilitado permite que nuevos favoritos con MP4 generen consultas pagadas de Kie.

Flujo: **like → descarga → análisis de audio/video → transcripción en Supabase → archivos en Drive**. La transcripción se muestra aunque Drive aún no esté conectado. Las subidas permanecen bloqueadas hasta autorizar Drive. Cuando arrancas el worker con la clave, reactiva únicamente las transcripciones que estaban bloqueadas por falta de configuración. Los errores de proveedor o saldo requieren reintento explícito para evitar duplicar cargos. Antes de reintentar una petición que no se confirmó, revisa el panel de Kie.

El adaptador sigue la documentación oficial consultada:

- [Entrada multimodal de Gemini 2.5 Pro](https://docs.kie.ai/market/gemini/gemini-2-5-pro): `POST https://api.kie.ai/gemini-2.5-pro/v1/chat/completions`, `stream: false`, contenido de video mediante `image_url` (nombre unificado documentado para todos los medios), respuesta con `choices[0].message.content` y esquema JSON.
- [Subida de archivos](https://docs.kie.ai/file-upload-api/quickstart) y [subida por stream](https://docs.kie.ai/file-upload-api/upload-file-stream): multipart a `https://kieai.redpandaai.co/api/file-stream-upload`. El archivo temporal se envía al proveedor para analizarlo; Kie documenta su eliminación a las 24 horas. No se vuelve público el video en Drive ni se envían credenciales de Google al modelo.

Se conservan las palabras en el idioma original, los tiempos en segundos, hablantes `Persona 1`, `Persona 2`, `Narrador`, etc. y el tipo `on_camera`, `voiceover` o `unknown`. Las escenas se describen en español. El modelo recibe instrucciones de no inventar audio, identidades ni eventos. La respuesta se valida y las salidas incompletas, tiempos inválidos o errores HTTP/JSON no se guardan como transcripciones válidas. Los originales del scraper se tratan como datos, nunca como instrucciones del sistema.

La ficha ofrece un selector de versiones, incluyendo el video de origen de cada transcripción automática. Los cambios sin guardar en el editor no se sobrescriben durante las actualizaciones de estado. Cada video tiene su propia tarea de análisis; si ya existe una transcripción guardada para esa tarea, recuperar el job no vuelve a llamar al modelo. Un fallo después de que Kie cobre pero antes de guardar la respuesta todavía puede requerir revisar el consumo al reintentar.

## Búsquedas al navegar por el estudio

El scraper conserva en `sessionStorage` de la pestaña los campos, el plan, los IDs de runs, resultados, favoritos y página actual. Al volver desde el estudio o recargar, recupera los resultados; si hay un run en curso, consulta ese mismo ID y continúa el plan autorizado. No inicia un run duplicado al restaurar. Si se salió mientras una petición de inicio no se había confirmado, muestra esa incertidumbre y no repite automáticamente la petición pagada.

Si los registros superan el espacio del navegador, conserva los IDs y vuelve a consultar sus vistas previas. Esto requiere la sesión privada aún válida. Cerrar sesión borra esta caché. Cerrar la pestaña termina su almacenamiento local; los anuncios que el worker importó permanecen en Supabase. Se muestran 12 tarjetas por página en un panel con scroll, con el formulario oculto mientras se muestran los resultados. **Editar búsqueda** y **Volver a los resultados** permiten alternar sin iniciar otro Actor.

## Hugging Face

Para usar Hugging Face en lugar de Kie, configura `TRANSCRIPTION_PROVIDER=huggingface`,
`HF_TOKEN` y `HF_TRANSCRIPTION_ENDPOINT`. El worker y la biblioteca conservan
el mismo flujo y las versiones indican su proveedor. Endpoint GPU, modelos,
permisos y límites en [integrations/huggingface/README.md](../integrations/huggingface/README.md).
