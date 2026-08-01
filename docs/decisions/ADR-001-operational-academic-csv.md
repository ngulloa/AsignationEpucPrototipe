# ADR-001: CSV operacional de académicos

- Estado: reemplazada por ADR-002 y ADR-004
- Fecha: 2026-07-30
- Alcance: primera versión funcional del MVP

## Contexto

El artefacto fuente protegido `docs/Tables/Academic.csv` usa este esquema:

```text
academic_id,rut,name,email,status,start_date,end_date
```

El formulario disponible en el MVP entrega exclusivamente:

```text
name,rut,plant,profile,weekly_hours,status
```

No existe información suficiente para completar `email`, `start_date` o
`end_date`. A la vez, descartar `plant`, `profile` o `weekly_hours` perdería
datos efectivamente ingresados por la persona usuaria.

## Decisión

`docs/Tables/Academic.csv` se conserva intacto como artefacto fuente. No se
migra, escribe, renombra ni elimina.

El MVP utiliza un archivo separado y operacional:

```text
data/Academic.csv
```

con la cabecera exacta:

```text
academic_id,rut,name,plant,profile,weekly_hours,status
```

Cada alta recibe un UUID4 textual. El RUT se almacena en formato canónico y
`weekly_hours` como entero en el modelo de aplicación, convertido a texto
únicamente por el adaptador CSV.

Esta separación es una decisión técnica del MVP. No constituye una regla
institucional ni define el modelo definitivo del sistema.

## Consecuencias

- El formulario puede persistirse sin inventar ni perder campos.
- El artefacto original y su hash permanecen verificables.
- El servicio depende de una abstracción de repositorio; solo la raíz de
  composición conoce el adaptador CSV.
- Cada escritura reconstruye y valida el archivo completo en un temporal del
  mismo directorio, fuerza su vaciado y usa `os.replace`.
- La edición, eliminación y migración del archivo original quedan fuera del
  alcance.
- La coordinación entre varios procesos que escriban simultáneamente no está
  resuelta en este MVP. La aplicación debe ejecutarse como una única instancia
  escritora.
