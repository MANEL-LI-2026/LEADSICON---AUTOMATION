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

La interfaz permite enviar el input JSON del Actor y ver/descargar hasta 100
registros. Los formularios específicos por palabra clave y anunciante dependen
de elegir y verificar los Actors. Las búsquedas siguen activas en Apify aunque
cierres la página; no se cancelan automáticamente.

Pruebas de la CLI y de la web:

```sh
/workspace/.venvs/leadsicon/bin/python -m unittest discover -s tests -v
```

## Configuración

Configura `APIFY_TOKEN` de forma segura en el entorno, sin guardarlo en Git.
Configura `APIFY_FACEBOOK_ACTOR` y `APIFY_YOUTUBE_ACTOR` con los IDs o nombres
`usuario/actor` de los Actors elegidos. El programa lee variables del proceso;
no carga archivos `.env` automáticamente.

Los Actors deben obtener anuncios de Meta Ads Library y anuncios de YouTube
desde una fuente compatible, por ejemplo Google Ads Transparency Center.
Hay que comprobar la cobertura del Actor: un scraper de videos de YouTube
no necesariamente obtiene anuncios pagados.

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
Pendiente: elegir los Actors, validar sus inputs y hacer una ejecución real
antes de afirmar que la extracción de anuncios funciona.
