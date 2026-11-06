"""Delegated operational review: records selections made by the agent under an
explicit, verbatim user delegation. NOT human authentication (H-02 remains open).

The user must have explicitly stated in the conversation that the agent may take
the decisions. The verbatim statement is mandatory and is stored in the event
(`delegation`), so every delegated approval is distinguishable and auditable.
Only `resolve-finding` and `resume` bindings are delegable; overwrite of existing
output files and historical-decision reattestation stay manual (review_cli.py).

Usage:
  python delegated_review.py record <service> <request_id> --choices <file.yml> \
      --user-authorization "<verbatim user statement>" [--rationale "<text>"]

choices file: mapping `decision key` (e.g. finding-1) -> alternative id
(e.g. swagger-governs), or `REJECT`. Keys not listed stay pending.
"""
import argparse
from pathlib import Path
import sys

import yaml

import decision_context as dc
import decision_requests as dr
import decision_reviews as reviews

DELEGABLE = ('resolve-finding', 'resume')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    rec = sub.add_parser('record')
    rec.add_argument('service')
    rec.add_argument('request_id')
    rec.add_argument('--choices', type=Path, required=True)
    rec.add_argument('--user-authorization', required=True)
    rec.add_argument('--rationale', default='')
    args = parser.parse_args(argv)
    repo = Path.cwd().resolve()
    try:
        statement = args.user_authorization.strip()
        if len(statement) < 10:
            raise dc.DecisionError('delegation-requires-verbatim-user-statement')
        request = dr.read(repo, args.service, args.request_id)
        if dr.status(repo, args.service, args.request_id)['validity'] != 'current':
            raise dc.DecisionError('stale-request; prepare a current one')
        wanted = yaml.safe_load(args.choices.read_text(encoding='utf-8')) or {}
        if not isinstance(wanted, dict):
            raise dc.DecisionError('choices-must-be-a-mapping')
        by_key = {d['key']: d for d in request['decisions']}
        unknown = set(wanted) - set(by_key)
        if unknown:
            raise dc.DecisionError(f'unknown-decision-keys: {sorted(unknown)}')
        choices = {}
        for key, answer in wanted.items():
            decision = by_key[key]
            if decision['classification'] not in ('human-functional', 'explicit-authorization'):
                raise dc.DecisionError(f'{key}: not a human decision item')
            if answer == 'REJECT':
                choices[decision['decisionId']] = ('rejected', None)
                continue
            alt = next((a for a in decision['alternatives'] if a['id'] == answer), None)
            if not alt or (alt.get('binding') or {}).get('kind') not in DELEGABLE:
                raise dc.DecisionError(f'{key}: alternative {answer!r} missing or not delegable')
            choices[decision['decisionId']] = ('approved', answer)
        if not choices:
            raise dc.DecisionError('no-choices')
        delegation = {'by': 'agent', 'userAuthorization': statement, 'rationale': args.rationale,
                      'choices': {k: wanted[k] for k in sorted(wanted)}}
        result = reviews._record(repo, args.service, args.request_id, choices, delegation=delegation)
        print(reviews.WARNING)
        print('DELEGATED review recorded:', result['eventId'], f'({len(choices)} selections)')
        return 0
    except (ValueError, OSError, KeyError, TypeError, yaml.YAMLError, dc.DecisionError) as error:
        print(f'delegated-review: {error}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
