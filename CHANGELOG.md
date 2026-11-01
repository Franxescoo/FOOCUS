# Registro de cambios de FOOCUS

Las publicaciones oficiales están disponibles en [GitHub Releases](https://github.com/Franxescoo/FOOCUS/releases). La V1.1.0+ se prepara en una rama de desarrollo y no se considera publicada hasta completar revisión, CI y pruebas manuales.

## En desarrollo — V1.1.0+

- **Evolución sin reemplazo:** conservar tareas, calendario mensual, plan semanal, sesiones, temporizador, notas, estadísticas y exportación.
- **Perfil adaptativo local:** calcular duración promedio de sesiones, periodos de actividad y diferencias entre estimaciones y tiempo real; ofrecer recomendaciones prudentes e indicar cuándo faltan datos.
- **Planificador inteligente:** generar propuestas locales a 7, 14, 21 o 30 días según prioridad, fecha límite, tiempo pendiente, días disponibles, horario preferido, duración de sesión, descansos y capacidad diaria.
- **Control del usuario:** las propuestas no alteran el calendario hasta ser aceptadas.
- **Replanificación asistida:** volver a calcular una distribución con el estado actual de las tareas y la disponibilidad, y sustituir el plan futuro solo cuando el usuario lo acepte.
- **Personalización profunda:** configurar días y horarios, sesiones, descansos, capacidad diaria, color de acento, vista compacta y módulos visibles del panel principal.
- **Integración del temporizador:** usar la duración preferida como bloque inicial y el descanso configurado en el aviso de finalización.
- **Correcciones:** confirmación de eliminación compatible con CSP, validación uniforme de fechas, respuestas 400 para JSON que no sea un objeto, actualización del día del calendario al cruzar medianoche y versión predeterminada corregida.
- **Persistencia conservadora:** añadir una tabla para sesiones planificadas y guardar preferencias en `app_settings`, sin recrear tareas ni eliminar historial anterior.

No crear una Release ni un tag estable hasta revisar el pull request, completar las pruebas de CI y probar manualmente el instalador de Windows y la actualización desde una instalación existente.
