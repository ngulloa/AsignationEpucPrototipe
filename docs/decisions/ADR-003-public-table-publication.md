# ADR-003: publicación recuperable de tablas públicas

- Estado: aceptado
- Fecha: 2026-07-31

## Contexto

Una tabla académica pública es un agregado formado, como mínimo, por su CSV de
`Academic`, su CSV de `AcademicAppointment` y su entrada en
`data/public/tables_index.json`. `AcademicStaff` y `AcademicProfile` son
catálogos compartidos; no se duplican dentro de cada tabla. Una escritura
parcial, un commit no enviado o una edición concurrente no pueden presentarse
como una publicación exitosa.

## Decisión

Cada edición pública y cada tabla personal preparada crea una operación privada
bajo `users/<usuario>/outbox/publications/<uuid>/`. La identidad de archivos se
deriva del número estable y del `filename` del índice, nunca del nombre visible.
La operación registra su ID, tabla, tres rutas autorizadas, huella base, commit,
estado y un error saneado. El borrador conserva los dos CSV completos con modo
privado cuando la plataforma lo permite.

La huella SHA-256 incluye los bytes de ambos CSV, la entrada correspondiente del
índice y los dos CSV de catálogos. Una modificación remota del mismo agregado o
de la versión de catálogo invalida el borrador. Un cambio remoto de otra tabla
puede integrarse si todo el rango remoto pertenece a la allowlist pública y la
huella del agregado objetivo continúa igual.

Los estados son:

- `prepared`: borrador validado y aún sin commit;
- `committed_local`: el commit identificable fue creado y registrado;
- `published`: el remoto contiene el commit;
- `retry_pending`: existe un commit local válido cuyo push falló;
- `failed_before_commit`: la operación falló sin crear un commit válido.

`retry_pending` reenvía exactamente el hash registrado. No materializa, no hace
staging y no crea otro commit. Si el remoto ya contiene ese commit, la operación
se confirma como publicada. Un HEAD distinto del commit registrado o una
divergencia remota detienen el reintento.

## Flujo Git y allowlist

Publicar y Actualizar revalidan sesión y aprobación antes de obtener un bloqueo
de proceso por raíz de repositorio. Git corre fuera del hilo Qt. El flujo valida
rama, HEAD, índice y worktree; ejecuta `fetch`; acepta únicamente un
`merge --ff-only` cuyos cambios sean datos públicos permitidos; compara la
huella; vuelve a validar y materializa el agregado; hace `git add --` solo de los
dos CSV y el índice; crea un commit con el UUID; vuelve a comprobar el remoto y
ejecuta un push sin fuerza. No se usa `pull`, reset, checkout destructivo,
rebase, staging global ni force-push.

Los catálogos están permitidos al recibir un avance remoto. Esta decisión no
añade UI de administración ni autoriza su publicación: el flujo de tablas nunca
los incluye en sus rutas de staging. Una futura operación de catálogo deberá ser
explícita y revalidar que la sesión sea del owner.

## Recuperación y límites transaccionales

Antes de materializar se capturan únicamente las tres rutas autorizadas. Si
falla la creación de cualquiera de los CSV, el staging o el commit, esas rutas
se restauran y se limpia solo su estado de índice. El borrador permanece y el
estado pasa a `failed_before_commit`. Un fetch fallido deja los archivos públicos
en su base confirmada. Un push fallido no revierte el commit ni informa “sin
cambios”: pasa a `retry_pending`.

Los reemplazos de dos CSV y el índice no forman una transacción de sistema de
archivos indivisible ni una transacción distribuida con Git. La mitigación es
preparar y validar temporales, respaldar las rutas exactas, restaurarlas antes
del commit ante cualquier falla y publicar los tres archivos en un solo commit.
Una caída abrupta entre llamadas de sistema todavía puede requerir reabrir la
operación; sus borradores, respaldos y estado privado se conservan para ello.

El bloqueo implementado serializa publicaciones dentro de una única instancia
escritora. No coordina procesos ni clones. Entre clones, la protección es
optimista: `fetch`, fast-forward, huella y el rechazo natural de un push sin
fuerza. Dos clones no comparten borradores ni locks, y una colisión de identidad
o nombre detectada después del fetch obliga a preparar o reconciliar de nuevo.

## Permisos y Qt

Leer tablas públicas exige sesión. Editar y publicar exige usuario aprobado;
cualquier aprobado conserva la regla vigente para editar cualquier tabla. El
backend revalida en cada operación. Solo el titular puede preparar/publicar su
tabla personal o renombrarla. No hay acceso anónimo ni cambios en quién puede
aprobar.

Los workers de `QThread` reciben callbacks de backend y no widgets. Progreso,
resultado, error y finalización viajan mediante señales tipadas. La UI desactiva
acciones, rechaza doble clic, restaura su estado al terminar y espera el cierre
del thread durante el cierre de la ventana. `QApplication.processEvents()` no
forma parte del flujo.
