"""Materializer v2 (functional layer): typed components, rules from the plan, assumptions, unsupported patterns, compile check (synthetic services, temp dirs)."""
from pathlib import Path
import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synth as fx
import full_materializer as mz
import consistency_gate as gate
import file_protection as fp
import validate_generated_service as vg
import style_lint as sl

SCRIPTS = HERE.parent / 'scripts'
INV = 'src/main/java/com/acme/inventory/core/'
BIL = 'src/main/java/org/example/billing/'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = fx.make_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def gen(self, name, **kw):
        fx.ready_service(self.repo, name, **kw)
        mz.materialize(self.repo, name)
        return self.repo / 'output' / name

    def text(self, out, rel):
        return (out / rel).read_text(encoding='utf-8')

    def refused(self, name='inventory-service', **kw):
        fx.ready_service(self.repo, name, **kw)
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, name)
        self.assertFalse((self.repo / 'output' / name).exists())          # a refused generation writes nothing at all
        return caught.exception


class ComponentTests(Base):
    def test_every_functional_component_type_is_generated_for_both_service_shapes(self):
        for name, base in (('inventory-service', INV), ('billing-service', BIL)):
            out = self.gen(name)
            plan = yaml.safe_load((self.repo / f'.factory/services/{name}/implementation-plan.yml').read_bytes())
            planned = {f['path'] for f in plan['files']['generate'] if f['action'] == 'create' and f['componentType'] in mz.SUPPORTED}
            self.assertEqual({p for p in planned if (out / p).is_file()}, planned)
            self.assertTrue({'contract-dto', 'contract-api-interface', 'controller-implementation', 'application-service-contract', 'application-service-implementation',
                             'business-validator', 'explicit-contract-data-mapper', 'jpa-specification', 'central-contract-error-advice'} <= {f['componentType'] for f in plan['files']['generate']})

    def test_dtos_are_generated_from_the_models_with_presence_tracking_only_for_patch_requests(self):
        out = self.gen('inventory-service')
        patch = self.text(out, INV + 'dto/request/PatchItemRequest.java')
        create = self.text(out, INV + 'dto/request/CreateItemRequest.java')
        self.assertIn('private final Set<String> suppliedFields = new LinkedHashSet<>();', patch)
        self.assertEqual(patch.count('suppliedFields.add('), 4)
        self.assertNotIn('suppliedFields', create)
        for text in (patch, create):
            self.assertIn('@JsonInclude(JsonInclude.Include.NON_NULL)', text)
            self.assertEqual(text.count('@JsonSetter(nulls = Nulls.FAIL)'), 4)
        self.assertIn('@NotNull\n    @Size(min = 2, max = NAME_SIZE_MAX)\n    private String name;', create)
        self.assertIn('private static final int NAME_SIZE_MAX = 40;', create)
        self.assertIn('@Schema(allowableValues = {"0", "1"})', create)
        response = self.text(out, INV + 'dto/response/SearchItemsData.java')
        self.assertIn('private List<ItemView> items;', response)
        self.assertNotIn('JsonSetter', response)
        self.assertEqual(self.text(out, INV + 'dto/response/ItemView.java').count('private String'), 5)

    def test_validator_uses_typed_commands_and_no_untyped_maps_or_casts(self):
        out = self.gen('inventory-service')
        for rel in ('validation/ItemValidator.java', 'dto/mapper/ItemMapper.java', 'service/impl/ItemServiceImpl.java'):
            text = self.text(out, INV + rel)
            self.assertNotIn('Map<', text, rel)
            self.assertNotRegex(text, r'\((Integer|BigDecimal|Long|String)\)\s*\w', rel)
        validator = self.text(out, INV + 'validation/ItemValidator.java')
        self.assertIn('public record CreateItemCommand(', validator)
        self.assertIn('Field<BigDecimal> sku', validator)
        self.assertIn('public record Field<T>(boolean supplied, T value)', validator)
        self.assertIn('SKU_INTEGER_DIGITS = 6;', validator)          # NUMBER(8,2) from the plan's column type
        self.assertIn('SKU_SCALE = 2;', validator)
        self.assertIn('Set.of("0", "1")', validator)
        self.assertIn('field(supplied, "sku", () -> toBoundedDecimal(request.getSku(), "sku", SKU_INTEGER_DIGITS, SKU_SCALE))', validator)
        billing = self.gen('billing-service')
        self.assertIn('TOTAL_INTEGER_DIGITS = 8;', self.text(billing, BIL + 'validation/InvoiceValidator.java'))      # NUMBER(10,2): independent of the first service

    def test_rules_come_from_the_plan_rules_only(self):
        out = self.gen('inventory-service')
        validator = self.text(out, INV + 'validation/ItemValidator.java')
        self.assertIn('if ((limit == null) != (offset == null))', validator)                          # pagination-pairing
        self.assertIn('if (request.getSku() != null && (request.getNotes() == null))', validator)     # conditional-required: when sku is supplied requires notes
        self.assertIn('if (supplied.isEmpty())', validator)                                           # at-least-one-of
        billing = self.text(self.gen('billing-service'), BIL + 'validation/InvoiceValidator.java')
        self.assertNotIn('limit', billing)
        self.assertNotIn('conditionally required', billing)
        self.assertNotIn('supplied.isEmpty()', billing)

    def test_mapper_conversions_audit_values_and_enum_guard(self):
        out = self.gen('inventory-service')
        mapper = self.text(out, INV + 'dto/mapper/ItemMapper.java')
        self.assertIn('entity.setName(command.name());', mapper)
        self.assertIn('entity.setCreatedBy(auditUser);', mapper)
        self.assertIn('if (command.sku().supplied()) {\n            entity.setSku(command.sku().value());', mapper)
        self.assertIn('entity.setUpdatedBy(auditUser);', mapper)
        self.assertIn('result.setSku(text(row.getSku()));', mapper)
        self.assertIn('checked(text(row.getState()), SEARCH_ITEMS_ALLOWED_STATE)', mapper)
        self.assertIn('SEARCH_ITEMS_SUCCESS_MESSAGE = "Consulta exitosa"', mapper)
        self.assertIn('toPlainString', mapper)

    def test_specification_follows_the_filter_policy_of_each_service(self):
        spec = self.text(self.gen('inventory-service'), INV + 'repository/ItemSpecifications.java')
        self.assertIn('builder.or(predicates.toArray', spec)
        self.assertIn('builder.disjunction()', spec)
        self.assertIn('contains(predicates, builder, root, "name", criteria.name());', spec)
        self.assertIn('builder.equal(root.get("sku"), criteria.sku())', spec)
        other = self.text(self.gen('billing-service'), BIL + 'repository/InvoiceSpecifications.java')
        self.assertIn('builder.and(predicates.toArray', other)
        self.assertIn('builder.conjunction()', other)
        self.assertNotIn('contains(predicates, builder, root, "', other)               # exact filters only

    def test_endpoints_and_http_contract_of_each_service(self):
        out = self.gen('inventory-service')
        api = self.text(out, INV + 'controller/ItemApi.java')
        self.assertIn('@GetMapping(path = "/api/v1/items", produces = {"application/json"})', api)
        self.assertIn('@PatchMapping(path = "/api/v1/items/{id}", consumes = {"application/json"}, produces = {"application/json"})', api)
        self.assertIn('@Validated', api)                                           # parameters carry declared constraints
        self.assertIn('@Min(1) @Max(SEARCH_ITEMS_LIMIT_MAX) @RequestParam(name = "limit", required = false) Integer limit', api)
        self.assertIn('@Size(min = 1) @PathVariable(name = "id", required = true) String id', api)
        self.assertIn('@Valid @RequestBody PatchItemRequest request', api)
        self.assertIn('@ApiResponse(responseCode = "409"', api)
        controller = self.text(out, INV + 'controller/impl/ItemController.java')
        self.assertIn('new RequestHeaders(xCorrelationId, xUserId)', controller)
        self.assertIn('log.info("searchItems - transactionId: {}", xCorrelationId);', controller)
        self.assertIn('service.patchItem(headers, id, request)', controller)
        billing_api = self.text(self.gen('billing-service'), BIL + 'controller/InvoiceApi.java')
        self.assertIn('@Validated', billing_api)
        self.assertIn('@Pattern(regexp = "^[A-Za-z0-9 -]+$")', billing_api)
        self.assertNotIn('"409"', billing_api)
        self.assertNotIn('"504"', billing_api)
        self.assertIn('@GetMapping(path = "/billing/v2/invoices"', billing_api)
        billing_controller = self.text(self.repo / 'output' / 'billing-service', BIL + 'controller/impl/InvoiceController.java')
        self.assertIn('new RequestHeaders(xTraceId, xUser, xApp)', billing_controller)

    def test_exception_advice_takes_statuses_and_texts_only_from_the_contract_examples(self):
        handler = self.text(self.gen('inventory-service'), INV + 'exception/GlobalExceptionHandler.java')
        for expected in ('"ITEM_SEARCH_ERROR"', '"ITEM_CREATE_ERROR"', '"ITEM_PATCH_ERROR"', '"Missing or invalid parameters."', '"Nothing found."', '"Internal failure [ERROR_DETAIL]"',
                         'error.setType("MissingParameters");', 'error.setSubType("T1");', 'case GATEWAY_TIMEOUT ->'):
            self.assertIn(expected, handler)
        self.assertIn('case CONFLICT -> {', handler)
        conflict = handler.split('case CONFLICT -> {')[1].split('}')[0]
        self.assertIn('getReasonPhrase', conflict)                      # 409 has no example in the contract: no invented type, subtype or detail
        self.assertNotIn('setType', conflict)
        self.assertIn('case "GET" -> status == HttpStatus.BAD_REQUEST', handler)       # a status a method does not declare becomes an internal error
        other = self.text(self.gen('billing-service'), BIL + 'exception/GlobalExceptionHandler.java')
        self.assertNotIn('GATEWAY_TIMEOUT', other.split('declared(')[1].split('private void')[0] if False else other.split('private HttpStatus declared')[1].split('private void')[0])
        self.assertIn('"Bad invoice request."', other)
        self.assertNotIn('Missing or invalid', other)

    def test_logging_follows_the_archetype_pattern_with_plan_constants(self):
        out = self.gen('inventory-service')
        service = self.text(out, INV + 'service/impl/ItemServiceImpl.java')
        for expected in ('ConstanApi.ACT1_VALIDAR_ENTRADA', 'ConstanApi.ACT2_CONSULTAR', 'ConstanApi.ACT2_CREAR', 'ConstanApi.ACT2_ACTUALIZAR', 'ConstanApi.LOG_TIMEOUT_ACT2_CREAR',
                         'ConstanApi.LOG_ERROR_DATOS_ACT2_ACTUALIZAR', 'ActivityLogger.inicioActividad(log, menTran, actividad);', 'ActivityLogger.finActividad(log, menTran, actividad);',
                         'private void logSearch(', 'private void logCreate(', 'private void logUpdate(', 'NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] "', '@Slf4j'):
            self.assertIn(expected, service)
        self.assertEqual(service.count('ActivityLogger.logContenido('), 2)                           # only operations with a request body
        self.assertIn('PatchItemRequest.class', service)
        self.assertNotIn('ACT2_LISTAR', service)
        constants = self.text(out, INV + 'utils/ConstanApi.java')
        self.assertIn('LOG_TIMEOUT_ACT2_ACTUALIZAR', constants)
        handler = self.text(out, INV + 'exception/GlobalExceptionHandler.java')
        self.assertIn('TRANSACTION_HEADER = "x-correlation-id"', handler)
        self.assertIn('ConstanApi.ACT1_VALIDAR_ENTRADA', handler)

    def test_outcome_behavior_comes_from_declared_statuses(self):
        out = self.gen('inventory-service')
        service = self.text(out, INV + 'service/impl/ItemServiceImpl.java')
        self.assertEqual(service.count('throw new ServiceOperationException(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);'), 2)      # search empty + patch target missing
        self.assertIn('entity.setCreatedAt(LocalDateTime.now(clock));', service)
        self.assertIn('entity.setUpdatedAt(LocalDateTime.now(clock));', service)
        self.assertIn('repository.findAll(specification, new OffsetLimitRequest(criteria.offset(), criteria.limit(), ORDER)).getContent()', service)
        billing = self.text(self.gen('billing-service'), BIL + 'service/impl/InvoiceServiceImpl.java')
        self.assertNotIn('OffsetLimitRequest', billing)
        self.assertNotIn('Optional', billing)
        self.assertNotIn('findById', billing)

    def test_no_domain_specific_names_leak_between_services_or_from_the_reference(self):
        a, b = self.gen('inventory-service'), self.gen('billing-service')
        text_a = '\n'.join(d.decode('utf-8') for d in fx.tree(a).values())
        text_b = '\n'.join(d.decode('utf-8') for d in fx.tree(b).values())
        for word in ('Invoice', 'invoice', 'billing'):
            self.assertNotIn(word, text_a)
        for word in ('ItemEntity', 'ItemView', 'inventory', 'sku', 'SKU'):
            self.assertNotIn(word, text_b)
        for word in ('Mailing', 'mailing', 'emailBody', 'MAILINGINFORMATION'):
            self.assertNotIn(word, text_a + text_b)
        for source in SCRIPTS.glob('*.py'):
            self.assertNotRegex(source.read_text(encoding='utf-8').lower(), r'mailing|emailbody')


