from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from modulos.config import (
    cargar_empleados,
    cargar_feriados,
    guardar_empleados,
    guardar_feriados,
)
from modulos.exportacion import exportar_excel
from modulos.procesamiento import (
    calcular_jornadas,
    crear_jornadas,
    crear_resumen,
    leer_fichadas,
    minutos_a_hhmm,
)

st.set_page_config(page_title="Sistema Horas DS", page_icon="⏰", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem;}
    [data-testid="stMetricValue"] {font-size: 1.7rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("⏰ Sistema de Horas - DS HNOS")
st.caption("Importá las fichadas, revisá el resumen y descargá el Excel para RR. HH.")

with st.sidebar:
    st.header("Reglas de cálculo")
    jornada_normal = st.number_input("Jornada normal (horas)", min_value=1.0, max_value=24.0, value=8.0, step=0.25)
    nocturna_desde = st.text_input("Nocturna desde", value="21:00")
    nocturna_hasta = st.text_input("Nocturna hasta", value="06:00")
    sabado_desde = st.text_input("Sábado al 100% desde", value="12:00")
    bloque_extra = st.selectbox("Bloque mínimo de extra", options=[15, 30, 60], index=0, format_func=lambda x: f"{x} minutos")
    st.info("Las extras se pagan solo por bloques completos. Los minutos anteriores al horario oficial no generan extra.")

pestana_procesar, pestana_config, pestana_ayuda = st.tabs([
    "📥 Procesar fichadas", "⚙️ Configuración", "❓ Ayuda"
])

with pestana_config:
    st.subheader("Empleados y horarios oficiales")
    st.write(
        "El horario oficial evita que una fichada anticipada genere horas extras. "
        "Podés cargar varios turnos separados por /, por ejemplo 05:30/07:30. Dejá vacío cuando deba computarse la entrada real."
    )
    empleados = cargar_empleados()
    empleados_editados = st.data_editor(
        empleados,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "ID de usuario": st.column_config.NumberColumn("ID de usuario", min_value=1, step=1),
            "Nombre": st.column_config.TextColumn("Nombre"),
            "Horario oficial": st.column_config.TextColumn("Horario/s oficial/es (ej. 05:30/07:30)"),
        },
        key="editor_empleados",
    )
    if st.button("Guardar empleados y horarios", type="primary"):
        try:
            guardar_empleados(empleados_editados)
            st.success("Empleados y horarios guardados.")
        except Exception as exc:
            st.error(f"No se pudo guardar: {exc}")

    st.divider()
    st.subheader("Feriados")
    feriados = cargar_feriados()
    feriados_editados = st.data_editor(
        feriados,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Fecha": st.column_config.TextColumn("Fecha (AAAA-MM-DD)"),
            "Descripción": st.column_config.TextColumn("Descripción"),
        },
        key="editor_feriados",
    )
    if st.button("Guardar feriados"):
        try:
            fechas_validas = pd.to_datetime(feriados_editados["Fecha"], errors="coerce")
            if fechas_validas.isna().any() and feriados_editados["Fecha"].astype(str).str.strip().ne("").any():
                st.warning("Hay alguna fecha inválida. Usá el formato AAAA-MM-DD.")
            else:
                guardar_feriados(feriados_editados)
                st.success("Feriados guardados.")
        except Exception as exc:
            st.error(f"No se pudo guardar: {exc}")

