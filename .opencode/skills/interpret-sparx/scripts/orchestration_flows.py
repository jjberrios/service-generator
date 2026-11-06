"""Flow table of the orchestration service of the current target and the builder of its `sparx-spec.yml`.

FLOWS is the written interpretation of the authoritative process graph: for every requestTypeId, the ordered steps, the decisions (gateway text that
must exist in the graph) and the compensation chains. `build` verifies every step against the parsed evidence and never approximates: a missing
activity, gateway or code is an InterpretationError.
"""
from pathlib import Path
import html
import re
import yaml

import orchestration_interpretation as oi
from orchestration_interpretation import InterpretationError, fold

ROOT_LANE = 'POST-/api/v1/agreement/financing'

# ----------------------------------------------------------------------------- sub-flows and flows
SYNC = [
    {'t': 'remote', 'key': '4.1', 'sel': ('Sincronizar', '4.1')},
    {'t': 'remote', 'key': '4.2', 'sel': ('Sincronizar', '4.2')},
    {'t': 'remote', 'key': '4.3', 'sel': ('Sincronizar', '4.3')},
    {'t': 'compute', 'key': '4.4', 'sel': ('Sincronizar', '4.4'), 'fail': 'IDF388',
     'ops': [{'fn': 'filter-paid-for-sync', 'args': ['lst:4.3:installments', 'lst:4.2:quoteCobranza', 'prop:propEstadoCuotaPagada'], 'out': 'filteredQuote'}]},
    {'t': 'branch', 'gateway': 'filteredQuote[] > 0', 'when': ('gt', ('size', 'val:4.4:filteredQuote'), 'int:0'),
     'then': [{'t': 'remote', 'key': '4.5', 'sel': ('Sincronizar', '4.5')}], 'else': []},
]
STATE_OK = {'t': 'decide', 'gateway': 'financingStateCodeId (act 4.1) = 2', 'when': ('eq', 'act:4.1:financingStateCodeId', 'prop:propEstadoConfirmada'), 'fail': 'IDF301'}

