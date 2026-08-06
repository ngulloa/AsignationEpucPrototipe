# Sistema de asignación de carga académica

## Propósito

Prototipo de escritorio para autenticación local, gestión de académicos y
asignación de carga de cursos mediante una interfaz PySide6.

## Requisitos

- Python 3.14
- Git, solo para las funciones de sincronización

## Instalación

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Ejecución

```bash
python main.py
```

La instalación también crea el comando `epuc-academic-assignment`.

## Estructura mínima de datos

`data/public/tables/` contiene identidades y vínculos académicos, períodos,
cursos, ofertas, asignaciones, autorizaciones y ajustes. Las tablas deben
conservar sus encabezados aunque no tengan registros.

`data/public/catalogs/` contiene los catálogos requeridos por la aplicación,
incluidas las reglas de carga y la Política V3.

## Almacenamiento local

Las cuentas se guardan en `data/local/users.json`. Las operaciones CSV crean
temporalmente bloqueos, staging y respaldos bajo `data/local/` para permitir
validación transaccional y rollback. Este directorio no se comparte mediante
Git.

## Sincronización

Los controles de subida y bajada sincronizan exclusivamente las tablas
compartidas autorizadas. Las bajadas aceptan solo avances rápidos, los datos se
validan antes de aplicarse y los conflictos requieren resolución manual.

## Limitaciones actuales

- El dataset inicial no incluye períodos, cursos, ofertas ni asignaciones.
- Solo la asignación de tipo Curso está habilitada.
- La Política V3 conserva el estado institucional `PROPOSED`.
- La sincronización requiere acceso al remoto Git configurado y una identidad
  Git válida para subir cambios.