class QualityTests(Base):
    def test_functional_output_is_clean_for_the_preventive_lint_and_valid_for_the_generic_validator(self):
        for name in fx.SERVICES:
            out = self.gen(name)
            lint = sl.lint_project(out)
            self.assertEqual(lint['findings'], [], lint['findings'][:3])
            result = vg.validate(self.repo, name)
            self.assertEqual(result['status'], 'passed', result['violations'])
            self.assertEqual(result['checkstyleOfficial'], 'unverified')

    def test_validator_detects_a_service_that_dropped_the_corporate_logging(self):
        out = self.gen('inventory-service')
        service = out / (INV + 'service/impl/ItemServiceImpl.java')
        service.write_text(service.read_text(encoding='utf-8').replace('ActivityLogger.', 'Other.'), encoding='utf-8')
        failed = {v['check'] for v in vg.validate(self.repo, 'inventory-service')['violations']}
        self.assertIn('manifestRowsMatchDisk', failed)
        self.assertTrue(any(c.startswith('serviceLogging:') for c in failed))

    @unittest.skipUnless(shutil.which('javac') and (Path.home() / '.m2' / 'repository').is_dir(), 'javac or the local Maven cache is not available')
    def test_generated_java_compiles_with_javac_against_local_jars_without_running_maven(self):
        jars = collect_jars()
        lombok = [j for j in jars if 'projectlombok' in j.replace('\\', '/')]
        if not lombok or len(jars) < 20:
            self.skipTest('required jars are not in the local cache')
        for name in fx.SERVICES:
            out = self.gen(name)
            args = self.repo / f'{name}.args'
            classes = self.repo / f'{name}-classes'
            assembled = {r['path'] for r in yaml.safe_load((out / '.generation-manifest.yml').read_bytes())['fileInventory'] if r.get('componentType') == 'project-assembly'}       # compiled by Maven, not by this javac check
            sources = [str(p).replace('\\', '/') for p in (out / 'src/main/java').rglob('*.java') if p.relative_to(out).as_posix() not in assembled]
            args.write_text('\n'.join(['-parameters', '-proc:full', '-processorpath', f'"{lombok[0]}"'.replace('\\', '/'), '-d', f'"{classes}"'.replace('\\', '/'), '-cp',
                                       '"' + os.pathsep.join(j for j in jars if 'jpamodelgen' not in j).replace('\\', '/') + '"'] + [f'"{s}"' for s in sources]), encoding='utf-8')
            done = subprocess.run(['javac', f'@{args}'], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr[-1500:])


