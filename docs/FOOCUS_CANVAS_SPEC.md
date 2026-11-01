# FOOCUS Canvas — especificación técnica

**Estado:** especificación basada en auditoría del repositorio; pendiente de implementación.  
**Alcance:** Canvas libre y estructurado, tableros independientes y asociados a espacios de trabajo, uso local sin colaboración simultánea.

## 1. Auditoría de la arquitectura existente

La rama principal auditada corresponde al commit `21260038932a8d45b5d13c785b548e966044583e`, que contiene el merge del PR #25 (FOOCUS V1.1.0+).

### Stack y estructura comprobados

- Backend: Python con Flask. Las rutas actuales se concentran principalmente en `app.py`.
- Persistencia: SQLite, con la ruta configurable mediante `FOCUSFLOW_DATABASE`; por defecto se crea `focusflow.db` junto a `app.py`.
- Acceso a datos: `get_db()` abre una conexión por operación, activa claves foráneas y ejecuta commit/rollback al salir.
- Esquema/migraciones: `init_db()` crea tablas con `CREATE TABLE IF NOT EXISTS` y aplica cambios compatibles con bases existentes mediante comprobación de columnas y `ALTER TABLE`.
- Interfaz: Jinja en `templates/index.html`, estilos en `static/style.css` y `static/productivity.css`; hay JavaScript inline en la plantilla y lógica separada en `static/productivity.js`.
- Pruebas: `unittest` en `tests/test_app.py`; el repositorio cuenta con automatizaciones para pruebas y compilación de Windows.
- Distribución: aplicación local de escritorio/navegador; el README declara que es de un solo usuario y no incluye cuentas ni sincronización entre dispositivos.

### Datos que ya existen

| Tabla | Uso actual |
|---|---|
| `subjects` | Asignaturas. |
| `tasks` | Tareas globales. Incluye título, prioridad, fechas, estado, asignatura y tiempo estimado. |
| `task_study_days` | Días seleccionados para planificar tareas. |
| `work_sessions` | Sesiones de trabajo vinculadas a tareas globales. |
| `app_settings` | Preferencias locales, tema y perfil de productividad. |
| `planned_sessions` | Sesiones propuestas/aceptadas por el planificador. |

Actualmente **no existen** tablas de espacios de trabajo ni de Canvas. La interfaz tampoco tiene todavía una pantalla de Canvas. Por tanto, ambas capacidades son nuevas; no se deben describir como funciones existentes.

### Consecuencias para el diseño

1. Canvas debe agregarse de manera aditiva. No se reemplazan `tasks`, `task_study_days`, `work_sessions`, `planned_sessions` ni `app_settings`.
2. Las migraciones deben ser idempotentes y conservar instalaciones existentes.
3. Las tareas globales deben seguir teniendo una sola fuente de verdad: la tabla `tasks`.
4. Para mantener el estilo del proyecto, la primera implementación seguirá usando Flask, SQLite, Jinja, HTML, CSS y JavaScript. Se evitará incorporar un framework frontend nuevo en el MVP.
5. Las rutas nuevas se pueden mantener en un módulo Canvas separado y registrarse desde la aplicación existente. La lógica de dominio y validación no debe quedar mezclada con el JavaScript de la interfaz.
6. La carpeta de adjuntos debe vivir junto a los datos de la aplicación (derivada de `DATABASE.parent`), nunca dentro de `static/` ni de la carpeta del código fuente.

## 2. Decisiones de producto confirmadas

| Área | Decisión |
|---|---|
| Tipos | Canvas libre e integrado/estructurado. |
| Relación con espacios | Tableros independientes y tableros asociados a espacios de trabajo. |
| Navegación | Canvas tendrá una entrada propia en la navegación principal. Los espacios de trabajo también mostrarán sus tableros asociados. Ambos accesos abrirán el mismo tablero, sin copias. |
| Colaboración | Local y de un solo usuario. No se implementan cuentas, sincronización ni edición simultánea. |
| Guardado | Automático y manual. |
| Tareas | Tareas propias de Canvas y referencias a tareas globales existentes. |
| Adjuntos | Imágenes, archivos comunes y enlaces externos. |
| Historial | Deshacer/rehacer durante la sesión de edición y versiones persistentes consultables/restaurables. |