FLOWS = {
    1: {'name': 'Pre-Financiamiento', 'sparx': '2. Registra Prefinanciamiento', 'prerequisite': None, 'steps': [
        {'t': 'compute', 'key': '2.2.1', 'sel': ('Calcular', '2.2.1'), 'ops': [{'fn': 'subtract', 'args': ['req:debtAmount', 'req:amountInitialQuote'], 'out': 'amountFinanced'}]},
        {'t': 'compute', 'key': '2.2.2', 'sel': ('Calcular', '2.2.2'), 'ops': [{'fn': 'divide-money', 'args': ['val:2.2.1:amountFinanced', 'req:quotesNumber'], 'out': 'quoteAmount'}]},
        {'t': 'compute', 'key': '2.2.3', 'sel': ('Calcular', '2.2.3'), 'ops': [{'fn': 'add', 'args': ['val:2.2.2:quoteAmount', 'req:fixedAmount'], 'out': 'monthlyPayment'}]},
        {'t': 'decide', 'gateway': 'creditLimit (request) >= pagoMensual', 'when': ('ge', 'req:creditLimit', 'val:2.2.3:monthlyPayment'), 'fail': 'IDF401'},
        {'t': 'branch', 'gateway': "saveRequest = 'S'", 'when': ('eq', 'req:saveRequest', 'lit:S'),
         'then': [{'t': 'remote', 'key': '2.3', 'sel': ('Prefinanciamiento', '2.3')}], 'else': []},
        {'t': 'respond', 'data': {'requestCodeId': 'act:2.3:requestCodeId', 'amountFinanced': 'val:2.2.1:amountFinanced', 'quoteAmount': 'val:2.2.2:quoteAmount'}}],
        'comps': [], 'chains': {}},
    2: {'name': 'Financiamiento', 'sparx': '3. Registra Financiamiento', 'prerequisite': None, 'steps': [
        {'t': 'branch', 'gateway': 'isDelivered = 1', 'when': ('eq', 'req:isDelivered', 'int:1'),
         'then': [{'t': 'remote', 'key': 'C3.6', 'sel': ('Confirmar', '3.6')},
                  {'t': 'decide', 'gateway': 'financingStateCodeId (act 3.6) = 1', 'when': ('eq', 'act:C3.6:financingStateCodeId', 'prop:propFinanEstadoSolicitada'), 'fail': 'IDF390'},
                  {'t': 'remote', 'key': 'C3.7', 'sel': ('Confirmar', '3.7')},
                  {'t': 'respond', 'data': {'agreementCodeId': 'req:agreementCodeId'}}],
         'else': [{'t': 'remote', 'key': '3.2', 'sel': ('Financiamiento', '3.2')},
                  {'t': 'decide', 'gateway': 'requestTypeId (act 3.2) = 1', 'when': ('and', ('eq', 'act:3.2:requestTypeId', 'int:1'), ('eq', 'act:3.2:financingStateCodeId', 'prop:propFinanEstadoSolicitada')), 'fail': 'IDF405'},
                  {'t': 'decide', 'gateway': 'agreementCodeId (act 3.2) = nulo/vacio', 'when': ('empty', 'act:3.2:agreementCodeId'), 'fail': 'IDF406'},
                  {'t': 'decide', 'gateway': 'fechaHoy - createAt(act 3.2)', 'when': ('not', ('hours-exceed', 'act:3.2:createdAt', 'cfg:vigenciaRegistroSolicitudEnHoras')), 'fail': 'IDF407'},
                  {'t': 'decide', 'gateway': 'clientCode (request) = clientCode_2 (act 3.2)', 'when': ('eq', 'req:clientCode', 'act:3.2:clientCode'), 'fail': 'IDF408'},
                  {'t': 'decide', 'gateway': 'amountInitialQuote(act 3.2) > 0', 'when': ('not', ('and', ('gt', 'act:3.2:amountInitialQuote', 'int:0'),
                                                                                                      ('or', ('empty', 'req:proofPaymentType'), ('empty', 'req:proofPaymentNumber')))), 'fail': 'IDF409'},
                  {'t': 'remote', 'key': '3.3', 'sel': ('Financiamiento', '3.3')},
                  {'t': 'remote', 'key': '3.4', 'sel': ('Financiamiento', '3.4')},
                  {'t': 'remote', 'key': '3.5', 'sel': ('Financiamiento', '3.5')},
                  {'t': 'respond', 'data': {'agreementCodeId': 'act:3.3:agreementCodeId', 'installments': 'ins:3.5'}}]}],
        'comps': [{'key': 'R3.6', 'sel': ('Financiamiento', '3.6')}, {'key': 'R3.7', 'sel': ('Financiamiento', '3.7')}],
        'chains': {'rollback financiamiento': ['R3.6'], 'revertir solicitud': ['R3.7', 'R3.6'], 'rollback solicitud': []},
        'chainEdges': [('Rollback financiamiento', '3.6. Ejecuta rollback'), ('Revertir Solicitud', '3.7. Revertir Solicitud'), ('3.7. Revertir Solicitud', '3.6. Ejecuta rollback')]},
    3: {'name': 'Pre-Refinanciamiento', 'sparx': '5. Registra Pre refinanciamiento', 'prerequisite': 'sync', 'steps': [
        STATE_OK,
        {'t': 'remote', 'key': '5.2', 'sel': ('Pre Refinanciamiento', '5.2')},
        {'t': 'compute', 'key': '5.3', 'sel': ('Pre Refinanciamiento', '5.3'),
         'ops': [{'fn': 'classify-installments', 'args': ['lst:5.2:quotes', 'prop:propEstadoCuotaNotificada', 'prop:propEstadoCuotaPagada'], 'out': ['notifiedInstallments', 'paidInstallments']}]},
        {'t': 'decide', 'gateway': 'notifiedInstallments[].size > 0', 'when': ('gt', ('size', 'val:5.3:notifiedInstallments'), 'int:0'), 'fail': 'IDF423'},
        {'t': 'decide', 'gateway': 'paidInstallments[].size >= 2', 'when': ('ge', ('size', 'val:5.3:paidInstallments'), 'int:2'), 'fail': 'IDF424'},
        {'t': 'remote', 'key': '5.4.1', 'sel': ('Validaciones', '5.4.1')},
        {'t': 'decide', 'gateway': 'activeRefinancingCount = 0', 'when': ('eq', 'act:5.4.1:activeRefinancingCount', 'int:0'), 'fail': 'IDF426'},
        {'t': 'decide', 'gateway': 'completedRefinancingCountInPeriod > 1', 'when': ('le', 'act:5.4.1:completedRefinancingCountInPeriod', 'int:1'), 'fail': 'IDF427'},
        {'t': 'compute', 'key': '5.4.2', 'sel': ('Validaciones', '5.4.2'), 'ops': [{'fn': 'subtract', 'args': ['req:debtAmount', 'req:amountFinanced'], 'out': 'newAmountInitialQuote'}]},
        {'t': 'compute', 'key': '5.4.3', 'sel': ('Validaciones', '5.4.3'),
         'ops': [{'fn': 'minimum-percentage', 'args': ['req:stateLine', 'cfg:PorcentajeMinimoCuotaInicialClienteServActivo', 'cfg:PorcentajeMinimoCuotaInicialClienteServSuspendido',
                                                       'cfg:PorcentajeMinimoCuotaInicialClienteServDesactivo'], 'out': 'porcentajeValido'}]},
        {'t': 'compute', 'key': '5.4.4', 'sel': ('Validaciones', '5.4.4'), 'ops': [{'fn': 'percentage', 'args': ['val:5.4.2:newAmountInitialQuote', 'req:debtAmount'], 'out': 'porcentajeCalculado'}]},
        {'t': 'decide', 'gateway': 'porcentajeCalculado (5.4.4) >= porcentajeValido (5.4.3)', 'when': ('ge', 'val:5.4.4:porcentajeCalculado', 'val:5.4.3:porcentajeValido'), 'fail': 'IDF428'},
        {'t': 'remote', 'key': '5.4.5', 'sel': ('Validaciones', '5.4.5')},
        {'t': 'compute', 'key': '5.4.6', 'sel': ('Validaciones', '5.4.6'), 'ops': [{'fn': 'divide-money', 'args': ['req:amountFinanced', 'act:5.4.5:quotesNumber'], 'out': 'quoteAmount'}]},
        {'t': 'decide', 'gateway': 'creditLimit (act 5.1) >= quoteAmount (act 5.4.6) + fixedAmount (act 5.1)', 'when': ('ge', 'req:creditLimit', ('add', 'val:5.4.6:quoteAmount', 'req:fixedAmount')), 'fail': 'IDF429'},
        {'t': 'branch', 'gateway': "saveRequest = 'S'", 'when': ('eq', 'req:saveRequest', 'lit:S'),
         'then': [{'t': 'remote', 'key': '5.5', 'sel': ('Pre Refinanciamiento', '5.5')}], 'else': []},
        {'t': 'respond', 'data': {'requestCodeId': 'act:5.5:requestCodeId', 'amountInitialQuote': 'val:5.4.2:newAmountInitialQuote', 'amountFinanced': 'req:amountFinanced',
                                  'quoteAmount': 'val:5.4.6:quoteAmount', 'quotesNumber': 'act:5.4.5:quotesNumber', 'percentage': ('round2', 'val:5.4.4:porcentajeCalculado')}}],
        'comps': [], 'chains': {}},
    4: {'name': 'Refinanciamiento', 'sparx': '6. Registrar Refinanciamiento', 'prerequisite': 'sync', 'steps': [
        STATE_OK,
        {'t': 'remote', 'key': '6.2', 'sel': ('Refinanciamiento', '6.2')},
        {'t': 'decide', 'gateway': 'financingStateCodeId (act 6.2) = 1', 'when': ('eq', 'act:6.2:financingStateCodeId', 'prop:propFinanEstadoSolicitada'), 'fail': 'IDF432'},
        {'t': 'decide', 'gateway': 'agreementCodeId (act 6.2) = nulo/vacio', 'when': ('empty', 'act:6.2:agreementCodeId'), 'fail': 'IDF433'},
        {'t': 'decide', 'gateway': 'fechaHoy - createDate(act 6.2)', 'when': ('not', ('hours-exceed', 'act:6.2:createdAt', 'cfg:vigenciaRegistroSolicitudEnHoras')), 'fail': 'IDF434'},
        {'t': 'remote', 'key': '6.3', 'sel': ('Refinanciamiento', '6.3')},
        {'t': 'remote', 'key': '6.4', 'sel': ('Refinanciamiento', '6.4')},
        {'t': 'remote', 'key': '6.5', 'sel': ('Refinanciamiento', '6.5')},
        {'t': 'remote', 'key': '6.6', 'sel': ('Refinanciamiento', '6.6')},
        {'t': 'remote', 'key': '6.7', 'sel': ('Refinanciamiento', '6.7')},
        {'t': 'branch', 'gateway': 'Rollback Proceso', 'when': ('gt', ('size', 'lst:6.7:quotes'), 'int:0'),
         'then': [{'t': 'remote', 'key': '6.8', 'sel': ('Refinanciamiento', '6.8')}, {'t': 'remote', 'key': '6.9', 'sel': ('Refinanciamiento', '6.9')}], 'else': []},
        {'t': 'respond', 'data': {'agreementCodeId': 'act:6.3:agreementCodeId', 'installments': 'ins:6.5'}}],
        'comps': [{'key': 'R6.del', 'sel': ('Refinanciamiento', 'Rollback Refinanciamiento y cuotas asociadas')},
                  {'key': 'R6.req', 'sel': ('Refinanciamiento', 'Rollback Actualizacion solicitud pre-Refinanciamiento')},
                  {'key': 'R6.state', 'sel': ('Refinanciamiento', 'Revertir estado Financiamiento original')}],
        'chains': {'rollback refinaciamiento': ['R6.del'], 'revertir solicitud': ['R6.req', 'R6.del'], 'rollback proceso': ['R6.state', 'R6.req', 'R6.del']},
        'chainEdges': [('Rollback Refinanciamiento', 'Rollback Refinanciamiento y cuotas asociadas'), ('Revertir Solicitud', 'Rollback Actualizacion solicitud'),
                       ('Rollback Actualizacion solicitud', 'Rollback Refinanciamiento y cuotas asociadas'), ('Rollback Proceso', 'Revertir estado Financiamiento original'),
                       ('Revertir estado Financiamiento original', 'Rollback Actualizacion solicitud')]},
    5: {'name': 'Anulacion', 'sparx': '7. Anulaci', 'prerequisite': 'sync', 'steps': [
        STATE_OK,
        {'t': 'remote', 'key': '7.2', 'sel': ('"Anulada Notificada"', '7.2')},
        {'t': 'compute', 'key': '7.3', 'sel': ('"Anulada Notificada"', '7.3'),
         'ops': [{'fn': 'has-ineligible-installments', 'args': ['lst:7.2:quotes', 'prop:propEstadoPendiente', 'prop:propEstadoNotificada', 'prop:propCuotaInicial'], 'out': 'valor'}]},
        {'t': 'decide', 'gateway': 'valor=0', 'when': ('eq', 'val:7.3:valor', 'int:0'), 'fail': 'IDF343'},
        {'t': 'remote', 'key': '7.4', 'sel': ('"Anulada Notificada"', '7.4')},
        {'t': 'remote', 'key': '7.5', 'sel': ('"Anulada Notificada"', '7.5')},
        {'t': 'compute', 'key': '7.6', 'sel': ('"Anulada Notificada"', '7.6'), 'fail': 'IDF346', 'comp': 'rollback anulacion',
         'ops': [{'fn': 'cancellation-transform', 'args': ['lst:7.2:quotes', 'prop:propEstadoCuotaExortada', 'prop:propEstadoCuotaAnulada'], 'out': 'quotesFiltered'}]},
        {'t': 'remote', 'key': '7.7', 'sel': ('"Anulada Notificada"', '7.7')},
        {'t': 'remote', 'key': '7.8', 'sel': ('"Anulada Notificada"', '7.8'), 'listFilter': {'field': 'quoteNumber', 'ne': 0}},
        {'t': 'respond', 'data': {'requestCodeId': 'act:7.4:requestCodeId', 'agreementCodeId': 'req:agreementCodeId'}}],
        'comps': [{'key': 'R7.state', 'sel': ('"Anulada Notificada"', '7.9')}, {'key': 'R7.req', 'sel': ('"Anulada Notificada"', '7.10')}],
        'chains': {'rollback solicitud': ['R7.req'], 'rollback anulacion': ['R7.state', 'R7.req']},
        'chainEdges': [('Rollbak Solicitud', '7.10. Ejecuta Rollback'), ('Rollback Anulaci', '7.9. Revertir estado'), ('7.9. Revertir estado', '7.10. Ejecuta Rollback')]},
    6: {'name': 'Traslado de cuotas', 'sparx': '8. Cambio Titularidad', 'prerequisite': 'sync', 'steps': [
        STATE_OK,
        {'t': 'decide', 'gateway': 'currentDocumentCodeId (request) = documentCodeId (Act. 4.1)', 'when': ('and', ('eq', 'req:currentDocumentCodeId', 'act:4.1:documentCodeId'),
                                                                                                        ('eq', 'req:currentDocumentNumber', 'act:4.1:documentNumber')), 'fail': 'IDF441'},
        {'t': 'remote', 'key': '8.2', 'sel': ('Cambio', '8.2')},
        {'t': 'compute', 'key': '8.3', 'sel': ('Cambio', '8.3'), 'ops': [{'fn': 'sum-quotes', 'args': ['lst:8.2:quotes'], 'out': 'montoTotalCuotasPendientes'}]},
        {'t': 'decide', 'gateway': 'montoTotalCuotasPendientes = debtAmount (request)', 'when': ('eq', 'val:8.3:montoTotalCuotasPendientes', 'req:debtAmount'), 'fail': 'IDF444'},
        {'t': 'compute', 'key': '8.4', 'sel': ('Cambio', '8.4'),
         'ops': [{'fn': 'divide-money', 'args': ['req:debtAmount', 'req:quotesNumber'], 'out': 'quoteAmount'},
                 {'fn': 'add', 'args': ['val:8.4:quoteAmount', 'req:fixedAmount'], 'out': 'capacidadMes'}]},
        {'t': 'decide', 'gateway': 'creditLimit (request) >= capacidadMes', 'when': ('ge', 'req:creditLimit', 'val:8.4:capacidadMes'), 'fail': 'IDF445'},
        {'t': 'remote', 'key': '8.5', 'sel': ('Cambio', '8.5')},
        {'t': 'remote', 'key': '8.6', 'sel': ('Cambio', '8.6')},
        {'t': 'remote', 'key': '8.7', 'sel': ('Cambio', '8.7')},
        {'t': 'remote', 'key': '8.8', 'sel': ('Cambio', '8.8')},
        {'t': 'remote', 'key': '8.9', 'sel': ('Cambio', '8.9')},
        {'t': 'remote', 'key': '8.10', 'sel': ('Cambio', '8.10')},
        {'t': 'respond', 'data': {'agreementCodeId': 'act:8.6:agreementCodeId', 'installments': 'ins:8.7'}}],
        'comps': [{'key': 'R8.state', 'sel': ('Cambio', '8.11')}, {'key': 'R8.del', 'sel': ('Cambio', '8.12')}, {'key': 'R8.req', 'sel': ('Cambio', '8.13')}],
        'chains': {'rollback solicitud': ['R8.req'], 'rollback nuevo finaciamiento': ['R8.del', 'R8.req'], 'rollback proceso': ['R8.state', 'R8.del', 'R8.req']},
        'chainEdges': [('Rollback Solicitud', '8.13. Rollback Solicitud'), ('Rollback Nuevo Finaciamiento', '8.12. Rollback nuevo'), ('8.12. Rollback nuevo', '8.13. Rollback Solicitud'),
                       ('Rollback Proceso', '8.11. Revertir estado'), ('8.11. Revertir estado', '8.12. Rollback nuevo')]},
    7: {'name': 'Cancelacion por baja de servicio', 'sparx': '9. Cancelaci', 'prerequisite': 'sync', 'steps': [
        STATE_OK,
        {'t': 'remote', 'key': '9.2', 'sel': ('Cancelación', '9.2')},
        {'t': 'compute', 'key': '9.3', 'sel': ('Cancelación', '9.3'),
         'ops': [{'fn': 'filter-for-service-cancellation', 'args': ['lst:9.2:quotes', 'prop:propEstadoPendiente', 'prop:propEstadoNotificada', 'today'], 'out': 'quotesFiltered'}]},
        {'t': 'decide', 'gateway': 'quotesFiltered[].size > 0', 'when': ('gt', ('size', 'val:9.3:quotesFiltered'), 'int:0'), 'fail': 'IDF353'},
        {'t': 'remote', 'key': '9.4', 'sel': ('Cancelación', '9.4')},
        {'t': 'remote', 'key': '9.5', 'sel': ('Cancelación', '9.5')},
        {'t': 'remote', 'key': '9.6', 'sel': ('Cancelación', '9.6')},
        {'t': 'respond', 'data': {'requestCodeId': 'act:9.4:requestCodeId', 'agreementCodeId': 'req:agreementCodeId'}}],
        'comps': [{'key': 'R9.req', 'sel': ('Cancelación', '9.7')}],
        'chains': {'rollback solicitud': ['R9.req']}, 'chainEdges': [('Rollback Solicitud', '9.7. Ejecuta Rollback')]},
    8: {'name': 'Cambio de ciclo de facturacion', 'sparx': '10. Cambio Ciclo', 'prerequisite': 'sync', 'steps': [
        STATE_OK,
        {'t': 'remote', 'key': '10.2', 'sel': ('Cambio', '10.2')},
        {'t': 'remote', 'key': '10.3', 'sel': ('Cambio', '10.3')},
        {'t': 'remote', 'key': '10.4', 'sel': ('Cambio', '10.4')},
        {'t': 'compute', 'key': '10.5', 'sel': ('Cambio', '10.5'), 'fail': 'IDF465', 'comp': 'rollback cambiociclo',
         'ops': [{'fn': 'billing-cycle-dates', 'args': ['lst:10.2:quotes', 'req:quoteCycle', 'cfg:DiasVencimientoCuota'], 'out': 'quotesUpdated'}]},
        {'t': 'remote', 'key': '10.6', 'sel': ('Cambio', '10.6')},
        {'t': 'remote', 'key': '10.7', 'sel': ('Cambio', '10.7')},
        {'t': 'respond', 'data': {'requestCodeId': 'act:10.3:requestCodeId', 'agreementCodeId': 'req:agreementCodeId'}}],
        'comps': [{'key': 'R10.req', 'sel': ('Cambio', '10.8')}, {'key': 'R10.fin', 'sel': ('Cambio', '10.9')}],
        'chains': {'rollback solicitud': ['R10.req'], 'rollback cambiociclo': ['R10.fin', 'R10.req']},
        'chainEdges': [('Rollback Solicitud', '10.8. Rollback Solicitud'), ('Rollback CambioCiclo', '10.9. Rollback Financiamiento'), ('10.9. Rollback Financiamiento', '10.8. Rollback Solicitud')]},
}