def collect_jars():
    m2 = Path.home() / '.m2' / 'repository'
    prefixes = ('org.springframework', 'jakarta', 'com.fasterxml.jackson', 'org.hibernate', 'io.swagger', 'org.projectlombok', 'org.slf4j', 'org.apache.tomcat', 'ch.qos', 'io.micrometer', 'org.aspectj')
    best = {}

    def key(v):
        return [int(x) if x.isdigit() else 0 for x in re.split(r'[.\-]', v)]
    for jar in m2.rglob('*.jar'):
        art, ver = jar.parent.parent.name, jar.parent.name
        group = str(jar.parent.parent.parent.relative_to(m2)).replace('\\', '.').replace('/', '.')
        if jar.name == f'{art}-{ver}.jar' and group.startswith(prefixes) and ((group, art) not in best or key(ver) > key(best[(group, art)][0])):
            best[(group, art)] = (ver, str(jar))
    return [j for _, j in best.values()]


class AssumptionTests(Base):
    def test_a_complete_generation_records_where_every_rule_comes_from(self):
        def cite(plan):
            plan['api']['operations'][1]['modelMappings'][0]['column']['aliasDecisionId'] = 'human-reviewed-x'
        fx.ready_service(self.repo, 'inventory-service', mutate=cite)
        ws = self.repo / '.factory/services/inventory-service'
        fx.wfx.dump(ws / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [{'decisionId': 'human-reviewed-x', 'humanReviewed': True}]})
        fx.wfx.simulate_manual(self.repo, 'inventory-service', kind='historical', decision_id='human-reviewed-x')
        fx.wfx.simulate_manual(self.repo, 'inventory-service')
        mz.materialize(self.repo, 'inventory-service')
        register = yaml.safe_load((ws / 'assumptions-register.yml').read_bytes())
        sources = {e['source'] for e in register['entries']}
        self.assertEqual(sources, {'sparx', 'swagger', 'archetype-technical', 'human-decision'})
        self.assertNotIn('pending-functional', sources)
        self.assertTrue(any(e['id'] == 'human-reviewed-x' for e in register['entries']))
        self.assertTrue(any(e['id'] == 'createItem:C1' and e['source'] == 'sparx' for e in register['entries']))
        self.assertEqual(register, yaml.safe_load((ws / 'assumptions-register.yml').read_bytes()))

    def test_a_decision_the_plan_relies_on_must_exist_and_be_a_human_review(self):
        def cite(plan):
            plan['api']['operations'][0]['query']['filterPolicy']['decisionId'] = 'human-reviewed-missing'
        error = self.refused(mutate=cite)
        self.assertEqual(error.kind, 'missing-decision')

    def test_pending_functional_assumptions_stop_the_generation_without_writing(self):
        error = self.refused(derived_assumptions=[{'id': 'empty-filter-semantics', 'classification': 'functional', 'blocker': True, 'statement': 'blank filters'},
                                                  {'id': 'timezone', 'classification': 'technical-implementation-choice', 'blocker': False}])
        self.assertEqual(error.kind, 'pending-functional-assumptions')
        self.assertEqual(error.details['pending'], ['empty-filter-semantics'])
        self.assertFalse((self.repo / '.factory/services/inventory-service/assumptions-register.yml').exists())

    def test_technical_choices_alone_do_not_block(self):
        fx.ready_service(self.repo, 'billing-service', derived_assumptions=[{'id': 'clock', 'classification': 'technical-implementation-choice', 'blocker': False}])
        self.assertEqual(mz.materialize(self.repo, 'billing-service')['status'], 'complete')

    def test_planning_blockers_stop_the_generation(self):
        error = self.refused(mutate=lambda plan: plan.update({'planningBlockers': [{'id': 'x'}]}))
        self.assertEqual(error.kind, 'pending-functional-assumptions')


