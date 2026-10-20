# FocusFlow · Hoja de ruta técnica

Este documento distingue entre las funciones que existen hoy y las decisiones que conviene tomar antes de convertir FocusFlow en una aplicación multiusuario o desplegada en internet.

## Estado actual

FocusFlow es una aplicación **local y de un solo usuario** construida con Flask, SQLite, Jinja, CSS y JavaScript.

- Las tareas, sesiones de trabajo y la meta diaria se guardan en SQLite.
- Las notas rápidas, la colección musical, el tema y el contador del temporizador se guardan en el navegador.
- Las sesiones activas tienen un inicio registrado y solo se consolidan en el historial cuando se terminan y guardan.
- La búsqueda musical usa una biblioteca no oficial; depende de cambios externos y no debe considerarse un servicio garantizado.
- No existen cuentas de usuario, sincronización entre dispositivos, permisos ni aislamiento de datos por persona.

## Prioridades recomendadas

### 1. Consolidar la experiencia local

- Mantener las métricas principales visibles y sin sobrecargar la pantalla.
- Mantener asignaturas, estimaciones, filtro y resumen de carga de estudio cubiertos por pruebas.
- Probar creación, edición, cierre y eliminación de tareas con fechas límite.
- Probar sesiones activas, recargas, errores de red y sesiones que quedan abiertas.
- Añadir pruebas de regresión para las estadísticas, la meta diaria y la exportación.
- Seguir manteniendo controles de accesibilidad, modo oscuro, diseño móvil y movimiento reducido.

### 2. Evolucionar el modelo académico

**Ya implementado:** tabla normalizada de asignaturas, tareas vinculadas mediante `subject_id`, tiempo estimado por tarea, comparación con tiempo real, filtro por asignatura y resumen de carga pendiente. `init_db()` detecta columnas ausentes y las añade sin recrear la tabla ni borrar tareas existentes.

Siguientes mejoras recomendadas:
- Introducir migraciones versionadas para que futuras modificaciones se puedan auditar, probar y revertir con seguridad.
- Añadir semestres o periodos académicos y permitir archivar asignaturas antiguas.
- Desarrollar una planificación semanal con bloques de estudio y fecha objetivo, basada en la estimación pendiente.
- Registrar una breve revisión al cerrar una sesión: qué se avanzó y cuál es el siguiente paso.
- Comparar estimaciones y tiempos reales en un informe semanal para ajustar futuras estimaciones.

La migración actual es aditiva y conservadora, pero no sustituye una herramienta de migraciones versionadas antes de introducir cambios de esquema más complejos.

### 3. Separar la lógica del servidor

Cuando app.py empiece a crecer, mover responsabilidades a módulos con límites claros:
- db.py: conexión, transacciones y migraciones.
- repositories/: consultas SQL.
- services/: reglas para tareas, sesiones, metas y reportes.
- routes/: controladores HTTP y validación de entradas.

No hace falta convertir un proyecto pequeño en una arquitectura compleja antes de tiempo. Hacer esta separación cuando sea posible probar cada módulo de manera independiente.

### 4. Antes de añadir cuentas o desplegar en internet

No publicar esta versión directamente como servicio multiusuario. Primero:
- Implementar autenticación y autorización en todas las operaciones.
- Asociar cada tarea, sesión y preferencia a un user_id.
- Migrar de SQLite a una base de datos de servidor si la concurrencia lo requiere.
- Configurar una clave secreta persistente desde variables de entorno.
- Usar un servidor WSGI de producción, HTTPS, límites de solicitudes y registros sin datos privados.
- Definir copias de seguridad, restauración, exportación y eliminación de datos.
- Revisar la protección CSRF, encabezados de seguridad, cookies y pruebas de acceso entre usuarios.

El token CSRF actual protege las solicitudes que cambian datos, pero **no reemplaza autenticación ni autorización**. Sin cuentas, cualquier persona que pueda acceder a la instancia local tiene acceso a la misma lista.

### 5. Integraciones con criterio

- Mantener la exportación CSV con protección ante fórmulas de hojas de cálculo.
- Para notificaciones, comenzar con recordatorios locales y permisos explícitos.
- Para calendarios, evaluar importación/exportación estándar antes de conectar servicios privados.
- Para música, encapsular la búsqueda detrás de un adaptador intercambiable y documentar que ytmusicapi no es una API oficial estable.
- Para sincronización, diseñar primero propiedad de datos, conflictos y resolución offline; no sincronizar archivos SQLite compartidos directamente.

## Criterio para aceptar nuevas funciones

Una función nueva debería cumplir al menos uno de estos objetivos: ahorrar pasos, mejorar el seguimiento del estudio, reducir errores, aumentar la accesibilidad o preparar una necesidad real de crecimiento. Evitar añadir widgets que solo decoren la pantalla o dupliquen datos que ya existen.