for _flow in FLOWS.values():
    for _comp in _flow['comps']:
        _comp.setdefault('t', 'remote')
ALL = list(FLOWS.items()) + [('sync', {'name': 'sync', 'sparx': '4. Sincronizaci', 'prerequisite': None, 'steps': SYNC, 'comps': [], 'chains': {}})]

# Codes where the activity prose disagrees with the process graph and the contract: the graph/contract code is used (swagger governs).
CODE_FIXES = {'9.4': ({'otherwise': 'IDF354'}, 'prose IDF351 is the 404 code of 9.2; process graph and contract name IDF354 (CreateServiceCancellationRequest) for 9.4'),
              '9.5': ({'otherwise': 'IDF355'}, 'prose IDF353 is NoPendingOrNotified; process graph and contract name IDF355 (UpdateInstallmentsDates) for 9.5')}

# The sources give 1.1 two codes for the same failure; the contract catalog only has IDF389 (GetSystemConfiguration).
CONFIG_FAILURE_CODE = ('IDF399', 'IDF389')

# Rules of act 1 (VALIDACIONES): code -> (kind, parameters, keywords that must appear in the evidence line).
RULE_TABLE = {
    'IDF103': ('positive', {'field': 'debtAmount'}, ['debtamount > 0']), 'IDF104': ('positive', {'field': 'quotesNumber'}, ['quotesnumber >0']),
    'IDF105': ('positive', {'field': 'creditLimit'}, ['creditlimit > 0']), 'IDF106': ('enum', {'field': 'isClient', 'values': ['S', 'N']}, ['isclient = s | n', 'isclient solo']),
    'IDF107': ('enum', {'field': 'saveRequest', 'values': ['S', 'N']}, ['saverequest = s | n']),
    'IDF108': ('min', {'field': 'amountInitialQuote', 'min': 0, 'unlessChannel': 'CAD'}, ['amountinitialquote >= 0']),
    'IDF109': ('min', {'field': 'amountInitialQuote', 'min': 1, 'onlyChannel': 'CAD'}, ['amountinitialquote >= 1']),
    'IDF111': ('enum', {'field': 'stateLine', 'values': ['1', '2', '3']}, ['stateline = 1 | 2 | 3']),
    'IDF112': ('enum', {'field': 'clientInstantAccount', 'values': ['S']}, ['clientinstantaccount = s']),
    'IDF113': ('date-format', {'field': 'quoteCycle'}, ['quotecycle']), 'IDF114': ('range', {'field': 'cancellationTypeId', 'min': 1, 'max': 4}, ['entre 1 y 4']),
    'IDF115': ('date-max-month', {'field': 'quoteCycle'}, ['un mes posterior']), 'IDF119': ('date-gte-today', {'field': 'quoteCycle'}, ['quotecycle >= fecha de hoy']),
    'IDF120': ('date-gt-today', {'field': 'quoteCycle'}, ['mayor a la fecha del dia', 'mayor a la fecha de dia']),
    'IDF133': ('positive', {'field': 'amountFinanced'}, ['amountfinanced > 0']), 'IDF134': ('min', {'field': 'fixedAmount', 'min': 0}, ['fixedamount >=0']),
    'IDF135': ('enum', {'field': 'isInitialQuotePaid', 'values': ['S']}, ['solo debe tener como valor']),
}


