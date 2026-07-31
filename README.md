# Sistema de asignación de carga académica

Aplicación de escritorio para administrar tablas académicas personales, compartirlas con usuarios aprobados, gestionar aprobaciones y sincronizar los datos compartidos mediante Git.

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

El botón **Actualizar** recibe cambios remotos mediante avance rápido y publica la tabla personal del usuario junto con los datos compartidos pendientes. La operación requiere una cuenta aprobada y un repositorio Git válido.

Los datos privados se guardan bajo `users/<usuario>/`. Las aprobaciones, tablas publicadas y notificaciones compartidas se guardan bajo `data/public/`.

No versione `config/owner.local.json`, contraseñas, credenciales ni estados locales. En este MVP, los permisos de la aplicación no sustituyen los permisos del repositorio privado: el acceso efectivo también depende de la autorización configurada en Git.