class UnsupportedRulesTests(Base):
    """Anything the plan asks for beyond the supported pattern stops the WHOLE generation with a reason; nothing is approximated."""

    def case(self, mutate, expected_words):
        error = self.refused(mutate=mutate)
        self.assertEqual(error.kind, 'unsupported')
        reasons = ' '.join(u['reason'] for u in error.details['unsupported'])
        for word in expected_words:
            self.assertIn(word, reasons)

    def op(self, plan, index=0):
        return plan['api']['operations'][index]

    def test_unknown_validation_rule_kind_is_not_invented(self):
        self.case(lambda p: self.op(p)['validation'][0]['rules'].append({'ruleId': 'X', 'kind': 'cross-field-checksum'}), ['cross-field-checksum'])

    def test_unsupported_action_kind_http_method_and_status(self):
        self.case(lambda p: self.op(p, 1).update({'actionKind': 'delete'}), ['delete'])
        self.case(lambda p: self.op(p, 1).update({'method': 'TRACE'}), ['TRACE'])
        self.case(lambda p: self.op(p, 0).update({'effectiveStatusCodes': ['200', '400', '404', '418']}), ['418'])

    def test_missing_success_message_in_the_contract_is_not_invented(self):
        def drop(plan):
            del self.op(plan, 1)['contract']['responses']['200']['content']['application/json']['example']
        self.case(drop, ['success message'])

    def test_empty_result_and_not_found_outcomes_that_the_contract_does_not_declare_are_not_invented(self):
        self.case(lambda p: self.op(p, 0).update({'effectiveStatusCodes': ['200', '400', '500']}), ['404'])
        self.case(lambda p: self.op(p, 2).update({'effectiveStatusCodes': ['200', '400', '500']}), ['404'])

    def test_write_responses_with_extra_fields_need_an_approved_decision(self):
        def extra(plan):
            for m in plan['models']:
                if m['name'] == 'CreateItemResponse':
                    m['fields'].append({'name': 'data', 'javaType': 'String', 'required': False, 'validationAnnotations': [], 'declaredConstraints': {}})
        self.case(extra, ['approved decision'])

    def test_unsupported_parameters_conversions_and_filters(self):
        def enum_param(plan):
            self.op(plan, 0)['contract']['parameters']['query'][0]['schema']['enum'] = ['1']
        self.case(enum_param, ['enum'])
        self.case(lambda p: self.op(p, 0)['contract']['parameters'].update({'cookie': [{'name': 'c'}]}), ['cookie'])
        self.case(lambda p: self.op(p, 0)['query']['filters'][0].update({'effectiveMatch': 'regex'}), ['regex'])
        self.case(lambda p: self.op(p, 0)['query']['filters'][3].update({'effectiveMatch': 'contains'}), ['String property'])

    def test_second_search_operation_and_missing_header_roles_and_error_model(self):
        def second(plan):
            clone = copy.deepcopy(self.op(plan, 0))
            clone['operationId'] = 'searchAgain'
            plan['api']['operations'].append(clone)
            plan['activityLogging']['operations'].append(dict(copy.deepcopy(plan['activityLogging']['operations'][0]), operationId='searchAgain'))
        self.case(second, ['more than one search'])
        self.case(lambda p: self.op(p, 0)['contract']['parameters']['header'].pop(0), ['header'])

        def no_detail(plan):
            plan['models'][0]['fields'] = [f for f in plan['models'][0]['fields'] if f['name'] != 'detail']
        self.case(no_detail, ['error model'])

    def test_unsupported_dto_features(self):
        def bad_annotation(plan):
            plan['models'][3]['fields'][0]['validationAnnotations'] = ['@CustomRule']
        self.case(bad_annotation, ['@CustomRule'])

        def bad_type(plan):
            plan['models'][3]['fields'][0]['javaType'] = 'Map<String,String>'
        self.case(bad_type, ['Map<String,String>'])

    def test_activity_flows_other_than_validation_plus_behavior_are_refused(self):
        def three(plan):
            plan['activityLogging']['operations'][0]['activitySequence'].append({'order': 3, 'constant': 'ACT3_X', 'role': 'behavior'})
        self.case(three, ['validation+behavior'])

    def test_planned_tests_make_the_whole_generation_stop_instead_of_producing_an_incomplete_service(self):
        error = self.refused(with_unsupported=True)
        self.assertEqual({u['componentType'] for u in error.details['unsupported']}, {'repository-persistence-test'})