def parse_request_validations(lines):
    """Act 1 VALIDACIONES prose -> {typeId: {'required': [(field, when)], 'rules': [{code, ...}]}} plus the type range rule."""
    result, current, condition, collecting = {}, None, None, False
    for line in lines:
        folded = fold(line)
        match = re.search(r'requesttypeid ?= ?(\d)', folded)
        if folded.startswith('si') and match and 'entonces' in folded:
            current, condition, collecting = int(match.group(1)), None, False
            result[current] = {'required': [], 'rules': []}
            continue
        if current is None:
            continue
        if 'isdelivered' in folded and 'diferente de uno' in folded:
            condition = 'notDelivered'
        elif 'isdelivered' in folded and 'valor de uno' in folded:
            condition = 'delivered'
        elif 'deben de venir informados' in folded or 'si no vienen informados' in folded or 'consider' in folded and 'mandatorios' in folded:
            collecting = True
        elif line.startswith('. ') and collecting:
            result[current]['required'].append({'field': line[2:].strip(), 'when': condition})
        elif line.startswith('-') and 'devolver idf' in folded:
            code = re.search(r'IDF\d{3}', line).group(0)
            if code == 'IDF101':
                continue
            if code not in RULE_TABLE:
                raise InterpretationError(f'validation code {code} has no rule definition')
            kind, params, keywords = RULE_TABLE[code]
            if not any(k in folded for k in keywords):
                raise InterpretationError(f'validation line for {code} does not match its rule definition: {line}')
            rule = {'code': code, 'kind': kind, **params, 'evidence': line}
            if code == 'IDF113' and current == 2:
                rule['when'] = 'notDelivered'
            result[current]['rules'].append(rule)
        elif not line.startswith('-') and not line.startswith('.'):
            collecting = False
    return result