La posibilidad de colaboración futura no forma parte del alcance ni debe usarse para justificar complejidad adicional en esta versión.

## 3. Experiencia funcional

### 3.1 Administración de espacios y tableros

- Desde Canvas se puede consultar el listado de todos los tableros.
- Se puede crear un tablero independiente o dentro de un espacio de trabajo.
- Un tablero independiente puede asociarse o desasociarse posteriormente.
- Los espacios de trabajo agrupan tableros; no contienen copias de su contenido.
- Eliminar un espacio no debe borrar silenciosamente sus tableros: debe ofrecer conservarlos como independientes o cancelar la eliminación.
- Eliminar un tablero requiere confirmación y explica qué pasará con sus adjuntos locales.

### 3.2 Canvas libre

Lienzo desplazable y con zoom, con elementos que se pueden organizar libremente:

- Notas y bloques de texto.
- Tarjetas de tarea.
- Grupos visuales.
- Conexiones entre elementos.
- Imágenes, archivos y enlaces.
- Selección individual y múltiple, arrastre, redimensionado, duplicación y eliminación.
- Ajuste opcional a cuadrícula y acción para encuadrar todos los elementos.

Las conexiones pertenecen al tablero. Mover un elemento no debe romper ni desconectar sus conexiones.

### 3.3 Canvas estructurado

Tablero de columnas y tarjetas, con comportamiento tipo Kanban:

- Crear, renombrar, reordenar y eliminar columnas.
- Crear, editar, duplicar y mover tarjetas entre columnas.
- Las tarjetas admiten título, descripción/notas, prioridad, fecha, estado y subtareas.
- Antes de eliminar una columna con tarjetas, FOOCUS debe pedir reubicar las tarjetas o cancelar. Nunca debe borrarlas silenciosamente.

### 3.4 Tareas

Se distinguen dos clases:

**Tarea propia de Canvas**
- Vive únicamente en el tablero.
- Sus atributos se guardan en el elemento Canvas.
- No aparece automáticamente en el gestor global, calendario, planificador ni estadísticas globales.

**Tarea global vinculada**
- El elemento conserva una referencia al `tasks.id` existente.
- El gestor global `tasks` sigue siendo la fuente de verdad para título, prioridad, vencimiento, estado y tiempo estimado.
- Canvas refleja los datos actuales y permite abrir la tarea original.
- Modificar los datos globales desde Canvas llama a la lógica existente del gestor de tareas; no crea otra copia.
- Desvincular elimina la relación, no la tarea global.
- Convertir una tarea propia crea una tarea global una sola vez y conserva el elemento/notas de Canvas. La tabla actual `tasks` no tiene un campo de descripción; no se debe fingir que una descripción larga se sincroniza allí. Puede permanecer como contenido del elemento Canvas.

Si una tarea global se elimina fuera de Canvas, el elemento no debe desaparecer. La referencia se convierte en no disponible y el tablero conserva una copia de presentación mínima del último título/estado conocido para que el usuario pueda decidir si convertirla en tarea propia o eliminarla.

### 3.5 Calendario, planificador y concentración

- Las tareas globales vinculadas siguen participando en las funciones actuales.
- Las tareas propias de Canvas no se insertan en `tasks` ni en `planned_sessions` sin una conversión explícita.
- Desde una tarjeta vinculada se puede abrir la tarea y comenzar la sesión de concentración usando el flujo de trabajo existente.
- La fecha mostrada para una tarea global procede del gestor global; no debe haber fechas conflictivas almacenadas en dos lugares.

### 3.6 Archivos y enlaces

Tipos iniciales permitidos:
- Imágenes: PNG, JPG, JPEG y WebP.
- Documentos: PDF, TXT, MD, CSV, DOCX, XLSX y PPTX.
- Enlaces: URL HTTP o HTTPS.

