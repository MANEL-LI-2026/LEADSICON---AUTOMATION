# Chat UGC con Kie.ai

La sección `/chat` requiere el login de Leadsicon. Incluye selector de modelos,
historial de conversación, sugerencias y modos claro/oscuro. La clave permanece
en el servidor. Los mensajes y el historial se envían a Kie cuando pulsas Enviar.
La conversación se pierde al recargar; todavía no se importa el proyecto UGC
automáticamente ni se guardan conversaciones en una base de datos.

## Estado de la conexión

El adaptador implementa el contrato OpenAI-compatible: POST con autenticación
Bearer, `model`, `messages`, `stream: false`, y lectura de
`choices[0].message.content`. No implementa endpoints de tareas asíncronas,
la API nativa de Anthropic ni la API nativa de Gemini.

La documentación oficial es https://docs.kie.ai/. Su acceso desde el entorno
de desarrollo está bloqueado por la política de red. Las rutas y modelos
concretos aún deben verificarse en esa documentación. Las pruebas actuales
simulan el proveedor: no prueban una conexión real ni consumen crédito.

## Configurar en Render

En Environment del servicio, configura:

- `KIE_API_KEY`: clave privada de Kie. Nunca la pongas en GitHub o en el chat.
- `KIE_CHAT_MODELS`: lista JSON con los IDs exactos, nombres para mostrar y rutas
  HTTPS documentadas de chat OpenAI-compatible en `api.kie.ai`.

Esquema orientativo (los valores en mayúsculas son placeholders que debes reemplazar):

```json
[
  {
    "id": "ID_EXACTO_DEL_MODELO",
    "name": "NOMBRE_VISIBLE",
    "endpoint": "https://api.kie.ai/RUTA_DOCUMENTADA_DEL_MODELO"
  }
]
```

Crea una entrada por cada modelo disponible en tu cuenta, sea ChatGPT, Claude
o Gemini. No se presupone que una versión específica, como GPT 5.6, esté en
el catálogo. No copies la ruta de ejemplo como una ruta real.

Aplica las variables y despliega `main`. La web arranca sin estas variables,
pero el envío del chat permanece deshabilitado hasta configurar ambos campos.
Una configuración presente no demuestra que la clave y los modelos funcionen:
valida un mensaje corto con cada modelo y revisa el consumo en Kie.

## Límites y manejo de errores

Cada mensaje tiene un máximo de 6000 caracteres. Se envían hasta 19 mensajes
previos/incluyendo la pregunta, con un máximo de 24000 caracteres, conservando
pares completos. Los pares antiguos se excluyen cuando exceden esos límites.
Un cambio de modelo conserva el historial disponible.

No hay reintentos automáticos. La conexión tiene un timeout de 20 segundos y
no sigue redirecciones para evitar enviar la clave a otros destinos. Una
petición fallida o que agota la espera puede haber consumido crédito.

Antes de declarar la integración lista, hay que verificar los endpoints
oficiales, configurar una clave válida y completar una conversación real.
