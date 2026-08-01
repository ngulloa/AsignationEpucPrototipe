# Auditoría técnica y guía de continuidad

## Estado verificado

Documento actualizado el 1 de agosto de 2026 para la versión 0.2.0. Describe el
árbol distribuible actual, no los estados de ejecución utilizados durante el
desarrollo.

La aplicación es un cliente local PySide6 con persistencia en archivos. Permite
registrar cuentas locales, administrar agregados académicos personales,
solicitar aprobación, preparar publicaciones y sincronizar el conjunto público
mediante Git. No constituye un servicio institucional multiusuario: identidad,
autorización efectiva, coordinación entre clones y recuperación remota siguen
dependiendo del repositorio y de su operación humana.

## Instalación y verificación

El procedimiento normativo está en `README.md` y `pyproject.toml`. Requiere
Python 3.14, crea un entorno virtual e instala con:

```bash
python -m pip install -e ".[dev]"
```

Antes del primer inicio se copia `config/owner.example.json` a
`config/owner.local.json` y se completa localmente. Ese archivo y `users/`
están ignorados y nunca forman parte de la distribución.

Verificación completa:

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_project_smoke.py tests/test_visual_references.py
git diff --check
```

El paquete expone `epuc-academic-assignment` y `epuc-reset-local-state`. Los
archivos de configuración predeterminada, los catálogos y los documentos
públicos vacíos se incluyen como `data-files` para instalaciones no editables.

## Arquitectura

`main.py` es la raíz ejecutable. `backend/composition.py` construye el grafo
productivo sin efectos laterales: sesión, autenticación, aprobaciones,
académicos personales, tablas compartidas, publicaciones, notificaciones y
sincronización Git. `backend/frontend_controller.py` adapta esa fachada a los
contratos consumidos por Qt.

Las responsabilidades se distribuyen así:

- `backend/`: contratos de dominio, validación, casos de uso, coordinación de
  publicación y Git;
- `persistence/`: rutas canónicas, JSON atómico y repositorios CSV;
- `frontend/`: ventana única, navegación, vistas, widgets, configuración y
  operaciones asíncronas;
- `scripts/`: migración explícita de datasets y reinicio administrativo seguro;
- `tests/`: dominio, persistencia, integración, Qt offscreen y estructura;
- `config/`: textos, sistema visual y ejemplo de propietario;
- `data/public/catalogs/`: fuentes normativas `AcademicStaff` y
  `AcademicProfile`;
- `docs/decisions/`: decisiones arquitectónicas vigentes.

No hay módulos Python sin consumidor conocido. Los `__init__.py` sin importador
directo definen paquetes distribuibles; los módulos ejecutables se consumen por
sus puntos de entrada y pruebas.

## Rutas y datos

`ProjectPaths` deriva toda persistencia desde una raíz explícita y valida cada
componente variable. En una copia fuente usa la raíz del proyecto; en una
instalación no editable puede usar la raíz del entorno virtual donde setuptools
instala los recursos declarados.

Estado distribuido esperado:

```text
config/
  frontend_texts.json
  frontend_visual.json
  owner.example.json
data/public/
  approved_users.json       # esquema 2, lista vacía
  notifications_error.json  # esquema 3, lista vacía
  tables_index.json         # esquema 2, lista vacía
  catalogs/
    academic_staff.csv
    academic_profiles.csv
  tables/                   # se crea al publicar
users/                      # vacío o ausente; solo runtime ignorado
```

Las tablas personales y públicas usan dos CSV:

```text
academics.csv
academic_appointments.csv
```

La identidad, los nombramientos y los catálogos se unen en backend. Qt solo
recibe proyecciones y nunca lee CSV ni JSON directamente. Los repositorios
validan el esquema completo antes de exponer datos y realizan reemplazos
atómicos para evitar archivos parciales.

`data/Academic.csv` fue retirado después de comprobar que no participaba en la
composición. ADR-004 conserva la evidencia y el fundamento. El adaptador CSV
sigue activo para datos personales, públicos y borradores. El artefacto
`docs/Tables/Academic.csv` permanece como fuente documental.

## Publicación y Git

Una publicación prepara dos CSV y una entrada de índice bajo una operación
privada. El coordinador valida sesión, aprobación, rutas autorizadas, catálogos,
estado Git y huellas antes de materializar cambios públicos. Los estados y la
recuperación de push se definen en ADR-003.

El código no debe agregar al commit estado privado, configuración propietaria,
temporales o recuperaciones de persistencia. Los permisos de la interfaz no
sustituyen los permisos del repositorio ni resuelven por sí solos la
autorización entre clones.

## Reinicio administrativo

El comando normativo es:

```bash
python -m scripts.reset_local_state --dry-run
```

Dry-run es también el modo predeterminado. `--apply` exige `--backup-dir` fuera
del repositorio si hay estado por cambiar. La lista blanca comprende:

- contenido de `users/`;
- `config/owner.local.json`;
- contenido de `data/public/tables/`;
- aprobaciones, índice y notificaciones públicas, reinicializados con sus
  esquemas actuales.

El comando muestra categorías y rutas, nunca contenido; rechaza rutas externas,
enlaces simbólicos y tipos de archivo no soportados; copia cada archivo,
verifica SHA-256 y valida el manifiesto antes de limpiar. Conserva configuración
predeterminada y catálogos. Una segunda ejecución sobre el estado vacío no hace
cambios.

## Diseño y referencias visuales

El conjunto mínimo se conserva en `design.prototipe/exportacion_penpot/`:

- `PrototipoSistemadePuntosLocal.penpot`: única fuente editable;
- `01_Wireframes.pdf`: referencia humana compacta.

La exportación JSON/PNG descompuesta era una reproducción exacta del archivo
Penpot y fue retirada. Las capturas candidatas no aprobadas también se retiraron
porque `tests/visual_capture.py` las regenera determinísticamente en una ruta
temporal. `tests/test_visual_references.py` comprueba la integridad interna y la
reproducibilidad sin guardar artefactos generados en el repositorio.

`docs/original_artifacts.sha256` cubre solamente las dos referencias de diseño
conservadas y la tabla académica documental.

## Seguridad y privacidad

Las contraseñas se almacenan únicamente como verificadores locales bajo
`users/`. Los estados de aprobación, notificación y publicación pueden contener
identidades o texto operacional y por ello deben partir vacíos en una
distribución. Las fixtures usan datos sintéticos.

La revisión histórica encontró categorías personales en versiones previas de
`data/Academic.csv` y estados públicos no vacíos. Limpiar el árbol actual no
elimina blobs alcanzables desde commits existentes. Una purga exigiría rotación
o coordinación con todos los clones y una reescritura separada; no forma parte
de la operación normal de limpieza.

## Continuidad

Al modificar persistencia:

1. actualizar el contrato o esquema y su validador;
2. mantener la escritura atómica;
3. agregar migración explícita y respaldada si existen datos anteriores;
4. actualizar `ProjectPaths`, composición, pruebas, README y un ADR;
5. probar desde una copia sin usuarios ni configuración local.

Al modificar UI, mantener la ventana única, el acceso a datos mediante
contratos y las operaciones lentas fuera del hilo Qt. Las capturas visuales se
generan en directorios temporales; solo una referencia aprobada y no reproducible
justificaría volver a versionarlas.

Las decisiones aún abiertas son de producto y operación: política de identidad
compartida, transporte de solicitudes, autorización institucional, concurrencia
entre clones, observabilidad y estrategia de despliegue fuera de un entorno
virtual local.