with pestana_procesar:
    archivo = st.file_uploader("Seleccioná el archivo del reloj", type=["xls", "xlsx"])

    if archivo is not None:
        try:
            fichadas_originales = leer_fichadas(archivo)

            # Las correcciones manuales se conservan mientras la app permanece abierta.
            clave_archivo = f"{archivo.name}:{len(fichadas_originales)}:{fichadas_originales['Fecha/Hora'].min()}:{fichadas_originales['Fecha/Hora'].max()}"
            if st.session_state.get("clave_archivo") != clave_archivo:
                st.session_state["clave_archivo"] = clave_archivo
                st.session_state["correcciones_manuales"] = []

            empleados_para_corregir = cargar_empleados()
            ids_presentes = sorted(fichadas_originales["ID de usuario"].unique().tolist())
            mapa_nombres_correccion = {
                int(fila["ID de usuario"]): str(fila.get("Nombre", "") or f"ID {int(fila['ID de usuario'])}")
                for _, fila in empleados_para_corregir.iterrows()
                if pd.notna(fila.get("ID de usuario"))
            }
            opciones_empleados = {
                f"{mapa_nombres_correccion.get(i, f'ID {i}')} (ID {i})": i for i in ids_presentes
            }

            with st.expander("✏️ Corregir una fichada olvidada", expanded=False):
                st.write(
                    "Agregá la hora que falta. La corrección se usa en el cálculo y también aparece "
                    "en el Excel descargado, sin modificar el archivo original del reloj."
                )
                with st.form("form_correccion", clear_on_submit=False):
                    etiqueta_empleado = st.selectbox("Operario", list(opciones_empleados.keys()))
                    c_fecha, c_hora, c_tipo = st.columns(3)
                    fecha_corr = c_fecha.date_input("Fecha", value=pd.Timestamp(fichadas_originales["Fecha/Hora"].min()).date())
                    hora_corr = c_hora.time_input("Hora faltante", value=datetime.strptime("08:00", "%H:%M").time())
                    tipo_corr = c_tipo.selectbox("Tipo", ["Entrada", "Salida"])
                    agregar_corr = st.form_submit_button("Agregar fichada", type="primary")

                if agregar_corr:
                    empleado_id_corr = opciones_empleados[etiqueta_empleado]
                    fecha_hora_corr = pd.Timestamp(datetime.combine(fecha_corr, hora_corr))
                    st.session_state["correcciones_manuales"].append({
                        "ID de usuario": int(empleado_id_corr),
                        "Fecha/Hora": fecha_hora_corr,
                        "Dispositivo Nro.": 0,
                        "Tipo de registro": 0 if tipo_corr == "Entrada" else 1,
                        "Tipo manual": tipo_corr,
                    })
                    st.success("Fichada agregada. El cálculo se actualizó.")
                    st.rerun()

                correcciones = st.session_state.get("correcciones_manuales", [])
                if correcciones:
                    corr_df_vista = pd.DataFrame(correcciones).copy()
                    corr_df_vista["Nombre"] = corr_df_vista["ID de usuario"].map(mapa_nombres_correccion).fillna(
                        corr_df_vista["ID de usuario"].map(lambda x: f"ID {x}")
                    )
                    corr_df_vista.insert(0, "N.º", range(1, len(corr_df_vista) + 1))
                    st.dataframe(
                        corr_df_vista[["N.º", "Nombre", "ID de usuario", "Fecha/Hora", "Tipo manual"]],
                        use_container_width=True,
                        hide_index=True,
                    )
                    eliminar_n = st.selectbox(
                        "Eliminar una corrección",
                        options=[0] + list(range(1, len(correcciones) + 1)),
                        format_func=lambda x: "— Seleccionar —" if x == 0 else f"Corrección {x}",
                    )
                    b1, b2 = st.columns(2)
                    if b1.button("Eliminar seleccionada", disabled=eliminar_n == 0):
                        st.session_state["correcciones_manuales"].pop(eliminar_n - 1)
                        st.rerun()
                    if b2.button("Borrar todas las correcciones"):
                        st.session_state["correcciones_manuales"] = []
                        st.rerun()
                else:
                    st.caption("Todavía no agregaste correcciones manuales.")

            correcciones = st.session_state.get("correcciones_manuales", [])
            if correcciones:
                correcciones_df = pd.DataFrame(correcciones)
                # Dejamos solo las columnas compatibles con el archivo original.
                for columna in fichadas_originales.columns:
                    if columna not in correcciones_df.columns:
                        correcciones_df[columna] = pd.NA
                correcciones_df = correcciones_df[fichadas_originales.columns]
                fichadas = pd.concat([fichadas_originales, correcciones_df], ignore_index=True)
                fichadas = fichadas.sort_values(["ID de usuario", "Fecha/Hora"]).reset_index(drop=True)
            else:
                fichadas = fichadas_originales.copy()

            jornadas = crear_jornadas(fichadas)

            empleados_actuales = cargar_empleados()
            ids_archivo = sorted(fichadas["ID de usuario"].unique().tolist())
            ids_config = set(pd.to_numeric(empleados_actuales["ID de usuario"], errors="coerce").dropna().astype(int).tolist())
            faltantes = [i for i in ids_archivo if i not in ids_config]
            if faltantes:
                nuevos = pd.DataFrame({
                    "ID de usuario": faltantes,
                    "Nombre": [f"ID {i}" for i in faltantes],
                    "Horario oficial": [""] * len(faltantes),
                })
                empleados_actuales = pd.concat([empleados_actuales, nuevos], ignore_index=True)

            feriados_df = cargar_feriados()
            lista_feriados = pd.to_datetime(feriados_df["Fecha"], errors="coerce").dropna().dt.date.tolist()

            detalle = calcular_jornadas(
                jornadas,
                empleados_actuales,
                lista_feriados,
                jornada_normal_horas=jornada_normal,
                nocturna_desde=nocturna_desde,
                nocturna_hasta=nocturna_hasta,
                sabado_100_desde=sabado_desde,
                bloque_extra_min=bloque_extra,
            )
            resumen = crear_resumen(detalle)

            st.success(f"Archivo procesado: {archivo.name}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Fichadas", f"{len(fichadas):,}".replace(",", "."), delta=f"+{len(st.session_state.get('correcciones_manuales', []))} manuales" if st.session_state.get("correcciones_manuales") else None)
            c2.metric("Empleados", detalle["ID de usuario"].nunique())
            c3.metric("Jornadas", len(detalle))
            c4.metric("Incidencias", int(resumen["Incidencias"].sum()))

            st.subheader("📋 Resumen corto para RR. HH.")
            st.dataframe(resumen, use_container_width=True, hide_index=True)

            total_extras = int(detalle["Extras 50% min"].sum())
            total_noct = int(detalle["Nocturnas min"].sum())
            total_100 = int(detalle["100% min"].sum())
            k1, k2, k3 = st.columns(3)
            k1.metric("Total extras 50%", minutos_a_hhmm(total_extras))
            k2.metric("Total nocturnas", minutos_a_hhmm(total_noct))
            k3.metric("Total al 100%", minutos_a_hhmm(total_100))

            excel = exportar_excel(resumen, detalle, fichadas)
            st.download_button(
                "📤 Descargar Excel para RR. HH.",
                data=excel,
                file_name=f"Resumen_Horas_{pd.Timestamp(fichadas['Fecha/Hora'].min()).strftime('%Y_%m')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )

            with st.expander("Ver detalle de jornadas"):
                columnas_detalle = [
                    "ID de usuario", "Nombre", "Fecha", "Entrada", "Entrada computable", "Salida",
                    "Fichadas", "Total hs", "Normales", "Extras 50%", "Nocturnas", "100%",
                    "Extra nocturna", "Es feriado", "Observaciones",
                ]
                st.dataframe(detalle[columnas_detalle], use_container_width=True, hide_index=True)

            incidencias = detalle[detalle["Observaciones"].astype(str).str.strip() != ""]
            with st.expander(f"⚠️ Incidencias ({len(incidencias)})", expanded=bool(len(incidencias))):
                if incidencias.empty:
                    st.success("No hay incidencias.")
                else:
                    st.dataframe(
                        incidencias[["Nombre", "Fecha", "Entrada", "Salida", "Fichadas", "Observaciones"]],
                        use_container_width=True,
                        hide_index=True,
                    )

        except Exception as exc:
            st.error("No se pudo procesar el archivo.")
            st.exception(exc)
    else:
        st.info("Cargá un archivo XLS o XLSX del reloj para comenzar.")

with pestana_ayuda:
    st.subheader("Cómo usar el sistema")
    st.markdown(
        """
        1. En **Configuración**, revisá los nombres, horarios oficiales y feriados.
        2. En **Procesar fichadas**, cargá el archivo del reloj.
        3. Cuando falte una entrada o salida, abrí **Corregir una fichada olvidada**, elegí el operario, fecha y hora, y presioná **Agregar fichada**.
        4. Revisá el resumen y las incidencias.
        5. Descargá el Excel para RR. HH.

        **Reglas incluidas**
        - Primera fichada del día: entrada. Última fichada: salida.
        - Jornada normal configurable, inicialmente 8 horas.
        - Extras solo por bloques completos de 15 minutos.
        - Una entrada anterior al horario oficial no suma tiempo pagable.
        - Nocturnas entre 21:00 y 06:00 y pueden coexistir con extras.
        - Sábados desde las 12:00, domingos y feriados: 100%.
        """
    )
