# FocusFlow

FocusFlow es una aplicación de productividad personal construida con Python, Flask, SQLite, HTML, CSS y JavaScript. Incluye gestión de tareas, un temporizador de concentración, notas rápidas y un panel musical.

## Funciones

- Crear tareas con nombre, prioridad y fecha límite.
- Marcar tareas como completadas o pendientes y eliminarlas.
- Editar el nombre, la prioridad y la fecha de una tarea sin tener que volver a crearla.
- Ordenar las tareas pendientes por fecha límite.
- Mostrar avisos visuales para tareas que vencen hoy o están atrasadas.
- Buscar y filtrar tareas por estado o texto.
- Guardar tareas en una base de datos SQLite local.
- Temporizador de enfoque con bloques de 25, 15 y 5 minutos.
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

## FocusFlow Music

El panel consulta resultados mediante `ytmusicapi`, una biblioteca comunitaria que interactúa con una interfaz de YouTube Music que no es una API oficial estable. Por ello, la búsqueda puede dejar de funcionar si el servicio cambia o limita las solicitudes.

La reproducción integrada utiliza el reproductor oficial de YouTube. No todos los videos permiten reproducción fuera de YouTube; si el propietario bloquea la inserción o YouTube rechaza la reproducción, usa el enlace para abrir la canción en YouTube Music. Los controles de pausa y volumen solo pueden controlar la reproducción integrada que sí haya cargado.

FocusFlow no solicita la contraseña de Google ni intenta saltarse las restricciones de reproducción. No es una API propia de YouTube Music ni garantiza acceso a todas las funciones de una suscripción.

## Privacidad y almacenamiento

- Las tareas se guardan en el archivo local `focusflow.db`.
- Las notas rápidas y la colección de música se guardan en el almacenamiento local del navegador. En otro navegador o perfil no aparecerán automáticamente.
- No hay cuentas ni sincronización entre dispositivos implementadas actualmente.
- No publiques claves, contraseñas ni datos personales en el repositorio.

## Archivos principales

- `app.py`: aplicación Flask, base de datos, rutas de tareas y búsqueda musical.
- `templates/index.html`: estructura HTML/Jinja y componentes de la interfaz.
- `static/style.css`: diseño adaptable y estilos.
- `static/music.js`: búsqueda musical, colección guardada y reproductor.
- `requirements.txt`: dependencias de Python.
- `focusflow.db`: base de datos local creada al iniciar la aplicación.

## Limitaciones actuales

FocusFlow está pensado como proyecto local. Antes de publicarlo en internet habría que añadir protección CSRF para formularios, autenticación si se necesitan usuarios, configuración de producción de Flask y pruebas automatizadas. La música depende de servicios externos y puede tener restricciones por canción, navegador o región.
