# Closed batch variant: payment-sync-v1

This additive backend supports the interpreted payment synchronization model on
the selected Java 8 / Spring XML / log4j / JUnit4 shell archetype. It does not
change or re-extract that archetype, introduce an HTTP server, or copy a reference
project. Other batch variants keep their existing contract.

## Scope

The six ordered phases are authentication, collection retrieval, financing
retrieval, quote-number join, installment synchronization and financing completion.
The model carries all five outbound calls, nested JSON types, literal mappings,
documented property defaults, source bindings and separately identified delegated
decisions. JSON null is not the string `NULL`. Empty filtered installments still
reach the completion decision. Automatic retries and redirects are disabled.

`batch_payment_sync_model.py` accepts only the closed interpreted semantic digest;
unknown mappings, algorithms, omissions, snippets and incomplete configuration
fail before output writes. Supporting another interpretation requires a tested
backend extension and a current semantic review, not changing a digest to bypass
an unsupported behavior.

The deterministic `compile_payment_sync_spec.py` converts the specialist's typed
proposal into candidate batch IR. It grants no authority. The normal non-HTTP
consistency gate verifies live sources and a bound semantic review; an explicit
scoped resume review must adopt any delegated assumptions. The implementation
plan, preflight, whole-payload manual-file protection, lock and guarded atomic
materializer remain mandatory. Never edit generated Java directly.

## External prerequisites and honest validation

The authentication REST wire shape is an explicit delegated choice, not a verified
provider contract. Its URL, credentials and timeouts are external configuration.
Operators must confirm compatibility before production. No secret is supplied by
the generator. The shell does not execute SQL or install its own scheduler.

The Maven baseline comparison preserves all inherited dependencies and build
configuration, adding only justified Jackson and Apache HttpClient dependencies.
Inherited external `Lib` artifacts remain build prerequisites even when unused by
this service. No Maven, network, database or deployment execution is implicit.

Offline fixtures in `tests/test_payment_sync_http.py` compile Java with
`javac --release 8` and run 25 generated JUnit4 tests against already cached jars
when explicitly selected. The fixture checks generated Java bytes against the
actual output before execution. Some local framework versions differ from the
baseline; this is not Maven, baseline runtime compatibility or provider testing.
Checkstyle is not applicable to this archetype; JaCoCo coverage remains unverified.
