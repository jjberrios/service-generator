---
name: materialize-service-scaffold
description: Deterministically materializes only plan-authorized scaffold files from service-spec.yml and a versioned archetype, preserving all omit-unresolved exclusions.
---

# Materialize Service Scaffold

Read root `AGENTS.md` first. Use only `.factory/service-spec.yml`,
`.factory/implementation-plan.yml`, `.factory/generation-parameters.yml`, and the
selected archetype directory. Do not read raw OpenAPI/Sparx inputs or the
reference project. Do not generate business behavior, build-unready files, or
deployment resources.

The implementation plan's file statuses and resolved dependency values are the
generation allowlist. The script checks every dependency before rendering,
copies/parameterizes archetype files deterministically, renders contract models
and API interfaces from the approved service spec, creates structural tests,
records omitted items in `.generation-manifest.yml`, and verifies a two-run
temporary output comparison before writing the configured final output.

Run from repository root:

```text
python .opencode/skills/materialize-service-scaffold/scripts/materialize_scaffold.py --verify-determinism
```

The script stops if the target output directory already contains files. It does
not run Maven or generate deployment resources.

After a separate technical-parameter approval enables only Maven build files,
use the build-file-only materializer; it verifies the existing scaffold and
updates only `pom.xml`, `settings.xml`, and the generation manifest:

```text
python .opencode/skills/materialize-service-scaffold/scripts/materialize_build_files.py --verify-determinism
```

It refuses to overwrite existing Maven files, preserves all other output files,
and does not execute Maven.
