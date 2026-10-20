# FocusFlow

FocusFlow es una aplicación local de productividad para estudiar y organizar tareas. Está construida con Python, Flask, SQLite, Jinja, CSS y JavaScript. La interfaz busca mantener el trabajo importante a la vista sin convertir la página en un tablero saturado.

## Funciones actuales

### Organización de estudios
- Crear, editar, completar y eliminar tareas con prioridades, asignaturas y fechas límite.
- Reutilizar asignaturas escritas desde el formulario de tareas; FocusFlow las normaliza para evitar duplicados por mayúsculas y espacios.
- Definir el tiempo estimado por tarea, comparar la estimación con el tiempo registrado y filtrar la lista por asignatura.
- Consultar un resumen plegable por asignatura con pendientes, tiempo estimado pendiente y tiempo registrado.
- Planificar cada tarea para un día de estudio y revisar los próximos siete días en un calendario plegable, separado de la fecha límite.
- Identificar tareas con planificación pasada para reprogramarlas sin perder la fecha límite original.
- Buscar tareas y filtrarlas por estado.
- Avisos visuales para tareas vencidas o que vencen hoy.
- Registro de sesiones de trabajo por tarea, con tiempo transcurrido, resumen del avance y siguiente paso al cerrar.
- Ventana emergente de sesión al empezar una tarea, con opción de minimizar y retomarla desde un indicador flotante sin detener el cronómetro.
- Mostrar el siguiente paso guardado en la tarjeta de la tarea para retomar el trabajo más rápido.
- Historial de sesiones y tiempo total registrado por tarea.
- Estadísticas de tiempo de hoy, esta semana y el historial completo.
- Mapa de actividad de los últimos 35 días.
- Meta diaria de estudio configurable, guardada en SQLite y comparada con las sesiones finalizadas.
- Sistema anti-procrastinación para elegir una tarea y definir un primer paso de cinco minutos.
- Temporizador de enfoque con bloques de 25, 15 y 5 minutos.

### Herramientas personales
- Notas rápidas guardadas en el almacenamiento local del navegador.
- Modo claro y oscuro.
- Exportación CSV de tareas y sesiones, incluyendo asignatura, estimación, día planificado y siguiente paso registrado.
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

La base de datos focusflow.db se crea automáticamente junto a app.py. Si necesitas ubicarla en otra carpeta, configura la variable de entorno FOCUSFLOW_DATABASE con su ruta absoluta. Mantén la aplicación en ejecución mientras la usas. Las nuevas instalaciones crean las tablas de asignaturas, las estimaciones y las fechas planificadas; las instalaciones anteriores reciben columnas nuevas de forma aditiva y conservan sus tareas y sesiones. Haz una copia de seguridad antes de actualizar una base de datos importante.

## Instalar como aplicación de escritorio en Windows

FocusFlow se puede instalar como una aplicación de escritorio con su propia ventana, sin abrir el navegador manualmente.

### Descargar desde la página

1. En la pantalla principal de FocusFlow, busca **FocusFlow para Windows** o pulsa el enlace de descarga del encabezado.
2. La sección consulta la publicación más reciente de GitHub y compara su número de compilación con el de la aplicación instalada.
3. Pulsa **Descargar instalador** y, cuando termine la descarga de `FocusFlow-Setup.exe`, ábrelo para instalar o actualizar FocusFlow.
4. Cierra FocusFlow antes de actualizar. El instalador utiliza el mismo identificador de aplicación para actualizar la carpeta del programa.

El botón apunta al instalador de la publicación más reciente, por lo que no hay que cambiar el enlace de la página para cada versión. Como el repositorio es privado, debes iniciar sesión en GitHub con una cuenta que tenga acceso a FocusFlow para descargar el archivo. La publicación enlazada permite revisar la versión y sus notas. La página no consulta la API privada ni compara automáticamente las versiones porque eso requeriría credenciales autorizadas; no se incluye ningún token dentro de la aplicación.

