# Revisiones locales — Modelo B (Iteración 2B)

**H-02 permanece abierta. El Modelo B implementa mitigaciones operativas y verificaciones de consistencia, pero no proporciona una frontera de autenticación humana resistente frente a agentes con ejecución arbitraria bajo la misma identidad del sistema operativo.**

No hay nuevas cuentas, ACL, claves, servicios ni configuraciones globales. Los hashes
comprueban contenido y alcance, no identidad. Una terminal interactiva tampoco prueba
quién opera. El historial local puede ser sustituido por otro proceso del mismo usuario.

## Solicitar, revisar, continuar

Desde la raíz del repositorio (PowerShell), el agente puede ejecutar:

```powershell
python .opencode/skills/service-workspace/scripts/workspace_cli.py gate-evaluate mi-servicio
python .opencode/skills/service-workspace/scripts/workspace_cli.py decision-request-prepare mi-servicio
python .opencode/skills/service-workspace/scripts/workspace_cli.py decision-request-show mi-servicio request-HASH
```

El usuario, en su terminal, ejecuta explícitamente:

```powershell
python .opencode/skills/service-workspace/scripts/review_cli.py review mi-servicio request-HASH
```

Cada elemento conserva su `decisionId`: introducir el id de una alternativa,
`REJECT`, o Enter para dejar pendiente. `RECORD` registra exactamente las selecciones
mostradas, no las preguntas futuras. Los elementos técnicos/de análisis no son
aprobaciones funcionales. No hay `--by`, aprobación desde fichero ni modo pipe.
Las selecciones vigentes no vuelven a preguntarse. Revocar/sustituir afecta al
evento completo; la interfaz lo indica, por lo que hay que volver a seleccionar
explícitamente los elementos que deban conservarse.

Después de resolver hallazgos, preparar otra solicitud si el gate exige autorización
de continuación. Es una decisión diferente, ligada a su `evaluationHash`:

```powershell
python .opencode/skills/service-workspace/scripts/workspace_cli.py decision-request-prepare mi-servicio
# El usuario revisa el nuevo requestId con review_cli.py review.
python .opencode/skills/service-workspace/scripts/workspace_cli.py resume mi-servicio
python .opencode/skills/service-workspace/scripts/workspace_cli.py preflight mi-servicio
python .opencode/skills/service-workspace/scripts/workspace_cli.py materialize mi-servicio
```

Planificación/consolidación siguen siendo necesarias; estos comandos no inventan
planes. Continuación no autoriza Maven, DB ni despliegue. Una revisión no puede
cambiar `unsupported`/`unknown` a `supported`. El preflight FULL no se modifica.

## Históricos y sobrescrituras

Los YAML históricos se conservan físicamente, pero sus flags/nombres ya no otorgan
autoridad. No se migran automáticamente. Reatestiguar un registro completo:

```powershell
python .opencode/skills/service-workspace/scripts/workspace_cli.py decision-request-prepare mi-servicio --kind historical --decision ID-HISTORICO
# Revisar con review_cli: se muestra el registro íntegro y sus machineEffects.
```

Para un archivo manual incluido en el plan:

```powershell
python .opencode/skills/service-workspace/scripts/workspace_cli.py decision-request-prepare mi-servicio --kind overwrite --path src/main/java/paquete/Clase.java
# Revisar con review_cli. Cambio posterior del archivo o del plan invalida el permiso.
```

Se liga a outputDirectory, path, bytes actuales, plan y worktree. Nunca se permite
autorizar `application*.properties`. No se modifican outputs al revisar.
`gate-resolve`, `gate-authorize`, `protect-authorize` y sus antiguos escritores
Python fallan explícitamente sin escribir. No existe fallback permisivo.

## Consulta, revocación y sustitución

```powershell
python .opencode/skills/service-workspace/scripts/review_cli.py status mi-servicio
python .opencode/skills/service-workspace/scripts/review_cli.py revoke mi-servicio review-HASH
python .opencode/skills/service-workspace/scripts/review_cli.py review mi-servicio request-HASH --supersedes review-HASH-ANTERIOR
python .opencode/skills/service-workspace/scripts/workspace_cli.py decision-request-status mi-servicio request-HASH
python .opencode/skills/service-workspace/scripts/workspace_cli.py decision-request-stale mi-servicio
```

Los eventos se añaden en `decision-reviews/review-<hash>.yml`, con secuencia,
referencia previa, contexto, selección individual, alcance y objetivos de
revocación/sustitución. Publicación exclusiva y lock de escritor; un lock huérfano
requiere inspección manual. Los eventos no son firmas. Un historial malformado o
conflictivo falla cerrado. Los consumidores reconstruyen la vigencia, no confían
en `gate.yml` ni en una petición autoconsistente.

## Contratos y dependencias

Las solicitudes 2A v1 siguen siendo legibles y nunca autorizan. Solicitudes v2
añaden alternativas con `binding` tipado: resolve-finding, resume,
historical-decision u overwrite. Una alternativa v1 sin binding no es aprobable.
Los IDs individuales/grupales siguen siendo deterministas; reordenar no cambia
su identidad. La revisión usa un contexto factual **v2**, separado del contexto
de petición v1: no incluye resultados del gate ni planes/specs HTTP derivados,
evitando que consolidar invalide por sí solo la revisión que lo permitió.
Incluye fuentes vivas, arquetipo, evidencia, hallazgos, revisión semántica,
registros históricos y cobertura. Batch incluye el IR Sparx normalizado.
No incluye reloj, estado operativo del checkpoint o eventos de revisión.
Los timestamps de metadatos conocidos se excluyen; cambiar bytes de una fuente
original sí invalida conservadoramente. El closure de fuentes es el declarado
por los artefactos 2A, no una demostración de completitud semántica.

Reconciliación/materialización validan las referencias a decisiones históricas;
los consolidadores que aplican todo el registro exigen revisión de ese registro.
Las dependencias documentadas se conservan mediante el contexto y las citas; no
se introduce un motor general de reglas/autonomía. Si se corrige una fuente o
evidencia, preparar una solicitud nueva, no editar la vieja.

## Worktrees

Por defecto todo es local al worktree. Para una decisión **funcional** únicamente,
el usuario puede revisar con `--functional-common-git`; la adopción en otro
worktree es manual:

```powershell
python .opencode/skills/service-workspace/scripts/review_cli.py import-functional mi-servicio C:/ruta/worktree-origen review-HASH
```

Requiere mismo directorio Git común local y contexto semántico exacto. Ni rama ni
remote prueban identidad. No hay portabilidad automática de continuación,
sobrescritura, publicación o ejecución. Revocación en el origen no se sincroniza
automáticamente con una adopción local: cada historial debe revisarse/revocarse
explícitamente. No es un ledger distribuido.

## Permisos OpenCode V2

Los siete agentes usan `permissions` nativo ordenado (última coincidencia gana).
Se deniegan interfaz/escritor manual y comandos legacy en shell, edición de
historial y archivos de autoridad, y Code Mode `execute`. Los subagentes tienen
sus propias restricciones de delegación. El orquestador permite subcomandos
seguros explícitos del CLI en lugar del directorio completo. El runner rechaza
scripts fuera de skills/scripts y los escritores manuales. Otros comandos no
permitidos requieren revisión de herramientas; no es aislamiento del SO ni
defensa frente a código deliberadamente ofuscado bajo el mismo usuario.
