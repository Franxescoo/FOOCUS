# FOOCUS · Hoja de ruta de evolución

## Dirección del producto

FOOCUS evoluciona hacia un sistema de productividad inteligente y altamente personalizable. La aplicación debe adaptarse a los hábitos y preferencias de cada persona sin imponer una rutina.

**Principio de continuidad:** evolucionar, no reemplazar. Las tareas, el calendario, el plan semanal, las sesiones, el temporizador, las notas, las estadísticas y la exportación deben conservarse y ganar capacidades.

## Pilares

### Perfil adaptativo
- Procesamiento local de sesiones guardadas.
- Patrones de duración y periodos de actividad.
- Comparación entre estimaciones y tiempo real.
- Recomendaciones explicables, con un mínimo de datos antes de inferir patrones.
- Controles para activar o desactivar recomendaciones.

### Planificador de sugerencias
- Analizar tareas pendientes, prioridades, fechas límite y tiempo estimado restante.
- Respetar días disponibles, franjas horarias, capacidad diaria, sesiones y descansos.
- Crear propuestas sin modificar el calendario.
- Permitir aceptar, modificar o rechazar cada propuesta.
- Sincronizar las fechas aceptadas con el calendario actual.

### Personalización profunda
- Días y horarios de disponibilidad.
- Duración de sesiones y descansos.
- Capacidad diaria y horizonte de planificación.
- Acento de color y vista compacta.
- Visibilidad de módulos del panel principal.
- Futuro: perfiles independientes para universidad, trabajo y proyectos personales.

## Arquitectura y privacidad

- Mantener Python, Flask y SQLite como base local.
- Separar perfil, estadísticas y planificación en componentes comprobables.
- Mantener offline las funciones principales.
- No enviar datos de actividad a servicios externos.
- No reorganizar calendarios automáticamente sin aceptación.
- Aplicar cambios de base de datos aditivos y conservar tareas e historial existente.

## Criterios de lanzamiento

- Compatibilidad con tareas, calendario, sesiones y exportación existentes.
- Persistencia después de cerrar y abrir la aplicación.
- Validación de entradas y errores controlados.
- Pruebas del motor de planificación, fechas límite y disponibilidad.
- Verificación del instalador, actualizador y migración desde bases de datos anteriores.
- Changelog fiel a las funciones probadas.

## Secuencia de versiones propuesta

- V1.0.12: estabilidad y correcciones técnicas.
- V1.1.0+: evolución integrada hacia personalización, perfil adaptativo y planificación inteligente.

La V1.1.0+ será candidata a publicación después de revisión de código, CI satisfactoria y prueba manual de escritorio en Windows.