def build(repo: Path, service: str):
    """Returns (sparx_spec dict, report)."""
    ws = repo / '.factory' / 'services' / service
    detail = yaml.safe_load((ws / 'sparx-authoritative-endpoint-detail.yml').read_bytes())
    authority = yaml.safe_load((ws / 'sparx-target-authority.yml').read_bytes())
    ops = [o for o in detail['operations'] if o.get('status') == 'active']
    if len(ops) != 1:
        raise InterpretationError('exactly one active operation is required')
    op = ops[0]
    branch = detail['authority']['branch']
    activities = [oi.parse_activity(a) for a in op['activities']]
    source_root = repo / authority['target']['sourceRoot']
    nodes = oi.load_process_graph(repo, op, source_root, branch['pagePathPrefix'])
    if not nodes:
        raise InterpretationError('no process graph pages were found for the authoritative operation')
    problems = []

    # properties (constants of the evidence), consistency across activities
    properties = {}
    for act in activities:
        for name, value in act['properties'].items():
            if name in properties and properties[name]['value'] != value:
                problems.append(f'property {name} has different values in the evidence')
            properties.setdefault(name, {'value': value, 'activity': act['name']})
    for name, value in (('propEstadoPendiente', 1), ('propCuotaInicial', 0)):
        if name in properties and properties[name]['value'] != value:
            problems.append(f'property {name} differs from the expected evidence value')
    # properties written as free prose in the linkdoc of 7.3 / 9.3 (not structured by the indexer)
    for sel in (('"Anulada Notificada"', '7.3'), ('Cancelación', '9.3')):
        act = oi.select(activities, *sel)
        raw = (repo / act['linkdoc']).read_text(encoding='utf-8', errors='replace') if act.get('linkdoc') else ''
        text = html.unescape(re.sub(r'<[^>]+>', '\n', raw))
        for name, number in re.findall(r'^\s*(prop\w+)\s*=\s*(-?\d+)\s*$', text, re.M):
            if name in properties and properties[name]['value'] != int(number):
                problems.append(f'property {name} has different values in the evidence')
            properties.setdefault(name, {'value': int(number), 'activity': act['name'] + ' (linkdoc)'})

    validations = parse_request_validations(oi.text_lines(oi.section_by_label(op['activities'][0], 'VALIDACIONES')))
    if sorted(validations) != list(range(1, 9)):
        problems.append(f'request validations cover types {sorted(validations)}')
    # Evidence-driven corrections of act 1 documented as discrepancies
    discrepancies = []
    notdelivered = [r for r in validations.get(2, {}).get('required', []) if r['when'] == 'notDelivered']
    if any(r['field'] == 'contactName' for r in notdelivered):
        validations[2]['required'] = [r for r in validations[2]['required'] if not (r['field'] == 'contactName' and r['when'] == 'notDelivered')]
        discrepancies.append({'id': 'D-contactName', 'statement': 'act 1 lists contactName as mandatory for requestTypeId 2, act 3.1 and the contract mark it optional; optional is applied (contract governs)'})
    for typed in validations.values():
        for item in typed['required']:
            item['field'] = {'requestType': 'requestTypeId'}.get(item['field'], item['field'])
    if any(r['field'] == 'requestTypeId' for r in validations.get(3, {}).get('required', [])):
        discrepancies.append({'id': 'D-requestType', 'statement': "act 1 and 5.1 name the mandatory field 'requestType'; it is the contract field requestTypeId"})

    flows = {}
    for type_id, flow in ALL:
        steps_seen = []
        resolved = {'name': flow['name'], 'sparxProcess': flow['sparx'], 'prerequisite': flow['prerequisite'], 'chains': flow['chains'], 'steps': jsonable(flow['steps']), 'comps': jsonable(flow['comps'])}
        keys = {}
        for group in ('steps', 'comps'):
            def visit(items):
                for step in items:
                    if step['t'] in ('remote', 'compute'):
                        act = oi.select(activities, *step['sel'])
                        keys[step['key']] = act
                        steps_seen.append(step['key'])
                    if step['t'] == 'branch':
                        visit(step['then'])
                        visit(step['else'])
            visit(flow[group])
        resolved['activityKeys'] = {k: {'lane': v['lane'], 'name': v['name'], 'guid': v['guid'], 'page': v['page'], 'pageSha256': v['pageSha256']} for k, v in keys.items()}
        # decisions and codes must exist in the process graph
        def verify(items):
            for step in items:
                if step['t'] in ('decide', 'branch') and not oi.graph_has_node(nodes, step['gateway']):
                    problems.append(f'flow {type_id}: gateway text {step["gateway"]!r} not found in the process graph')
                if step['t'] == 'decide' and not oi.graph_has_node(nodes, step['fail']):
                    problems.append(f'flow {type_id}: code {step["fail"]} not found as end event')
                if step['t'] == 'branch':
                    verify(step['then'])
                    verify(step['else'])
        verify(flow['steps'])
        for source, target in flow.get('chainEdges', []):
            if not oi.graph_has_edge(nodes, source, target):
                problems.append(f'flow {type_id}: compensation edge {source!r} -> {target!r} not found in the process graph')
        if not oi.graph_has_node(nodes, flow['sparx']):
            problems.append(f'flow {type_id}: process {flow["sparx"]!r} not found in the graph')
        if type_id != 'sync':
            flows[str(type_id)] = resolved
    # prose vs process graph codes of the remote steps
    for type_id, flow in ALL:
        def visit(items):
            for step in items:
                if step['t'] == 'remote':
                    act = oi.select(activities, *step['sel'])
                    prose = {c for c in oi.OUT_CODE.findall(' '.join(filter(None, [act['outcome']['otherwise'], *act['outcome']['byStatus'].values()]))) if c != 'IDT'}
                    graph = oi.graph_codes_after(nodes, act['name'].split(' ', 1)[0] + ' ' + act['name'].split(' ', 1)[1][:12]) if ' ' in act['name'] else None
                    graph = {c for c in (graph or set()) if c != 'IDT'}
                    if prose and graph and not prose <= graph:
                        fix = CODE_FIXES.get(step['key'])
                        discrepancies.append({'id': f'D-code-{step["key"]}', 'statement': f'activity {step["key"]}: prose codes {sorted(prose)} differ from the process graph codes {sorted(graph)}'
                                              + (f'; {fix[1]}' if fix else ''), 'resolved': bool(fix)})
                        if not fix:
                            problems.append(f'activity {step["key"]}: prose codes {sorted(prose)} vs graph {sorted(graph)} without an approved correction')
                if step['t'] == 'branch':
                    visit(step['then'])
                    visit(step['else'])
        visit(flow['steps'])
        visit(flow['comps'])
    if problems:
        raise InterpretationError('interpretation does not match the evidence:\n' + '\n'.join(sorted(set(problems))))
    spec = {'version': oi.VERSION, 'kind': oi.KIND, 'service': service,
            'authority': {'file': f'.factory/services/{service}/sparx-target-authority.yml', 'sha256': oi.sha((ws / 'sparx-target-authority.yml').read_bytes()),
                          'detailSha256': oi.sha((ws / 'sparx-authoritative-endpoint-detail.yml').read_bytes()), 'branch': branch['branchRootId'],
                          'branchName': branch['name'], 'method': op['method'], 'path': op['path'], 'operationId': op['operationId'], 'process': op['process']['name']},
            'activities': [{k: v for k, v in act.items() if k in ('name', 'lane', 'guid', 'page', 'pageSha256', 'status', 'call', 'input', 'output', 'outcome', 'properties', 'linkdoc', 'linkdocSha256')} for act in activities],
            'processGraph': {'nodes': len(nodes), 'byType': _count(nodes), 'pageSha256': {n['page']: n['sha256'] for n in nodes.values()}},
            'properties': {k: v['value'] for k, v in sorted(properties.items())},
            'requestValidations': {str(k): v for k, v in sorted(validations.items())},
            'flows': flows, 'sync': jsonable(SYNC), 'discrepancies': discrepancies, 'configFailureCode': {'sparx': CONFIG_FAILURE_CODE[0], 'contract': CONFIG_FAILURE_CODE[1]}}
    return spec, {'activities': len(activities), 'graphNodes': len(nodes)}, (activities, nodes, op)


def jsonable(value):
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value


def _count(nodes):
    out = {}
    for n in nodes.values():
        out[n['type']] = out.get(n['type'], 0) + 1
    return dict(sorted(out.items()))


def main(argv=None):
    import sys
    service = (argv or sys.argv[1:])[0]
    repo = Path.cwd()
    spec, report, _ = build(repo, service)
    target = repo / '.factory' / 'services' / service / 'sparx-spec.yml'
    target.write_bytes(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    print({'written': target.as_posix(), **report})
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
