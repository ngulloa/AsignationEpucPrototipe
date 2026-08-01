# ADR-002: agregado académico y persistencia CSV v2

- Estado: aceptada
- Fecha: 2026-07-31
- Alcance: identidad académica, catálogos de referencia y nombramientos
- Reemplaza para tablas productivas: ADR-001

## Contexto

El CSV operacional v1 mezclaba identidad, planta, perfil y jornada en una fila.
Esa representación no permite historial de nombramientos y obliga a repetir la
planta, aunque esta ya está determinada por el perfil. No existe todavía una
política institucional para correo ni fechas de vigencia, y la interfaz actual
no los captura.

`data/Academic.csv` era un archivo legado protegido y no una tabla productiva
de usuarios. ADR-004 documenta su retiro posterior, una vez verificados sus
consumidores y su respaldo externo.

## Decisión

El dominio usa cuatro contratos inmutables:

- `Academic`: identidad, RUT, nombre, correo opcional y estado;
- `AcademicStaff`: identidad estable y etiqueta de planta;
- `AcademicProfile`: identidad versionada, planta propietaria, porcentajes y
  capacidad de cursos extra;
- `AcademicAppointment`: vínculo entre académico y perfil, jornada e intervalo
  de vigencia. No representa actividades ni carga asignada.

La proyección de compatibilidad para Qt conserva `academic_id`, RUT, nombre,
planta, perfil, jornada y estado. La unión se realiza en backend. Debe existir
como máximo un nombramiento vigente para proyectar; la ambigüedad se rechaza.
No se adopta todavía una regla general de solapamientos históricos.

Los nuevos datasets usan este par:

```text
academics.csv
academic_id,rut,name,email,status

academic_appointments.csv
appointment_id,academic_id,profile_id,weekly_hours,start_date,end_date
```

En tablas públicas, el acompañante se llama
`<stem-principal>.appointments.csv`. La ruta deriva solo del archivo principal
registrado en `tables_index.json`; nunca del nombre visible de la tabla.

Cada alta de académico y nombramiento usa UUID4. La conversión de una fila v1
usa UUID5 determinista para el nombramiento, conserva el `academic_id` y deja
correo y fechas vacíos. Un perfil desconocido o una combinación incompatible
continúa siendo visible como v1, pero bloquea migración y escritura v2 hasta su
corrección.

## Catálogos

Las únicas tablas de referencia productivas son:

```text
data/public/catalogs/academic_staff.csv
data/public/catalogs/academic_profiles.csv
```

Sus identificadores son independientes de etiquetas y claves de compatibilidad.
El catálogo se administra como append-only: no se elimina una identidad
referenciada. Un cambio semántico de porcentajes exige otra identidad o versión;
la anterior queda inactiva y disponible para lectura histórica. No existe aún
un mutador de catálogo. Si se agrega, debe entrar por backend y requerir permiso
de owner.

Los porcentajes se representan con `Decimal`, están entre 0 y 100 y suman 100.
`allows_extra_courses=false` para Investigador proviene de las páginas 10 y 20
de la propuesta. El valor `true` en los demás perfiles es una interpretación
provisional, no una regla institucional definitivamente aprobada.

Los estados Activo, Inactivo, Sabático y Terminado continúan siendo una decisión
provisional del MVP. El correo y las fechas pueden estar vacíos; no se inventan
durante migración.

## Consistencia multifichero

Toda escritura valida el agregado completo, prepara y relee ambos temporales,
guarda snapshots de rollback y reemplaza cada archivo atómicamente. Si falla el
segundo reemplazo, restaura el primero. La coordinación sigue suponiendo una
sola instancia escritora; no hay bloqueo distribuido ni transacción entre
procesos.

## Migración

`python -m scripts.migrate_academic_datasets` ejecuta dry-run por defecto.
`--apply` requiere `--backup-dir`. El comando descubre solamente tablas privadas
canónicas bajo `ProjectPaths` y tablas públicas declaradas en el índice, valida
todas antes de modificar, verifica respaldos y no muestra filas ni identidades.
Es idempotente y deja intactos los datasets incompatibles.

`docs/Tables/Academic.csv` está fuera del descubrimiento y se conserva como
fuente documental. El antiguo `data/Academic.csv` fue retirado por ADR-004.
