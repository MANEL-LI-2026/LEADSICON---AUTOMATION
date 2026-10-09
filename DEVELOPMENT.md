# Scraper de anuncios con Apify

CLI inicial para ejecutar Actors de Facebook y YouTube y exportar sus datasets.
Requiere Python 3.10 o superior, sin paquetes adicionales.

## Web privada

La pantalla principal (`/`) es el mockup interactivo de **UGC Studio**:
idea escrita o referencia, concepto, guion, variantes y hoja de ruta.
El scraper de anuncios permanece en `/ads`. Ambas pantallas requieren login.

El mockup permite edición manual, conservar exactamente el texto original,
combinar personas/locaciones/formatos (hasta 100 variantes) y exportar el brief
en JSON. Incluye un ejemplo editable y un borrador guardado en `sessionStorage`,
solo en la pestaña actual. No existe almacenamiento compartido de proyectos.
La transcripción contextual, el chat de edición, la generación de guiones,
la revisión de viralidad y la producción de videos con IA siguen pendientes.

La web usa Flask y requiere las dependencias de `requirements.txt`:

```sh
python3 -m venv /workspace/.venvs/leadsicon
/workspace/.venvs/leadsicon/bin/pip install -r requirements.txt
```

Configura `WEB_SESSION_SECRET` con un secreto aleatorio de al menos 32 bytes
y `WEB_PASSWORD_HASH` con el hash de la contraseña compartida. Genera el hash
localmente, con entrada oculta, y guárdalo en los secretos del alojamiento:

```sh
/workspace/.venvs/leadsicon/bin/python -c 'from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass("Contraseña: ")))'
```

No guardes la contraseña ni estos secretos en Git. El servidor no arranca si
faltan los secretos de acceso. `APIFY_TOKEN` y los Actors permanecen en el servidor.

Arranque en producción, detrás del HTTPS del proveedor:

```sh
/workspace/.venvs/leadsicon/bin/gunicorn --workers 1 --threads 4 --bind 0.0.0.0:8000 'web:create_app()'
```

La limitación de login (10 intentos por cinco minutos) es global y en memoria;
usa una sola instancia y un worker. Para varias instancias será necesario
un limitador compartido. Las sesiones duran ocho horas. Cerrar sesión elimina
la cookie del navegador; cambiar el secreto de sesión invalida todas las sesiones.

Solo para pruebas locales por HTTP: configura `WEB_LOCAL_HTTP=1` y arranca
en `127.0.0.1:8000`. No uses esa opción en una web pública. En producción las
cookies exigen HTTPS. GitHub Pages no ejecuta este backend ni protege el contenido
con contraseña: despliega la web completa en un proveedor con soporte para Python.

La interfaz genera el input del Actor desde keywords o anunciantes y permite
ver/descargar hasta 100 registros por run. Las búsquedas siguen activas en Apify aunque
cierres la página; no se cancelan automáticamente.

Pruebas de la CLI y de la web:

```sh
/workspace/.venvs/leadsicon/bin/python -m unittest discover -s tests -v
```

## Configuración

Configura `APIFY_TOKEN` de forma segura en el entorno, sin guardarlo en Git.
Los Actors de Meta y Google están fijados en `ad_inputs.py`; consulta `APIFY.md`. El programa lee variables del proceso;
no carga archivos `.env` automáticamente.

Los Actors seleccionados obtienen anuncios de Meta Ad Library y Google Ads
Transparency Center, filtrando YouTube para las búsquedas de esa plataforma.

## Uso

Crea un archivo JSON con el input documentado por el Actor concreto y ejecuta:

```sh
python3 scraper.py facebook --input /ruta/facebook-input.json
python3 scraper.py youtube --input /ruta/youtube-input.json
```

Cada ejecución inicia un Actor y puede consumir crédito de Apify. El timeout
local no cancela el Actor: revisa su run en Apify antes de repetir una ejecución
que haya agotado el tiempo de espera o perdido la conexión.

El resultado se guarda en `output/<plataforma>-<run-id>.json`, con los registros
originales del Actor. `--output` permite elegir otro archivo, que no debe existir.
`--timeout` ajusta la espera en segundos (600 por defecto).

## Validación

```sh
python3 -m unittest discover -s tests -v
python3 scraper.py --help
```

Las pruebas simulan Apify: no consumen crédito ni verifican Actors reales.
Los inputs de los Actors seleccionados se validaron contra sus esquemas publicados.
Pendiente: una extracción real con un token válido antes de afirmar que funciona.

## Biblioteca de anuncios

Favoritos, transcripciones de voz/escenas versionadas y cola de archivos están
en `/library`. Configuración de Supabase, OAuth de Drive personal y worker en
[docs/LIBRARY.md](docs/LIBRARY.md). La transcripción automática está integrada con Kie / Gemini 2.5 Pro y requiere
`KIE_API_KEY` en el worker; las pruebas simulan el proveedor. La extracción
orgánica sigue pendiente. La interfaz conserva búsquedas en la pestaña y ofrece
resultados paginados, seguimiento animado y superficies glass en la paleta original.

Prueba de navegador offline (requiere Node, Playwright y Chromium en
`/usr/bin/chromium`):

```sh
/workspace/.venvs/leadsicon/bin/python tests/browser/run_scraper.py
```

Arranca y detiene su propio servidor de prueba en `127.0.0.1:5094` con SQLite
temporal y credenciales ficticias. Simula Apify: no inicia Actors reales.
Verifica restauración de búsqueda en curso al navegar, paginación, ausencia de
runs duplicados, favoritos, transcripciones, correcciones y modos claro/oscuro
en móvil. Guarda capturas en `/tmp/leadsicon-search-*.png`.

Hugging Face está disponible como proveedor de transcripción, diarización y
descripciones visuales mediante un endpoint GPU protegido. Guía y handler en
[integrations/huggingface/README.md](integrations/huggingface/README.md). Sus
dependencias están separadas: no se instalan en el backend de Render.

El modo `HF_PROCESSING_MODE=remote` permite procesar dentro del endpoint de
Hugging Face y guardar directamente en la misma Supabase, sin Background Worker
de Render. El endpoint debe mantener una réplica activa y recibir su conexión
privada de base de datos. La guía y `build_bundle.py` incluyen el paquete
completo; los modelos GPU reales siguen pendientes de validación.