No se permite ejecutar archivos ni interpretar HTML/JavaScript adjunto. Los ejecutables, scripts, instaladores y archivos HTML se rechazan en el MVP.

Los binarios se guardan fuera de SQLite en una carpeta local de datos por tablero; SQLite guarda metadatos, identificador y ruta relativa. Se validan extensión, MIME detectado y tamaño. El borrado de un elemento no elimina un adjunto mientras otra referencia lo use. Un enlace externo puede necesitar Internet para abrirse, pero el Canvas y los archivos locales deben funcionar offline.

## 4. Arquitectura propuesta

### Frontend

- Añadir la pantalla Canvas a la navegación principal de `templates/index.html`.
- La lista de espacios mostrará sus tableros asociados; la biblioteca Canvas mostrará todos los tableros.
- Separar el código nuevo en archivos propios, por ejemplo `static/canvas.js` y `static/canvas.css`.
- El Canvas libre usa elementos HTML posicionados sobre una superficie desplazable y una capa SVG para las conexiones; el modo estructurado usa HTML/CSS.
- El motor debe mantener un modelo de estado independiente del DOM para guardar, deshacer y exportar de forma consistente.
- El arrastre, redimensionado, zoom y desplazamiento trabajan con coordenadas del lienzo; las conexiones se recalculan a partir de las posiciones/dimensiones.

### Backend

- Mantener Flask y la base SQLite actual.
- Añadir un módulo de rutas/servicio Canvas que use la conexión y la configuración existentes sin abrir una segunda base de datos.
- Las operaciones que modifican varias tablas deben ejecutarse dentro de una transacción.
- Validar cada entrada en el backend aunque también exista validación en JavaScript.
- Aplicar protección CSRF a las operaciones de escritura siguiendo los endpoints actuales.
- Los errores de archivos deben ser explícitos y no bloquear la lectura del tablero.

### Persistencia propuesta

Las tablas principales ya están incorporadas de forma aditiva en la rama de Canvas. La descripción conserva los nombres del esquema implementado; cualquier cambio posterior deberá pasar por una migración compatible:

| Tabla nueva | Campos/propósito principal |
|---|---|
| `workspaces` | `id`, nombre, descripción opcional, color, fechas de creación/actualización. |
| `canvas_boards` | `id`, `workspace_id` nullable, título, modo, viewport y preferencias en JSON validado, fechas. |
| `canvas_elements` | `id`, `board_id`, tipo, x/y, ancho/alto, contenido JSON (incluye subtareas y miembros de grupos), `task_id` nullable, snapshot del título global, fechas. |
| `canvas_connections` | `id`, `board_id`, elemento origen/destino y estilo/metadatos. |
| `canvas_columns` | `id`, `board_id`, título y posición. |
| `canvas_attachments` | `id`, elemento/tablero, tipo, nombre, MIME, tamaño, ruta relativa o URL. |
| `canvas_history` | `id`, `board_id`, número de versión, descripción, snapshot serializado, fecha. |
Las preferencias y la vista se guardan en `preferences_json` y `viewport_json` de `canvas_boards`; no se creó una tabla `canvas_preferences` adicional.

Los grupos visuales del modo libre se modelan como elementos/contenedores dentro de `canvas_elements`, con referencias validadas a sus miembros; no requieren una tabla adicional. Las operaciones de deshacer/rehacer serán una pila en memoria durante la sesión de edición; el historial persistente se guardará en `canvas_history`. No se necesita una tabla de operaciones persistentes para satisfacer la decisión actual.

Restricciones recomendadas:
- FK de tablero a espacio con `ON DELETE SET NULL` después de confirmar la operación de eliminación del espacio.
- FK de elementos a tablero con `ON DELETE CASCADE`.
- FK de tarea global con `ON DELETE SET NULL`, conservando un snapshot de presentación.
- Las conexiones guardan claves textuales de origen/destino y el backend valida que ambos elementos pertenezcan al mismo tablero; no tienen FK SQL directas a esas claves.
- Índices por tablero, columna, tarea vinculada y fecha de versión.
- El contenido JSON se valida en el backend; queda pendiente añadir un campo explícito de versión de esquema para futuras migraciones.

