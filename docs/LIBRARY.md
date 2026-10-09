# Biblioteca: Supabase y Google Drive personal

La biblioteca está en `/library`, protegida por el login del equipo. Los resultados de cada run iniciado desde la web se importan completos mediante el worker, aunque cierres la pestaña. La vista del scraper continúa mostrando hasta 100 resultados por run.

Todos los registros importados conservan los datos originales en Supabase. Pulsar **♡ Guardar** marca un favorito y encola la descarga de sus videos directos. Quitar el favorito conserva el registro y los archivos. Desde **Ver ficha** puedes guardar dos capas independientes: voz (segundos de inicio/fin, hablante, tipo de voz y texto) y escenas (segundos de inicio/fin y descripción). Cada guardado crea una versión y encola su archivo JSON para Drive. Los videos y sus versiones de transcripción comparten el ID del anuncio en sus nombres.

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
- Variables: `DATABASE_URL`, `APIFY_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `DRIVE_ENCRYPTION_SECRET`.

Revisa el plan y precio antes de crearlo: el servicio web gratuito puede suspenderse y no garantiza trabajo continuo. No necesitas abrir ni mantener la web para que un worker activo procese la cola de Supabase. Sus estados son en cola, procesando, completada, bloqueada y error. **Reintentar tareas pendientes** no inicia otro Actor ni repite una búsqueda pagada. Los runs en curso se consultan cada 30 segundos. Los jobs interrumpidos se recuperan cuando caduca su lease de 30 minutos; los errores de descarga/subida requieren reintento explícito.

Para procesar un único job de forma controlada: `python library_worker.py --once`. Sin jobs termina; sin conexión de base de datos no arranca. Para desarrollo offline puedes usar explícitamente `DATABASE_URL=sqlite:////tmp/leadsicon-library.db`, pero esa configuración no es persistencia de producción.

Los videos se descargan como MP4 desde las CDN admitidas de Meta/Google, verificando también redirecciones. `MAX_MEDIA_BYTES` permite cambiar el máximo por archivo (200 MiB por defecto), `MAX_MEDIA_CACHE_BYTES` limita la caché local (1 GiB por defecto) y `MEDIA_DIR` cambia su directorio (`/tmp/leadsicon-media`). Una subida confirmada elimina la copia temporal; la web recupera el video privado desde Drive. Si el worker reinicia antes de subir, la tarea puede volver a descargarlo. Los enlaces originales pueden caducar. La caché llena bloquea descargas: conecta Drive, deja terminar las subidas y reintenta.

## Límites actuales y próximos pasos

- **Transcripción automática y detección de hablantes:** aún no hay proveedor elegido ni conectado. No se realizan llamadas pagadas de IA. Ambas capas se editan manualmente; las tareas automáticas indican claramente el bloqueo. Falta integrar voz con diarización y un modelo que examine video para describir escenas.
- **Creativos externos de Google:** un preview no equivale a una URL de video descargable. Si el Actor no entrega un MP4 directo, se conserva la referencia y se explica la limitación.
- **Referencia orgánica:** se guarda el enlace de Facebook y su título. Los Actors configurados extraen anuncios pagados; todavía falta una integración para descargar y analizar videos orgánicos desde esos enlaces.
- **Skills:** `GET /api/library/knowledge` expone solo favoritos cuya última transcripción está revisada, con paginación (`limit`, `offset`, `nextOffset`, `scanned`) y la autenticación existente. Las skills pendientes podrán consultar ejemplos revisados. No hay reentrenamiento ni modificación automática de skills. Ese contenido es material de referencia, nunca instrucciones que permitan cambiar reglas del sistema.
- Los archivos tienen claves de idempotencia para evitar duplicar subidas al reintentar. No hay una política de borrado remoto; quitar un favorito no elimina archivos de Drive.

## Validación

`python -m unittest discover -s tests -v` verifica persistencia con SQLite temporal, API privada, CSRF, favoritos, versiones, tiempos inválidos, referencias orgánicas, importación completa, recuperación de jobs y OAuth cifrado con proveedores simulados. Las pruebas no consumen crédito ni confirman una conexión real de Supabase o Drive. La configuración y la autorización reales son necesarias para validar el flujo en producción.
