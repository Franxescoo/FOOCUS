# FocusFlow

FocusFlow es una aplicación de productividad personal construida con Python, Flask y SQLite. Permite gestionar tareas y ofrece una sección musical propia conectada a servicios de YouTube.

## Funciones
- Crear tareas con prioridad y fecha límite.
- Marcar tareas como completadas y eliminarlas.
- Guardar tareas localmente en SQLite.
- Ver un resumen de tareas totales y completadas.
- FocusFlow Music: buscar videos musicales con YouTube Data API v3 y reproducir videos compatibles con el reproductor oficial de YouTube.
- Abrir búsquedas directamente en YouTube Music.

## Ejecutar en Windows
1. Abre la carpeta FocusFlow en VS Code.
2. Abre **Terminal > Nueva terminal**.
3. Instala la dependencia:

   ```bash
   pip install -r requirements.txt
   ```

4. (Opcional) Configura la variable de entorno `YOUTUBE_API_KEY` con una clave de YouTube Data API v3 para habilitar la búsqueda musical dentro de FocusFlow.
5. Ejecuta:

   ```bash
   python app.py
   ```

6. Abre http://127.0.0.1:5000 en el navegador.

## Activar la búsqueda musical
1. Entra a [Google Cloud Console](https://console.cloud.google.com/).
2. Selecciona o crea un proyecto y habilita **YouTube Data API v3**.
3. Crea una clave de API.
4. Configura esa clave como variable de entorno llamada `YOUTUBE_API_KEY` antes de ejecutar `python app.py`.

No pongas tu clave directamente en el código ni la publiques en GitHub. Si no configuras la clave, las tareas seguirán funcionando y FocusFlow mostrará un aviso; el enlace para abrir YouTube Music seguirá disponible.

## Límites
La API de YouTube permite buscar videos, pero no da acceso ilimitado a todo el catálogo ni a las funciones privadas de una cuenta de YouTube Music. Algunos videos no permiten reproducción incrustada. FocusFlow no solicita tu contraseña de Google ni evita las restricciones de YouTube.

## Archivos principales
- `app.py`: servidor Flask, tareas y búsqueda musical.
- `templates/index.html`: estructura de la interfaz.
- `static/style.css`: estilos.
- `static/music.js`: búsqueda y reproductor.
- `focusflow.db`: base de datos local creada automáticamente.
