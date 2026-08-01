# Sistema de asignación de carga académica

Aplicación de escritorio para administrar tablas académicas personales, compartirlas con usuarios aprobados, gestionar aprobaciones y sincronizar los datos compartidos mediante Git.

La [auditoría técnica y guía de continuidad](docs/AUDITORIA_TECNICA.md) documenta la arquitectura, los esquemas, la UX/UI, los riesgos y los procedimientos para extender el proyecto.

## Requisitos

- Python 3.14 (`>=3.14,<3.15`).
- Git instalado.
- Una copia local del repositorio privado, con la rama de trabajo y el remoto `origin` configurados.
- Acceso de lectura y escritura al repositorio según las tareas que realizará cada persona.

## Instalación con entorno virtual

En Windows (PowerShell):

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
copy config\owner.example.json config\owner.local.json
```

En macOS o Linux:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp config/owner.example.json config/owner.local.json
```

Edite `config/owner.local.json` y reemplace el valor nulo de `username` por el nombre de la cuenta propietaria.

Como alternativa, con Miniconda:

```bash
conda create -n epuc python=3.14
conda activate epuc
python -m pip install -e ".[dev]"
```

Luego cree `config/owner.local.json` desde el ejemplo como se indicó arriba.

## Uso

Desde la raíz del repositorio:

```bash
python main.py
```

Para ejecutar las pruebas:

```bash
python -m pytest -q
```

La instalación también expone `epuc-academic-assignment` como punto de entrada.
Los recursos de configuración predeterminada, catálogos y documentos públicos
vacíos forman parte del paquete. Una instalación no editable los resuelve desde
la raíz de su entorno virtual.

## Reinicio seguro del estado local

El único comando administrativo de limpieza trabaja con una lista blanca y no
modifica nada por defecto:

```bash
.venv/bin/python -m scripts.reset_local_state --dry-run
```

Para aplicar un plan no vacío se exige un respaldo fuera del repositorio:

```bash
.venv/bin/python -m scripts.reset_local_state \
  --apply \
  --backup-dir /ruta/externa/respaldo-fechado
```

El comando respalda y verifica antes de cambiar rutas, no sigue enlaces
simbólicos y solo reinicia `users/`, la configuración propietaria local, las
tablas públicas y los tres registros públicos. Conserva los catálogos y la
configuración predeterminada. Es seguro volver a ejecutarlo.

El botón **Actualizar** recibe cambios remotos mediante avance rápido y publica la tabla personal del usuario junto con los datos compartidos pendientes. La operación requiere una cuenta aprobada y un repositorio Git válido.

Los datos privados se guardan bajo `users/<usuario>/`. Las aprobaciones, tablas publicadas y notificaciones compartidas se guardan bajo `data/public/`.
El repositorio distribuible parte sin usuarios ni propietario local, y con los
tres registros públicos vacíos en sus esquemas vigentes.

## Integridad académica del MVP

Las tablas versionadas `data/public/catalogs/academic_staff.csv` y
`academic_profiles.csv` son la única fuente de verdad para plantas, perfiles y
proporciones. La interfaz obtiene sus opciones desde backend. Las claves de
compatibilidad siguen siendo `Ordinaria`, `Especial`, `Investigador`, `Mixto`,
`Standard`, `Docente` y `Gestión`, pero los CSV productivos referencian IDs
estables independientes de esas etiquetas. Los estados `Activo`, `Inactivo`,
`Sabático` y `Terminado` siguen siendo una decisión provisional del MVP.

Las tablas personales y públicas usan `academics.csv` con
`academic_id,rut,name,email,status` y un acompañante de nombramientos con
`appointment_id,academic_id,profile_id,weekly_hours,start_date,end_date`. Correo
y fechas pueden quedar vacíos y todavía no se editan en la interfaz. Qt consume
una proyección aplanada creada en backend, no realiza uniones ni lee catálogos.

La lectura conserva compatibilidad con valores reconocibles del prototipo: por ejemplo, `Mixta` se interpreta como `Especial`, `Estandar`/`Estándar` como `Standard`, y variantes sin tilde de `Gestión` o `Sabático` se normalizan en memoria. Leer no reescribe el CSV. Una combinación histórica hoy incompatible se muestra con una advertencia y debe corregirse antes de guardarse.

Al crear con un RUT duplicado, el formulario solicita `Cancelar` o `Sobrescribir`. Sobrescribir requiere una confirmación explícita ligada al identificador y a una huella del registro advertido; el backend vuelve a validar todo, rechaza confirmaciones obsoletas y conserva el `academic_id` existente mediante reemplazo atómico.

Para revisar migraciones v1 sin escribir:

```bash
.venv/bin/python -m scripts.migrate_academic_datasets
```

La aplicación exige `--apply --backup-dir <directorio>` para aplicarlas. El
procedimiento y sus decisiones están en
[ADR-002](docs/decisions/ADR-002-academic-aggregate-v2.md).

No versione `config/owner.local.json`, contraseñas, credenciales ni estados locales. En este MVP, los permisos de la aplicación no sustituyen los permisos del repositorio privado: el acceso efectivo también depende de la autorización configurada en Git.

## Privacidad y preparación de cambios

Las notificaciones v3 exigen una descripción normalizada de hasta 1000
caracteres. La aplicación rechaza patrones que aparentan incluir contraseñas,
tokens, claves API, encabezados de autorización, claves privadas, URLs con
credenciales, rutas personales completas o trazas completas. Esta detección es
una reducción defensiva del riesgo y no garantiza identificar todos los
secretos; nunca deben copiarse credenciales, rutas personales ni trazas.

`Guardar` modifica exclusivamente los dos CSV académicos privados del usuario.
`Compartir tabla` exige un nombre único, prepara el agregado de dos CSV más su
entrada de índice y registra una operación privada, pero no ejecuta Git ni
afirma una publicación remota. `Actualizar` publica tablas personales
preparadas; `Publicar` hace lo mismo con un borrador de edición pública. Ambos
corren fuera del hilo Qt, usan fast-forward seguro y conservan el commit para un
reintento exacto cuando falla el push. Los estados y límites se documentan en
[ADR-003](docs/decisions/ADR-003-public-table-publication.md).

Una solicitud de aprobación pendiente puede retirarse lógicamente sólo por su
titular. No se borra y conserva autor y fecha del retiro. La política para volver
a solicitar aprobación después de un retiro no está definida todavía y queda
registrada como decisión pendiente; el flujo actual no crea una segunda
solicitud automáticamente.
