# FocusFlow

FocusFlow es una aplicación de productividad personal construida con Python, Flask, SQLite, HTML, CSS y JavaScript. Incluye gestión de tareas, un temporizador de concentración, notas rápidas y un panel musical.

## Funciones

- Crear tareas con nombre, prioridad y fecha límite.
- Marcar tareas como completadas o pendientes y eliminarlas.
- Editar el nombre, la prioridad y la fecha de una tarea sin tener que volver a crearla.
- Ordenar las tareas pendientes por fecha límite.
- Mostrar avisos visuales para tareas que vencen hoy o están atrasadas.
- Buscar y filtrar tareas por estado o texto.
- Exportar tareas y sesiones de trabajo a CSV para abrirlas en Excel u otra hoja de cálculo.
- Guardar tareas en una base de datos SQLite local.
- Temporizador de enfoque con bloques de 25, 15 y 5 minutos.
- Alternancia entre modo claro y oscuro, con preferencia guardada en el navegador.
- Sistema anti-procrastinación para elegir una tarea pendiente según prioridad y fecha límite, definir un primer paso de cinco minutos e iniciar el temporizador y el registro de trabajo desde el mismo panel.
- Contador diario de sesiones de concentración.
- Notas rápidas guardadas en el almacenamiento local del navegador.
- FocusFlow Music: búsqueda de canciones con `ytmusicapi`, colección de canciones guardadas y controles para el reproductor integrado de YouTube cuando el video admite reproducción incrustada.

## Requisitos

- Python 3.10 o posterior.
- Conexión a internet para la búsqueda musical y el reproductor de YouTube.
- Navegador actualizado.

## Ejecutar en Windows

1. Abre la carpeta del repositorio en VS Code.
2. Abre **Terminal > Nueva terminal**.
3. (Recomendado) crea y activa un entorno virtual:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

4. Instala las dependencias:

   ```bash
   python -m pip install -r requirements.txt
   ```

5. Inicia la aplicación:

   ```bash
   python app.py
   ```

6. Abre http://127.0.0.1:5000 en el navegador.

La base de datos `focusflow.db` se crea automáticamente junto a `app.py`. Mantén la aplicación en ejecución mientras la uses.


## Seguimiento del trabajo por tarea

- Cada tarea tiene el botón **Empezar a trabajar**. FocusFlow inicia una sesión y muestra un cronómetro que sigue contando aunque recargues la página.
- Solo se permite una sesión activa a la vez para evitar contabilizar dos tareas simultáneamente.
- Al pulsar **Terminar y guardar**, puedes escribir un comentario con lo que avanzaste. Se guardan la hora de inicio, la hora de término, la duración y el comentario en SQLite.
- **Ver sesiones** muestra el historial reciente de tiempo y notas de esa tarea.
- Cada tarea muestra el tiempo total registrado y una racha de días consecutivos en los que guardaste al menos una sesión.
- El panel de actividad representa los últimos 35 días con un mapa de intensidad inspirado en el calendario de contribuciones de GitHub. Es actividad de FocusFlow, no datos conectados a GitHub.
- Las estadísticas se calculan con las sesiones que se han terminado y guardado. Si cierras el navegador con una sesión activa, vuelve a abrir la aplicación para retomarla y finalizarla.

Las sesiones se almacenan en la tabla local `work_sessions` dentro de `focusflow.db`. No se necesita instalar una dependencia adicional para esta función.

## FocusFlow Music

El panel consulta resultados mediante `ytmusicapi`, una biblioteca comunitaria que interactúa con una interfaz de YouTube Music que no es una API oficial estable. Por ello, la búsqueda puede dejar de funcionar si el servicio cambia o limita las solicitudes.

La reproducción integrada utiliza el reproductor oficial de YouTube. No todos los videos permiten reproducción fuera de YouTube; si el propietario bloquea la inserción o YouTube rechaza la reproducción, usa el enlace para abrir la canción en YouTube Music. Los controles de pausa y volumen solo pueden controlar la reproducción integrada que sí haya cargado.

FocusFlow no solicita la contraseña de Google ni intenta saltarse las restricciones de reproducción. No es una API propia de YouTube Music ni garantiza acceso a todas las funciones de una suscripción.

## Privacidad y almacenamiento

- Las tareas se guardan en el archivo local `focusflow.db`.
- Las notas rápidas, la colección de música, el tema visual y el primer paso del sistema anti-procrastinación se guardan en el almacenamiento local del navegador. En otro navegador o perfil no aparecerán automáticamente.
- No hay cuentas ni sincronización entre dispositivos implementadas actualmente.
- No publiques claves, contraseñas ni datos personales en el repositorio.

## Archivos principales

- `app.py`: aplicación Flask, base de datos, rutas de tareas, exportación CSV y búsqueda musical.
- `templates/index.html`: estructura HTML/Jinja y componentes de la interfaz.
- `static/style.css`: diseño adaptable, temas claro/oscuro y estilos.
- `static/music.js`: búsqueda musical, colección guardada y reproductor.
- `requirements.txt`: dependencias de Python.
- `focusflow.db`: base de datos local creada al iniciar la aplicación.

## Limitaciones actuales

FocusFlow está pensado como proyecto local. Antes de publicarlo en internet habría que añadir protección CSRF para formularios, autenticación si se necesitan usuarios, configuración de producción de Flask y pruebas automatizadas. La música depende de servicios externos y puede tener restricciones por canción, navegador o región.
