# ADR-004: retiro del CSV académico operacional legado

- Estado: aceptada
- Fecha: 2026-08-01
- Reemplaza el uso operativo restante descrito por ADR-001

## Contexto

`data/Academic.csv` pertenecía a la primera persistencia monolítica. La
composición productiva actual crea repositorios personales bajo
`users/<usuario>/tables/` y repositorios publicados bajo `data/public/tables/`.
La propiedad `ProjectPaths.operational_academics_path` no tenía consumidores
productivos; sus únicas referencias restantes eran documentación y pruebas del
adaptador CSV con rutas temporales independientes.

El adaptador `CsvAcademicRepository` continúa siendo necesario: implementa la
persistencia de los agregados personales, públicos y de borradores. Lo retirado
es exclusivamente la instancia histórica en la raíz de `data/`.

Antes del retiro se verificó que:

- la raíz de composición no abre el archivo;
- ninguna ruta productiva lo descubre;
- la persistencia v2 cubre la función vigente;
- las pruebas del adaptador crean sus propios archivos bajo `tmp_path`;
- el contenido existente quedó en un respaldo externo verificado;
- `docs/Tables/Academic.csv` conserva el artefacto documental original.

## Decisión

Se elimina `data/Academic.csv` y la propiedad de ruta dedicada. Los comandos de
calidad dejan de necesitar una excepción por espacios finales en ese archivo.
No se modifica `docs/Tables/Academic.csv`.

## Consecuencias

Una instalación nueva parte únicamente con catálogos y documentos públicos
vacíos. Los datos académicos aparecen después del registro y guardado de una
tabla personal. El historial Git anterior aún contiene el archivo legado y sus
datos pueden recuperarse; cualquier purga histórica exige una operación
separada, coordinada y potencialmente disruptiva.
