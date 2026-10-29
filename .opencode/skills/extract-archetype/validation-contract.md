# Extraction validation, package 4

`scripts/validate_inventory.py <archetype>` is read-only and independent of
planner/backend availability. It does not select another archetype or read a
reference project's properties. UTF-8 YAML duplicate keys are errors.

## Shared checks

- Template inventory equals files, with unique safe relative paths; symlinks fail.
- Parameter tokens and affected-file declarations agree, including filename tokens.
- Template evidence IDs exist; decision IDs are registered and documented.
- Declared utilities and configuration templates exist in the inventory.
- Direct dependencies/plugins match declared build inventory, preserving order,
  versions, scopes, optional/type/classifier fields. Declaration does not imply use.
- Unknown manifest schemas fail explicitly. A fourth technology needs no backend
  to validate its extraction inventory.

`identity` manifests use `@@TOKEN@@`. The read-only legacy adapter accepts the
existing claro-spring-ms `template_inventory` and `__TOKEN__` dialect, directory
parameter scopes and Maven Wrapper's three own identifiers. Protected properties
are excluded before content access; their content is never validated.

## Additional evidence required

The profile validator retains reference POM comparison (including plugins,
configuration, executions, profiles and repositories), dependency-use inventory,
technical/domain separation, utility-method disposition, source fidelity and
secret/domain checks. Shared relational checks alone are not extraction approval.
Source ownership and classification remain evidence-based agent review; this
validator does not infer classifications from filenames or method names.

## Existing metadata repairs and findings

Java 8: J8-D-008/009 are now registered and `affectedFiles` includes the already
approved ClaroUtil, properties.config.j2 and JNDI templates. No template behavior
changes. Java structural checks use package/file relations instead of assuming
every class is servlet.config. The historic whole-input/reference fingerprint
cannot prove this reference independently; it remains recorded, with identity
reported unverified. The exact reference POM SHA check is retained.

Legacy claro-spring-ms: BASE_PACKAGE_PATH also occurs in the test template path,
outside the declared main-source directory scope. The common validator reports
this metadata mismatch; it does not silently modify the frozen baseline or
pretend the check passed. Full POM fidelity remains its profile's responsibility.

No Maven, Java compilation, runtime or remote verification is claimed.
