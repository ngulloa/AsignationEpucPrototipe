# Sistema de asignación de carga académica

Aplicación de escritorio PySide6 para autenticación local, consulta y edición
del registro académico global, y sincronización Git exclusiva de
`data/public/tables/Academic.csv`.

## Instalación

Requiere Python 3.14 y Git. Desde la raíz del checkout:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

En PowerShell, la activación equivalente es:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Para instalar también pytest, pytest-qt y Ruff:

```bash
python -m pip install -e ".[dev]"
```

## Ejecución

```bash
python main.py
```

La instalación expone además el comando `epuc-academic-assignment`.

## Autenticación local

El registro crea una cuenta y abre inmediatamente su sesión. Los nombres de
usuario se normalizan a minúsculas y admiten letras ASCII, números, punto,
guion y guion bajo. La contraseña debe tener entre 4 y 8 caracteres.

Las cuentas se guardan en `data/local/users.json`. El archivo contiene material
de verificación scrypt, nunca la contraseña, y se reemplaza atómicamente con
permisos locales `0600`. La sesión vive solo durante el proceso y se elimina al
cerrarla.

## Acciones de Inicio

Inicio presenta exactamente cinco acciones, en este orden:

1. `Asignar carga`: visible y deshabilitada.
2. `Académicos`: abre el registro global, permite agregar y editar registros.
3. `Asignaciones`: visible y deshabilitada.
4. `Bajar información`: consulta `origin/main` y descarga cambios autorizados.
5. `Subir información`: publica cambios locales autorizados.

Las operaciones Git se ejecutan fuera del hilo de la interfaz. Mientras una
está en curso, las cinco acciones y el cierre de sesión quedan temporalmente
deshabilitados.

## Academic.csv

La única persistencia académica es:

```text
data/public/tables/Academic.csv
```

Su cabecera es exacta y sensible a mayúsculas:

```csv
academic_id,rut,name,plant,profile,weekly_hours,status
```

- `academic_id`: identificador estable y no vacío.
- `rut`: RUT chileno válido; se guarda en formato canónico y no se duplica.
- `name`: nombre del académico.
- `plant`: clave vigente del catálogo de plantas.
- `profile`: clave vigente y compatible del catálogo de perfiles.
- `weekly_hours`: entero con signo.
- `status`: `Activo`, `Inactivo`, `Sabático` o `Terminado`.

Los catálogos versionados están en
`data/public/catalogs/academic_staff.csv` y
`data/public/catalogs/academic_profiles.csv`. La lectura reconoce los aliases
definidos por la aplicación; toda escritura usa las claves canónicas. El CSV se
valida completo antes de cada reemplazo atómico.

## Límites de Bajar y Subir

Ambas acciones exigen un checkout Git válido en la rama `main`, con el remoto
`origin` apuntando al repositorio configurado por la aplicación.

`Bajar información` ejecuta `fetch` y solo admite un avance rápido cuyo rango
modifique exactamente `data/public/tables/Academic.csv`. Valida el archivo
remoto antes de avanzar. Si el rango incluye código, configuración, catálogos u
otra ruta, se detiene y solicita una actualización manual del checkout. También
se detiene ante cambios locales del CSV o divergencia de ramas.

`Subir información` valida el CSV local, rechaza cualquier cambio staged,
rastreado o no rastreado fuera de esa ruta, crea un commit con mensaje fijo y
usa un push no forzado. Si `origin/main` avanzó, exige bajar primero. Si el push
falla, conserva un único commit verificado para reintentar el mismo envío.

Estas acciones no resuelven conflictos, no mezclan ramas, no actualizan código,
no sincronizan catálogos y no ejecutan force push.

## Datos que no deben versionarse

No deben incorporarse al repositorio:

- `data/local/` y su archivo de cuentas;
- contraseñas, tokens, claves y credenciales Git;
- entornos virtuales, cachés, logs, estados temporales ni capturas de revisión;
- archivos `.corrupt.*`, `.tmp`, respaldos o exportaciones locales.

Para verificar el producto durante el desarrollo:

```bash
python -m pytest -q
ruff check .
ruff format --check .
```
