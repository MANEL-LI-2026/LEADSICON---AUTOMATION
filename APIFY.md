# Actors seleccionados

Los IDs están configurados en el backend y en la CLI; no necesitas introducirlos
en Render. Solo configura `APIFY_TOKEN` en **Environment** del Web Service.
La clave permanece en el servidor.

| Plataforma | Actor | ID |
| --- | --- | --- |
| Facebook | apify/facebook-ads-scraper | JJghSZmShuco4j9gJ |
| YouTube | solidcode/ads-transparency-scraper | iRsL8PTQjmWC1SaPQ |

Se verificaron los README y esquemas de los builds `latest` publicados:
Meta `0.0.387`, Google `1.0.27`. El arranque usa el build predeterminado del
Actor. Los proveedores pueden actualizarlo; revisa los esquemas si cambian.

## Búsqueda desde la web

1. Elige Facebook o YouTube y el preset **Pago**.
2. Edita las keywords, una por línea, o elige **Anunciante / página**.
3. Elige país y límite de resultados por búsqueda (10 por defecto, máximo 100).
4. Usa **Ver inputs del Actor** para revisar el plan sin consumir crédito.
5. Pulsa **Buscar anuncios** para iniciar las ejecuciones.

Los presets pagos son Cheap Insurance, Auto Insurance, Low Car Insurance Rates
y Lower your rate. Estados Unidos es el país predeterminado; puedes cambiarlo
o seleccionar todos los países.

Meta recibe `startUrls` con URLs de búsqueda de Ad Library, una por keyword,
y `resultsLimit` por URL. Para anunciantes recibe URLs de páginas de Facebook
o de Meta Ad Library. La búsqueda por keyword filtra anuncios activos en Facebook;
las URLs proporcionadas por el usuario conservan sus filtros.
El enriquecimiento de e-commerce queda desactivado.

Google recibe `searchQuery`, `maxResults`, `region` y `platform: "youtube"`.
El Actor acepta una consulta por run: la web ejecuta secuencialmente un run por
keyword, dominio, nombre o ID de anunciante. Una keyword busca anunciantes
coincidentes; no necesariamente busca texto dentro de cada anuncio.

Máximo 10 consultas por envío. El límite de resultados se aplica por consulta,
no a toda la tanda. La vista previa muestra hasta 100 registros por run; puede
contener anuncios repetidos entre consultas. La descarga incluye los registros
mostrados, sin alterar su formato original.

Los resultados se muestran como tarjetas con anunciante, texto, fechas y enlaces.
Meta puede incluir imágenes o videos reproducibles. Algunos creativos de Google
solo incluyen un `previewUrl` externo: se abre con un enlace y no se ejecuta su
script dentro de la web. Cuando faltan assets o sus URLs dejan de funcionar,
la tarjeta muestra una indicación y conserva el enlace al anuncio si existe.
El botón Descargar JSON sigue exportando los registros originales.

Los Actors son de anuncios pagados. Los hashtags orgánicos se conservan en la
interfaz, pero su ejecución queda deshabilitada hasta elegir un Actor compatible.

## Configurar el token

Obtén un token en Apify Console → Settings → Integrations → API tokens.
En Render → servicio → Environment, configura `APIFY_TOKEN` y aplica los cambios.
No publiques el token en GitHub ni en el chat.

Una variable presente no garantiza autenticación válida ni saldo suficiente.
Las pruebas actuales validan inputs y simulan ejecuciones; no se ha hecho una
extracción real con estos Actors. Cada ejecución puede consumir crédito.

Si falla una tanda, se detienen las consultas restantes y se conservan los
resultados ya obtenidos. Si se agota la espera, se cierra la página o se pierde
la conexión, el run remoto puede continuar. Revisa Apify antes de repetir.