class SecurityAndDeterminismTests(Base):
    def test_functional_generation_is_deterministic_idempotent_and_independent(self):
        hashes = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as other:
                repo = fx.make_repo(Path(other))
                row = []
                for name in fx.SERVICES:
                    fx.ready_service(repo, name)
                    row.append(mz.materialize(repo, name)['payloadTreeSha256'])
                hashes.append(row)
        self.assertEqual(hashes[0], hashes[1])
        self.assertNotEqual(hashes[0][0], hashes[0][1])
        fx.ready_service(self.repo, 'inventory-service')
        first = mz.materialize(self.repo, 'inventory-service')
        snapshot = fx.tree(self.repo / 'output' / 'inventory-service')
        second = mz.materialize(self.repo, 'inventory-service')
        self.assertEqual((second['written'], fx.tree(self.repo / 'output' / 'inventory-service')), ([], snapshot))
        self.assertEqual(first['payloadTreeSha256'], second['payloadTreeSha256'])

    def test_a_blocked_service_with_a_complete_functional_plan_writes_nothing(self):
        ws = fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        before = fx.tree(ws.dir)
        with self.assertRaises(gate.GateError):
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(sorted((self.repo / 'output').rglob('*.java')) if (self.repo / 'output').exists() else [], [])
        self.assertEqual(fx.tree(ws.dir), before)

    def test_manually_edited_functional_files_are_preserved_and_block_the_run(self):
        out = self.repo / 'output' / 'inventory-service'
        fx.ready_service(self.repo, 'inventory-service')
        mz.materialize(self.repo, 'inventory-service')
        service = out / (INV + 'service/impl/ItemServiceImpl.java')
        service.write_text(service.read_text(encoding='utf-8') + '\n// hand written tweak\n', encoding='utf-8')
        manual = service.read_bytes()
        controller = out / (INV + 'controller/impl/ItemController.java')
        controller.write_text(controller.read_text(encoding='utf-8').replace('RestController', 'RestController /*x*/'), encoding='utf-8')
        controller.unlink()                                               # force a rewrite elsewhere
        plan_file = self.repo / '.factory/services/inventory-service/implementation-plan.yml'
        plan = yaml.safe_load(plan_file.read_bytes())
        plan['api']['operations'][1]['successMessage'] = 'ignored'
        plan['api']['operations'][1]['contract']['responses']['200']['content']['application/json']['example']['message'] = 'Another message'
        plan_file.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True), encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(caught.exception.kind, 'protected-files')
        self.assertEqual(service.read_bytes(), manual)
        self.assertFalse(controller.exists())                             # nothing else was written either

    def test_only_the_materializer_can_write_functional_java(self):
        agent = yaml.safe_load((fx.REPO_ROOT / '.opencode/agents/service-generator.md').read_text(encoding='utf-8').split('---')[1])
        import fnmatch
        for path in ('output/example/X.java', 'other.txt'):
            matches = [r['effect'] for r in agent['permissions'] if r['action'] == 'edit' and fnmatch.fnmatchcase(path, r['resource'])]
            self.assertEqual(matches[-1], 'deny')
        source = (SCRIPTS / 'full_materializer.py').read_text(encoding='utf-8')
        self.assertLess(source.index('gate.check_cleared'), source.index('assumption_register(plan, ws)'))
        self.assertLess(source.index('assumption_register(plan, ws)'), source.index('publish(out_dir, ws.dir, payload, manifest_bytes)'))
        import artifact_integrity
        import inspect
        publisher = inspect.getsource(artifact_integrity.publish)
        self.assertLess(publisher.index('prepare(output, workspace, payload)'), publisher.index('write_atomic('))
        self.assertLess(publisher.index('fp.guard_write(output, rel, workspace)'), publisher.index('write_atomic(safe_path(output, rel), data)'))
        self.assertLess(publisher.index('write_atomic(safe_path(output, rel), data)'), publisher.index('write_atomic(safe_path(output, fp.MANIFEST), manifest)'))
        for module in ('java_components.py', 'java_components2.py', 'service_model.py'):
            code = (SCRIPTS / module).read_text(encoding='utf-8')
            self.assertNotRegex(code, r'write_text|write_bytes|open\(|os\.replace')            # renderers are pure: they cannot write files


if __name__ == '__main__':
    unittest.main()
