# Explicit JDBC binding v1 (package 5)

The `war-jdbc-callablestatement-junit4` backend remains Java 8 / WAR / Oracle
CallableStatement / JNDI / SLF4J / mutable POJO / JUnit4. It never selects JPA,
ActivityLogger or Checkstyle. The selected archetype still owns its templates,
technical utilities, configuration and style. This change is not an archetype
baseline revision and does not regenerate existing services.

## Inputs and source ownership

Each normalized service-spec operation must declare `jdbcBinding`; planning input
must declare `technical.jdbcNames` with `dao`, `repository`, `service`, `controller`
(four distinct Java class identifiers). These are target technical identity,
not functional rules. Missing names are technical errors, not guessed defaults.

`jdbcBinding` is a closed dictionary with exactly:

- `version: 1` and nonempty `evidence` citations to target-local reviewed sources.
- `envelope`: audit=responseAudit, data=responseData, code=codigoRespuesta,
  message=mensajeRespuesta, transaction=idTransaccion. Other envelopes stop.
- `policies`: validation=required-query-nonempty, absentBody=empty-request,
  successMessage=procedure-message, invalidParameterPlaceholder=[PARAMETROS],
  procedureMessagePlaceholder=[PO_MSG_RESPUESTA(Act.2.0)]. Each policy must be
  explicitly supported by evidence; API `required` alone does not prove nonempty.
- `activities`: explicit `validate` and `persist` activity names.
- `outcomes`: `success` (String API code) and invalidParameters/procedureFailure/
  timeout/unavailable, each with explicit String `code` and `message`.
- `procedure`: the explicit structure below.

The semantic analyzer/reviewer must obtain business values from Sparx and mappings
from the contract plus behavior evidence. The planner does not reinterpret prose,
infer row cardinality or approve citations. The existing consistency gate remains
mandatory, and new/changed specs invalidate old review/hash bindings. Live citation
grounding and normalized input/consolidation adapters belong to package 7; a
nonempty citation alone is not proof of semantic correctness or human approval.

## Procedure shape and supported scope

Fields are name, inputs, codeOutput, messageOutput, cursor, columns, rowTarget,
columnMapping, singleRowOnly, parameterOrder, successCode, requireRows,
unmappedFields, outputSqlType, exceptionPolicy. No unknown fields are accepted.

- `name`: PACKAGE.PROCEDURE or OWNER.PACKAGE.PROCEDURE.
- `inputs`: ordered dictionaries `{parameter, source, origin, javaType}`;
  origin=request/header (header denotes a value carried in the internal Cabecera;
  HTTP location remains query). Only String/Integer inputs are supported.
- `parameterOrder`: exact list of input parameter names, then codeOutput,
  messageOutput and optional cursor. An alternate order is unsupported, not
  silently reordered. Code/message OUT SQL type must explicitly be VARCHAR.
- `cursor`: explicit SQL output parameter or null. `columns`: unique column names.
  No cursor is manufactured from a column list.
- `rowTarget`: `{property, many, wrapperProperty, rowClass, listItemClass}`;
  either a single object, or a list of single-object wrappers. For a single
  object, `singleRowOnly: true` explicitly chooses the first row and
  `requireRows: true` is mandatory. List extraction explicitly uses all rows.
- `columnMapping`: `{field, javaType, column}`, String/Integer only. Exact supplied
  mappings are used even when names differ. No prefix/name heuristics.
- `unmappedFields`: explicit list of response fields intentionally left null;
  all row fields must be mapped or listed, never implicitly dropped.
- `successCode` is the procedure code compared, separately from the API success
  code. `requireRows` is the explicit nonempty cursor predicate.
- `exceptionPolicy: sql-timeout-otherwise-unavailable` is explicit; other exception
  semantics/types stop rather than inheriting target-specific behavior.

The current renderer only supports one complete behavior action, POST, one JSON
request type, HTTP 200 JSON response and the envelope above. It accepts the known
String query names accept/aplicacion/idTransaccion/msgid/timestamp/userId, all
declared required, including idTransaccion; other shapes fail explicitly. Required
body, schema constraints unsupported by this backend and incomplete operations
stop. Such limits describe the backend, not requirements for all archetypes.

## External properties and migration

Procedure components/timeouts use operation-scoped `bd.jdbc.<operationId>.*` keys;
response keys are operation-scoped `ws.<operationId>.*`, preventing one operation's
owner/outcomes overwriting another. The archetype's existing configuration remains
intact; unused corporate baseline keys are not evidence for a target procedure.
JNDI and utility/style conventions still come from the selected archetype.

Old JDBC plans with inferred codes, procedure order, mapping or target-specific
stubs are explicitly unsupported. They are not silently migrated, rewritten or
deemed approved. Replanning requires current evidence-backed bindings. In
particular D-C/D-E/D-F/D-G of claro-post-atencion remain in that workspace only;
this backend does not automatically apply, repeal or reinterpret those decisions.
Existing output and its approved partial implementation are untouched. Supporting
that partial mode again requires a separately implemented and explicitly validated
capability; strict completeness is never fabricated.

## Evidence

`tests/test_jdbc_independence.py` creates temporary Stock and Invoice services
without reading reference sources. It tests unrelated names/codes/mappings,
explicit-order failures, missing bindings/names, separate operation owners,
legacy-plan rejection, no-write-on-error and deterministic pure rendering.
JDK parsing checks syntax only, not compilation, dependencies, JUnit execution,
Maven, Checkstyle, Oracle, deployment or runtime compatibility.
