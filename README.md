# FOOCUS

![Logotipo de FOOCUS](static/foocus-logo.svg)

**Estudia · Organiza · Avanza**

FOOCUS es una aplicación local de escritorio y navegador para organizar tareas de estudio, planificar la semana y registrar el tiempo dedicado a cada tarea. Está desarrollada con Python, Flask, SQLite, Jinja, HTML, CSS y JavaScript.

> **Proyecto realizado con asistencia de Inteligencia Artificial.** Se utilizó IA generativa como apoyo para implementar y mejorar funcionalidades, generar y revisar código, resolver problemas técnicos y redactar documentación. El desarrollo asistido por IA no sustituye las pruebas ni la revisión de los cambios.

## Funciones principales

- Crear, editar, completar, buscar, filtrar y eliminar tareas.
- Organizar tareas por asignatura, prioridad y fecha límite.
- Estimar el tiempo de cada tarea y planificar el día de estudio.
- Revisar la carga de trabajo de los próximos siete días.
- Registrar sesiones de trabajo, cronómetro, avances y siguientes pasos.
- Consultar historial de sesiones, estadísticas, meta diaria y mapa de actividad.
- Usar temporizadores de enfoque de 5, 15 o 25 minutos.
- Desbloquear tareas pendientes con un plan anti-procrastinación de cinco minutos, un primer paso concreto y sugerencias por prioridad y fecha límite.
- Guardar notas rápidas, cambiar entre modo claro y oscuro y exportar tareas/sesiones a CSV.

Las tareas, las sesiones y la meta diaria se almacenan en SQLite. Las notas rápidas, el tema y el estado del temporizador se almacenan en el navegador utilizado. Esta versión es local y de un solo usuario; no incluye cuentas ni sincronización entre dispositivos.

## Requisitos

- Python 3.10 o posterior.
- Navegador actualizado para la versión web local.
- Conexión a internet para comprobar nuevas versiones.

## Ejecutar desde el código fuente en Windows

Abre PowerShell en la carpeta del repositorio y ejecuta:

    py -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    python app.py

Luego abre http://127.0.0.1:5000 en el navegador. La base de datos focusflow.db se crea junto a app.py. Para cambiar su ubicación, configura FOCUSFLOW_DATABASE. Haz una copia de seguridad antes de actualizar datos importantes.

## Instalar FOOCUS para Windows

1. Abre [Releases](https://github.com/Franxescoo/FOOCUS/releases/latest).
2. Descarga FOOCUS-Setup.exe y ejecútalo.
3. Para actualizar una instalación anterior, cierra la app y ejecuta el instalador más reciente.

El identificador del instalador, el ejecutable interno, la carpeta de instalación y la carpeta de datos existentes se conservan por compatibilidad. El instalador nuevo se distribuye como FOOCUS-Setup.exe. Se conservan el identificador del instalador, el ejecutable interno y las carpetas de instalación y datos para mantener la compatibilidad con instalaciones anteriores.

## Actualizaciones

La aplicación consulta la última publicación semántica de GitHub al abrirse y periódicamente mientras está abierta. Cuando detecta una versión más reciente, muestra el número de versión y los cambios, y permite descargar el instalador. La instalación se realiza manualmente ejecutando el archivo descargado; la app no se reemplaza silenciosamente mientras está en uso.

Las compilaciones correctas de la rama main ejecutan las pruebas, generan el instalador y publican automáticamente el siguiente parche (V1.0.1, V1.0.2, etc.). Los cambios en ramas de desarrollo y pull requests no se publican como versiones estables.

Para que la comprobación y descarga funcionen para cualquier persona sin un token personal, el repositorio FOOCUS que contiene las Releases debe ser público. El actualizador consulta las Releases públicas de forma anónima. El programa distribuido no incluye tokens privados. En un despliegue privado, el token opcional debe configurarse como variable de entorno del servidor, nunca dentro del código o instalador.

## Pruebas

Desde la raíz del proyecto:

    python -m unittest discover -s tests -v

GitHub Actions ejecuta la suite automáticamente en los cambios configurados del repositorio.

## Seguridad y limitaciones

- No publiques esta versión como servicio web multiusuario sin autenticación, autorización, aislamiento de datos por usuario y una configuración de producción.
- La protección CSRF, la política CSP con nonce y los encabezados de seguridad reducen riesgos del navegador, pero no sustituyen autenticación ni autorización.
- Haz una copia de seguridad de la base de datos antes de actualizar o mover los datos.

## Tecnologías

Python · Flask · SQLite · Jinja · HTML · CSS · JavaScript · PyInstaller · Inno Setup

Repositorio: [Franxescoo/FOOCUS](https://github.com/Franxescoo/FOOCUS)
