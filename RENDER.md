# Desplegar en Render

La web Flask y el backend se despliegan juntos. El archivo `render.yaml`
define un Web Service de plan Free, un worker y cuatro threads, con HTTPS
gestionado por Render. El plan gratuito puede suspender el servicio por
inactividad; revisa sus límites actuales en Render. Los archivos temporales del servidor no son almacenamiento permanente.
La biblioteca usa Supabase para datos y Google Drive para archivos: consulta
[la configuración de la biblioteca](docs/LIBRARY.md). La automatización puede ejecutarse dentro del endpoint de Hugging Face,
guardando directamente en Supabase, sin un Background Worker de Render. El
modo anterior de worker separado se conserva para Kie; Gunicorn atiende HTTP.

## Publicar

1. Sube los cambios de este repositorio a GitHub. Render solo recibe los
   archivos que hayas publicado, no los cambios locales pendientes.
2. En Render, elige **New → Blueprint**, conecta GitHub y selecciona
   `MANEL-LI-2026/LEADSICON---AUTOMATION` y la rama con estos cambios.
3. Revisa el servicio y el plan antes de crearlo. Render leerá `render.yaml`.
4. Configura `WEB_PASSWORD_HASH` con el hash de tu contraseña generado
   localmente. No introduzcas la contraseña sin procesar en ese campo:

   ```sh
   python -c 'from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass("Contraseña: ")))'
   ```

   Ejecuta el comando en un entorno con las dependencias instaladas.
   Guarda el hash en los secretos de Render; no lo publiques en GitHub.
   `WEB_SESSION_SECRET` se genera automáticamente y debe conservarse entre
   despliegues para mantener las sesiones.
   `WEB_USERNAME` define el usuario del login y está configurado como `leadsicon`.
5. Crea el servicio y espera a que termine el despliegue.
6. Abre la URL HTTPS que Render asigne: debe aparecer el login. Comprueba
   contraseña incorrecta, acceso correcto y cierre de sesión.

La web puede arrancar sin Apify. Para habilitar búsquedas, añade en la sección
**Environment** del servicio y aplica los cambios:

| Variable | Valor |
| --- | --- |
| `APIFY_TOKEN` | Token privado de tu cuenta de Apify |


No compartas el token ni la contraseña en el chat o en el repositorio.
Los dos Actors ya están fijados en el código (ver `APIFY.md`); la extracción real sigue pendiente. Cada ejecución
puede consumir crédito de Apify.

## Actualizaciones

Los despliegues automáticos están desactivados. Después de subir cambios a la
rama conectada, usa **Manual Deploy → Deploy latest commit** en Render.
Para cambiar la contraseña, genera otro hash y actualiza `WEB_PASSWORD_HASH`.
Para invalidar también todas las sesiones existentes, rota `WEB_SESSION_SECRET`.

Mantén `WEB_LOCAL_HTTP=0`, una sola instancia y un worker: el límite de intentos
de login se guarda en memoria y es global. Reiniciar el servicio reinicia ese
límite. Las cookies de sesión requieren HTTPS.

El health check consulta `/login`. Confirma que la aplicación responde, pero
no comprueba las credenciales ni la extracción de Apify. Para validar el
scraper, inicia una búsqueda con el input documentado del Actor elegido.

## Biblioteca persistente

Configura Supabase y OAuth de Google siguiendo [docs/LIBRARY.md](docs/LIBRARY.md).
Después del despliegue aparece **Biblioteca** en el menú. Sin esas credenciales
se muestra el estado pendiente; los datos no se guardan de forma permanente.
