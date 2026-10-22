# Registro de cambios de FOOCUS

Las publicaciones oficiales están disponibles en [GitHub Releases](https://github.com/Franxescoo/FOOCUS/releases). Los cambios de la sección «Próxima versión» todavía no están publicados.

## Publicado — V1.0.10

- Preferencia de tema claro/oscuro persistente.
- Logo FOOCUS en el encabezado, favicon, ejecutable de Windows e instalador.
- Estadísticas de productividad y mejoras de presentación del actualizador.
- Mejoras visuales y de adaptación a ventanas estrechas.

## Próxima versión planificada — objetivo V1.0.11

- **Navegación:** barra lateral izquierda con pantallas independientes para Inicio, Calendario, Tareas, Concentración y Estadísticas.
- **Calendario mensual:** cuadrícula de días cuadrados, navegación entre meses, distinción visual de hoy, fechas elegidas y fecha límite.
- **Planificación flexible:** elegir varios días de estudio para una tarea y guardarlos en SQLite para conservarlos al reiniciar.
- **Respeto de la fecha límite:** bloquear días posteriores al vencimiento y validar la regla también en el servidor. Al adelantar un límite, se eliminan las sesiones planificadas que quedarían fuera del plazo.
- **Integración:** mantener el resumen semanal sincronizado con las selecciones del calendario y enlazarlo con el inicio de sesiones de concentración.
- **Diseño:** interfaz ligeramente más amplia y nítida, mejor contraste, navegación accesible y celdas cuadradas adaptables a pantallas pequeñas.
- **Pruebas:** cubrir la persistencia de múltiples días, el rechazo de fechas no válidas, los cambios en la fecha límite, la limpieza de planes vencidos y la navegación.

La V1.0.11 es solo el objetivo de planificación. No publicar ni etiquetar una versión oficial hasta revisar la interfaz y completar las validaciones de CI y la prueba manual de Windows.