### Publicación automática

Cada compilación correcta que se ejecuta al subir cambios a `main` publica una nueva versión de Windows en **GitHub Releases**, además de mantener el artefacto temporal de Actions por 30 días. La versión de compilación se incorpora al programa para que la página pueda comprobar si existe una compilación más reciente. Las compilaciones de ramas de desarrollo y pull requests no se publican como versiones estables.

El instalador instala el componente Microsoft Edge WebView2 necesario para la ventana de escritorio. FocusFlow guarda sus datos en `%LOCALAPPDATA%\FocusFlow`; la base de datos y la clave de sesión quedan fuera de la carpeta de instalación, por lo que actualizar el programa no debería borrar el historial. La música requiere conexión a internet.

**Importante si ya usas la versión de desarrollo:** la base `focusflow.db` ubicada junto al repositorio no se copia automáticamente. Para conservar esos datos en la versión de escritorio, cierra FocusFlow, crea la carpeta `%LOCALAPPDATA%\FocusFlow` si no existe y copia allí tu `focusflow.db` antes de iniciar la aplicación instalada por primera vez. Haz primero una copia de seguridad.

## Ejecutar pruebas

Desde la carpeta raíz del proyecto:

    python -m unittest discover -s tests -v

Las pruebas usan una base de datos temporal; no deberían modificar tu base de datos personal. GitHub Actions también ejecuta esta suite cuando hay cambios en ramas de desarrollo o pull requests hacia main.

## Seguimiento del trabajo

1. En una tarea pendiente, pulsa **Empezar a trabajar**.
2. FocusFlow registra la hora de inicio y abre una ventana emergente con el cronómetro y los campos de revisión.
2a. Puedes minimizar la ventana; la sesión continúa contando y queda un indicador flotante para volver a abrirla. Si recargas la página con una sesión activa, la ventana se recupera automáticamente.
3. Cuando termines, anota lo que avanzaste y define el siguiente paso concreto antes de pulsar **Terminar y guardar**.
4. Las estadísticas y el mapa de actividad se actualizan con las sesiones guardadas.
5. En **Actividad de trabajo**, puedes fijar una meta diaria de entre 15 minutos y 10 horas, en incrementos de 15 minutos.
6. El siguiente paso aparece en la tarjeta de la tarea y en su historial de sesiones para que puedas retomar desde ahí en la próxima sesión.
6. Asigna un **día para estudiar** a las tareas que quieras planificar. En **Plan de estudio · próximos 7 días** puedes revisar la carga por día e iniciar una tarea directamente desde ese panel. La fecha planificada no cambia la fecha límite de entrega.

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

- app.py: rutas Flask, validación, consultas, asignaturas, planificación semanal y reglas del registro de trabajo.
- templates/index.html: estructura de la pantalla principal y los widgets.
- templates/error.html: pantalla de error coherente con la aplicación.
- static/style.css: temas, diseño responsive, paneles y widgets.
- static/music.js: búsqueda, colección musical y reproducción.
- tests/test_app.py: pruebas de rutas, ventana de sesión, recuperación al recargar, meta diaria, CSRF y exportación.
- docs/ROADMAP.md: decisiones y pasos recomendados para el crecimiento futuro.
- .github/workflows/tests.yml: ejecución automática de pruebas en GitHub Actions.
- requirements.txt: dependencias de Python.

## Limitaciones conocidas

- Es una aplicación local de un solo usuario; una instancia compartida no separa los datos por persona.
- Las notas rápidas y algunos ajustes viven solo en el navegador y no se incluyen en la exportación CSV actual.
- La búsqueda musical depende de una interfaz comunitaria no oficial y puede dejar de funcionar si cambia el servicio o restringe solicitudes.
- Antes de sumar cuentas, sincronización o publicación web hacen falta autenticación, autorización, migraciones de base de datos, respaldos y una configuración de servidor de producción.