### API interna propuesta

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/workspaces` | Listar espacios. |
| POST | `/api/workspaces` | Crear espacio. |
| PATCH | `/api/workspaces/{id}` | Editar espacio. |
| DELETE | `/api/workspaces/{id}` | Eliminarlo conservando sus tableros como independientes (`preserve_boards=true`). |
| GET | `/api/canvas` | Listar tableros visibles. |
| POST | `/api/canvas` | Crear tablero. |
| GET | `/api/canvas/{id}` | Obtener metadatos del tablero. |
| GET | `/api/canvas/{id}/content` | Obtener columnas, elementos y conexiones. |
| PUT | `/api/canvas/{id}` | Actualizar metadatos y relación del tablero. |
| DELETE | `/api/canvas/{id}` | Eliminar con confirmación (`confirm=true`) y limpiar sus adjuntos locales. |
| PUT | `/api/canvas/{id}/content` | Guardar contenido; `create_version=true` crea una versión manual. |
| GET | `/api/canvas/{id}/attachments` | Listar adjuntos del tablero. |
| POST | `/api/canvas/{id}/attachments` | Añadir archivo multipart o enlace HTTP/HTTPS. |
| DELETE | `/api/canvas/{id}/attachments/{attachment_id}` | Quitar un adjunto y eliminar su binario cuando ya no se referencia. |
| GET | `/api/canvas/{id}/attachments/{attachment_id}/download` | Abrir/descargar un archivo adjunto. |
| PUT | `/api/canvas/{id}/viewport` | Guardar posición y zoom de la vista libre. |
| POST | `/api/canvas/{id}/attachments` | Añadir archivo multipart o enlace HTTP/HTTPS. |
| DELETE | `/api/canvas/{id}/attachments/{attachment_id}` | Quitar un adjunto y limpiar su archivo local cuando ya no se referencia. |
| GET | `/api/canvas/{id}/attachments/{attachment_id}/download` | Abrir/descargar un archivo adjunto. |
| PUT | `/api/canvas/{id}/viewport` | Guardar posición y zoom de la vista libre. |
| GET | `/api/canvas/{id}/history` | Consultar versiones. |
| POST | `/api/canvas/{id}/history/{version_id}/restore` | Restaurar una versión como nueva versión. |
| GET | `/api/canvas/task-options` | Listar tareas globales disponibles para vincular. |
| PATCH | `/api/tasks/{task_id}` | Actualizar datos de la tarea global vinculada. |
| PUT | `/api/tasks/{task_id}/completion` | Actualizar el estado completado de una tarea global. |
| POST | `/api/canvas/{id}/elements/{element_key}/convert-task` | Convertir una tarjeta propia en tarea global (idempotente). |
| GET | `/api/canvas/task-options` | Listar tareas globales disponibles para vincular. |
| PUT | `/api/tasks/{task_id}/completion` | Actualizar el estado completado de una tarea global. |
| POST | `/api/canvas/{id}/elements/{element_key}/convert-task` | Convertir una tarjeta propia en tarea global (idempotente). |

La integración de tareas reutiliza el CRUD global existente; no se crea un segundo CRUD de tareas. La conversión crea un registro global una sola vez y conserva una única fuente de verdad. El editor libre usa elementos HTML posicionados con una capa SVG para conexiones; el modo estructurado usa tarjetas HTML/CSS.

Los adjuntos binarios se guardan junto a la base de datos, en `canvas_attachments`, nunca en `static/`. En el alcance actual: PNG, JPG/JPEG, WebP, PDF, TXT, MD, CSV, DOCX, XLSX y PPTX; tamaño máximo de 7 MB por archivo y 8 MB para la petición. Se valida el contenido según formato, se generan nombres locales aleatorios y se rechazan ejecutables, scripts y HTML. Los enlaces HTTP/HTTPS son referencias externas y pueden necesitar conexión para abrirse.

Los adjuntos binarios se guardan junto a la base de datos, en `canvas_attachments`, nunca en `static/`. En el alcance actual: PNG, JPG/JPEG, WebP, PDF, TXT, MD, CSV, DOCX, XLSX y PPTX; tamaño máximo de 7 MB por archivo y 8 MB para la petición. Se valida el contenido según formato, se generan nombres locales aleatorios y se rechazan ejecutables, scripts y HTML. Los enlaces HTTP/HTTPS son referencias externas y pueden necesitar conexión para abrirse.

## 5. Guardado e historial

### Guardado automático y manual

- Autosave tras 1 segundo sin nuevas modificaciones (intervalo inicial sujeto a prueba de rendimiento).
- Agrupar cambios consecutivos; no guardar cada movimiento del puntero.
- Mostrar estados visibles: cambios pendientes, guardando, guardado y error.
- Mantener el estado sucio si la escritura falla y permitir reintentar.
- Botón «Guardar ahora» fuerza la persistencia inmediata.
- El cierre intenta guardar cambios pendientes, pero la interfaz no debe declarar guardada una modificación que no recibió confirmación.
- SQLite debe confirmar de forma atómica cada lote de cambios.

### Deshacer/rehacer e historial persistente

- Undo/redo opera sobre acciones atómicas durante la sesión actual.
- Una nueva acción después de deshacer descarta la rama de redo.
- Se crea una versión persistente en guardados manuales explícitos, hitos o puntos automáticos espaciados si hubo cambios.
- No se crea una versión por cada movimiento del cursor.
- Restaurar una versión crea un nuevo estado/versionado y no borra versiones posteriores.
- Las versiones deben mostrar fecha/hora y una descripción útil.
- El límite de versiones debe ser configurable; nunca se borran archivos todavía referenciados por el estado actual o por una versión conservada.

## 6. Criterios de aceptación

Cada criterio debe verificarse con una prueba automatizada o un escenario manual reproducible. «Implementado» no equivale a «aceptado» hasta que la prueba pase.

### A. Espacios y tableros

| ID | Criterio |
|---|---|
| CAN-001 | Crear un tablero independiente. |
| CAN-002 | Crear un tablero asociado a un espacio de trabajo. |
| CAN-003 | Renombrar un tablero. |
| CAN-004 | Abrir y cerrar un tablero sin perder cambios guardados. |
| CAN-005 | Asociar posteriormente un tablero independiente a un espacio existente. |
| CAN-006 | Desvincular un tablero conservando su contenido. |
| CAN-007 | Eliminar un tablero solo después de una confirmación explícita. |
| CAN-008 | Al eliminar un espacio, ofrecer conservar sus tableros como independientes o cancelar; nunca borrarlos silenciosamente. |

### B. Canvas libre

| ID | Criterio |
|---|---|
| CAN-009 | Crear notas y bloques de texto. |
| CAN-010 | Mover elementos libremente. |
| CAN-011 | Redimensionar elementos. |
| CAN-012 | Desplazar el lienzo mediante arrastre. |
| CAN-013 | Acercar y alejar el lienzo. |
| CAN-014 | Seleccionar varios elementos. |
| CAN-015 | Crear grupos desde varios elementos seleccionados y mover el grupo junto con sus miembros. |
| CAN-016 | Crear conexiones entre dos elementos. |
| CAN-017 | Mantener las conexiones correctas al mover elementos. |
| CAN-018 | Duplicar elementos con identificadores nuevos; duplicar un grupo crea copias de sus miembros y conexiones internas. |
| CAN-019 | Encuadrar todos los elementos visibles en el lienzo. |

### C. Canvas estructurado

| ID | Criterio |
|---|---|
| CAN-020 | Crear columnas. |
| CAN-021 | Renombrar y reordenar columnas. |
| CAN-022 | Crear tarjetas. |
| CAN-023 | Mover tarjetas entre columnas. |
| CAN-024 | Editar los datos de una tarjeta, incluidas subtareas (hasta 40 por tarjeta). |
| CAN-025 | Establecer prioridad y fecha en una tarjeta. |
| CAN-026 | Al eliminar una columna con tarjetas, permitir reubicarlas o cancelar. |
| CAN-027 | Mantener los cambios después de cerrar y abrir FOOCUS. |

### D. Guardado y recuperación

| ID | Criterio |
|---|---|
| CAN-028 | Guardar automáticamente después del intervalo establecido sin nuevas modificaciones. |
| CAN-029 | Permitir guardar manualmente. |
| CAN-030 | Mostrar el estado real del guardado. |
| CAN-031 | No mostrar éxito si el backend rechaza o no confirma el guardado. |
| CAN-032 | Conservar cambios confirmados después de reiniciar FOOCUS. |
| CAN-033 | Agrupar cambios y evitar escrituras excesivas durante el arrastre. |
| CAN-034 | Mantener consistencia si falla una transacción de guardado. |

### E. Tareas e integración

| ID | Criterio |
|---|---|
| CAN-035 | Crear tareas propias de Canvas. |
| CAN-036 | Vincular tareas globales existentes. |
| CAN-037 | Reflejar cambios globales en la tarjeta vinculada. |
| CAN-038 | Editar una tarea vinculada actualiza el registro original. |
| CAN-039 | Desvincular una tarea sin eliminar el registro global. |
| CAN-040 | Convertir una tarea propia en tarea global sin crear duplicados. |
| CAN-041 | Mantener la integración de tareas globales con calendario y planificador. |
| CAN-042 | No incluir tareas propias en estadísticas/calendario globales salvo conversión explícita. |

### F. Archivos y enlaces

| ID | Criterio |
|---|---|
| CAN-043 | Adjuntar imágenes de los formatos permitidos. |
| CAN-044 | Adjuntar documentos de los formatos permitidos. |
| CAN-045 | Añadir enlaces HTTP/HTTPS válidos. |
| CAN-046 | Conservar adjuntos locales después de reiniciar FOOCUS. |
| CAN-047 | No borrar un archivo todavía referenciado. |
| CAN-048 | Rechazar formatos no permitidos y archivos que excedan el límite. |
| CAN-049 | No ejecutar ni interpretar contenido activo de adjuntos. |
| CAN-050 | Informar un adjunto ausente sin bloquear la apertura del tablero. |

### G. Historial

| ID | Criterio |
|---|---|
| CAN-051 | Deshacer la última operación compatible. |
| CAN-052 | Rehacer una operación deshecha. |
| CAN-053 | Una operación nueva después de deshacer descarta la rama de rehacer. |
| CAN-054 | Consultar versiones persistentes anteriores. |
| CAN-055 | Restaurar una versión histórica. |
| CAN-056 | Restaurar no elimina las versiones posteriores. |
| CAN-057 | Conservar historial después de reiniciar FOOCUS. |
| CAN-058 | Mostrar fecha/hora y descripción de cada versión. |

### H. Compatibilidad, seguridad y estabilidad

| ID | Criterio |
|---|---|
| CAN-059 | Las funciones actuales de FOOCUS siguen operativas. |
| CAN-060 | Los datos anteriores a Canvas se conservan. |
| CAN-061 | Canvas funciona offline para datos y adjuntos locales. |
| CAN-062 | Las migraciones son repetibles y no eliminan ni sobrescriben datos existentes. |
| CAN-063 | El instalador incluye frontend, backend y recursos de Canvas necesarios. |
| CAN-064 | Un tablero de tamaño de prueba documentado no bloquea permanentemente la interfaz. |
| CAN-065 | Los errores de validación, archivo y persistencia se registran y comunican de forma comprensible. |

## 7. Escenarios de prueba end-to-end

1. **Proyecto completo:** crear espacio, asociar Canvas, crear elementos y columnas, cerrar/abrir y comprobar identidad de datos.
2. **Tareas:** crear tarea Canvas, convertirla, modificarla desde el gestor global y comprobar que Canvas refleja el mismo registro; desvincular sin borrar.
3. **Recuperación:** autosave, guardado manual, undo/redo, reinicio, consultar y restaurar una versión.
4. **Adjuntos:** adjuntar imagen/PDF/enlace, duplicar elemento, borrar una referencia y comprobar que el fichero sigue disponible mientras exista otra referencia.
5. **Compatibilidad:** abrir base de datos anterior, ejecutar migración, comprobar tareas/asignaturas/sesiones/calendario/ajustes y crear un Canvas.

## 8. Estado de implementación en el PR de Canvas

Este estado describe el código incorporado en la rama `feature/foocus-canvas-foundation`; no significa que Canvas esté integrado en `main` ni que haya una versión estable publicada.

| Fase | Estado de código | Validación pendiente |
|---|---|---|
| 0. Auditoría y arquitectura | Completada. HTML posicionado + SVG para conexiones; HTML/CSS para tarjetas estructuradas. | Medición de rendimiento con tableros grandes y pulido visual. |
| 1. Datos, espacios y catálogo | Implementada: migraciones aditivas, espacios, tableros independientes/asociados y navegación desde Canvas/espacios. | Revisión visual en Windows. |
| 2. Canvas libre | Implementada en la rama: notas, texto, grupos con miembros, conexiones, selección múltiple, movimiento, redimensionado, duplicación, zoom, encuadre y viewport persistente. | Validación manual con tableros reales. |
| 3. Canvas estructurado | Implementada en la rama: columnas reordenables, tarjetas, subtareas, prioridades, fechas, estados y movimiento entre columnas. | Validación manual de flujos completos. |
| 4. Guardado e historial | Implementada en la rama: autosave, guardado manual, undo/redo en sesión, versiones persistentes y restauración. | Prueba manual de recuperación tras cierre inesperado. |
| 5. Tareas y adjuntos | Implementada en la rama: tareas propias/vinculadas, conversión idempotente a tarea global, archivos locales y enlaces externos. | Validación manual de formatos y sincronización de tareas. |
| 6. Estabilización e instalador | Pruebas automatizadas y compilación de Windows se ejecutan en GitHub Actions. | La validación final debe corresponder al último commit; falta instalar/probar manualmente en Windows. |

La rama continúa en un PR de borrador. No debe declararse Canvas listo para distribución hasta que las pruebas de Actions y la instalación manual en Windows pasen sobre el mismo commit final.

## 8. Fases de implementación

| Fase | Entrega | Salida verificable |
|---|---|---|
| 0 | Prototipo de motor y auditoría de datos | Decisión SVG/Canvas 2D sustentada por prueba de rendimiento. |
| 1 | Migraciones, espacios y catálogo de tableros | CAN-001 a CAN-008 y prueba de migración legacy. |
| 2 | Canvas libre | CAN-009 a CAN-019. |
| 3 | Canvas estructurado | CAN-020 a CAN-027. |
| 4 | Guardado e historial | CAN-028 a CAN-034 y CAN-051 a CAN-058. |
| 5 | Tareas y adjuntos | CAN-035 a CAN-050. |
| 6 | Estabilización e instalador | CAN-059 a CAN-065 y escenarios end-to-end. |

## 9. Definition of Done

Canvas no se considera terminado hasta que:
- Los criterios de aceptación correspondientes a la entrega pasan.
- La migración se prueba sobre una base antigua con datos y conserva todos los registros.
- La aplicación funciona offline para Canvas y sus adjuntos locales.
- La integración de tareas no duplica la fuente de verdad.
- Las pruebas automatizadas pasan.
- El flujo de compilación de Windows termina correctamente.
- El instalador se prueba manualmente en Windows.
- La documentación describe funciones reales y limitaciones.
- La integración a `main` se realiza mediante PR revisado; no se publica una versión estable automáticamente como parte de la especificación.
