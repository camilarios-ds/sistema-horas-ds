# Sistema de Horas - DS HNOS

Aplicación web en Streamlit para importar fichadas, corregir entradas/salidas olvidadas, calcular horas y exportar un resumen para RR. HH.

## Publicar en Streamlit Community Cloud

1. Crear un repositorio en GitHub.
2. Subir todos los archivos y carpetas de este proyecto a la raíz del repositorio.
3. Ingresar a Streamlit Community Cloud y seleccionar **Create app**.
4. Elegir el repositorio y usar `app.py` como archivo principal.
5. En opciones avanzadas, seleccionar Python 3.12.
6. Presionar **Deploy**.

## Importante

- Las correcciones manuales duran durante la sesión de trabajo y se incluyen en el Excel descargado.
- En Community Cloud, los cambios hechos desde la pestaña Configuración pueden perderse cuando la app se reinicia. Para cambios permanentes, actualizar `configuracion/empleados.csv` y `configuracion/feriados.csv` en GitHub.
- No subir archivos de fichadas reales al repositorio. RR. HH. debe cargarlos desde la aplicación.
