# FocusFlow

FocusFlow es una aplicación local de productividad para estudiar y organizar tareas. Está construida con Python, Flask, SQLite, Jinja, CSS y JavaScript. La interfaz busca mantener el trabajo importante a la vista sin convertir la página en un tablero saturado.

## Funciones actuales

### Organización de estudios
- Crear, editar, completar y eliminar tareas con prioridades y fechas límite.
- Buscar tareas y filtrarlas por estado.
- Avisos visuales para tareas vencidas o que vencen hoy.
- Registro de sesiones de trabajo por tarea, con tiempo transcurrido y comentarios al cerrar.
- Historial de sesiones y tiempo total registrado por tarea.
- Estadísticas de tiempo de hoy, esta semana y el historial completo.
- Mapa de actividad de los últimos 35 días.
- Meta diaria de estudio configurable, guardada en SQLite y comparada con las sesiones finalizadas.
- Sistema anti-procrastinación para elegir una tarea y definir un primer paso de cinco minutos.
- Temporizador de enfoque con bloques de 25, 15 y 5 minutos.

### Herramientas personales
- Notas rápidas guardadas en el almacenamiento local del navegador.
- Modo claro y oscuro.
- Exportación CSV de tareas y sesiones.
- Panel musical con búsqueda mediante ytmusicapi, colección local y reproductor integrado de YouTube cuando el video permite reproducción incrustada.

## Requisitos

- Python 3.10 o posterior.
- Navegador actualizado.
- Conexión a internet solo para la búsqueda musical y la reproducción de YouTube.

## Ejecutar en Windows

1. Abre la carpeta del repositorio en VS Code.
2. Abre **Terminal > Nueva terminal**.
3. Crea y activa un entorno virtual.

   PowerShell:

       py -m venv .venv
       .venv\Scripts\Activate.ps1

4. Instala las dependencias:

       python -m pip install -r requirements.txt

5. Inicia FocusFlow:

       python app.py

6. Abre http://127.0.0.1:5000 en el navegador.

La base de datos focusflow.db se crea automáticamente junto a app.py. Si necesitas ubicarla en otra carpeta, configura la variable de entorno FOCUSFLOW_DATABASE con su ruta absoluta. Mantén la aplicación en ejecución mientras la usas.

## Ejecutar pruebas

Desde la carpeta raíz del proyecto:

    python -m unittest discover -s tests -v

Las pruebas usan una base de datos temporal; no deberían modificar tu base de datos personal. GitHub Actions también ejecuta esta suite cuando hay cambios en ramas de desarrollo o pull requests hacia main.

## Seguimiento del trabajo

1. En una tarea pendiente, pulsa **Empezar a trabajar**.
2. FocusFlow registra la hora de inicio y muestra el cronómetro de la sesión.
3. Cuando termines, añade una nota breve sobre lo que avanzaste y pulsa **Terminar y guardar**.
4. Las estadísticas y el mapa de actividad se actualizan con las sesiones guardadas.
5. En **Actividad de trabajo**, puedes fijar una meta diaria de entre 15 minutos y 10 horas, en incrementos de 15 minutos.

Solo puede haber una sesión de trabajo activa a la vez. El servidor evita iniciar trabajo sobre una tarea completada y no permite eliminar una tarea mientras tiene una sesión activa. Si cierras el navegador o la aplicación durante una sesión, vuelve a abrir FocusFlow para retomar y finalizar esa sesión.

El temporizador de enfoque es una herramienta independiente del registro de trabajo por tarea. Su contador de bloques completados se guarda en el navegador y no equivale al número de sesiones de trabajo guardadas en SQLite.

## Datos y privacidad

- Las tareas, sesiones de trabajo y la meta diaria se guardan en focusflow.db.
- Las notas, los ajustes de tema, la música guardada y el contador del temporizador se almacenan en el navegador en el que se usaron.
- Actualmente no hay cuentas de usuario ni sincronización entre dispositivos.
- No compartas contraseñas, claves ni datos personales en el repositorio.
- La exportación CSV antepone un apóstrofo a los textos que podrían interpretarse como fórmulas por aplicaciones de hojas de cálculo.

## Seguridad y configuración

Las solicitudes que cambian información utilizan tokens CSRF de sesión y la aplicación establece encabezados de seguridad básicos. Esto reduce algunos riesgos, pero no hace que la app sea apta por sí sola para un despliegue público o multiusuario.

La clave de sesión se genera al iniciar la aplicación cuando no se configura una. Para mantener sesiones estables entre reinicios, define una clave persistente como variable de entorno:

PowerShell:

    $env:FOCUSFLOW_SECRET_KEY = "reemplaza-esto-por-un-valor-aleatorio-largo"
    python app.py

Usa un secreto largo, privado y único. En un despliegue HTTPS, configura además FOCUSFLOW_SECURE_COOKIE como true. FLASK_DEBUG puede activarse durante desarrollo con valor 1; mantenlo desactivado en un servidor público.

**No expongas esta versión directamente a internet.** Todavía no cuenta con autenticación, autorización ni aislamiento de datos por usuario, y no tiene un proceso de despliegue de producción. Los encabezados CSRF no reemplazan esas protecciones.

## Archivos principales

- app.py: rutas Flask, validación, consultas y reglas del registro de trabajo.
- templates/index.html: estructura de la pantalla principal y los widgets.
- templates/error.html: pantalla de error coherente con la aplicación.
- static/style.css: temas, diseño responsive, paneles y widgets.
- static/music.js: búsqueda, colección musical y reproducción.
- tests/test_app.py: pruebas de rutas, sesión, meta diaria, CSRF y exportación.
- docs/ROADMAP.md: decisiones y pasos recomendados para el crecimiento futuro.
- .github/workflows/tests.yml: ejecución automática de pruebas en GitHub Actions.
- requirements.txt: dependencias de Python.

## Limitaciones conocidas

- Es una aplicación local de un solo usuario; una instancia compartida no separa los datos por persona.
- Las notas rápidas y algunos ajustes viven solo en el navegador y no se incluyen en la exportación CSV actual.
- La búsqueda musical depende de una interfaz comunitaria no oficial y puede dejar de funcionar si cambia el servicio o restringe solicitudes.
- Antes de sumar cuentas, sincronización o publicación web hacen falta autenticación, autorización, migraciones de base de datos, respaldos y una configuración de servidor de producción.
