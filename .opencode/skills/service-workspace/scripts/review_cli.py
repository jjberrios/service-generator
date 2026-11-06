"""Local MANUAL review UI, excluded from all project agents' permitted tools.

Interactive display/selection is an operational guard, not human authentication.
Same-user arbitrary execution can bypass it. H-02 remains open (Model B).
"""
import argparse
from pathlib import Path
import sys
import yaml

import decision_context as dc
import decision_requests as dr
import decision_reviews as reviews


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    review = sub.add_parser('review')
    review.add_argument('service')
    review.add_argument('request_id')
    review.add_argument('--functional-common-git', action='store_true')
    review.add_argument('--supersedes', action='append', default=[])
    revoke = sub.add_parser('revoke')
    revoke.add_argument('service')
    revoke.add_argument('event_id')
    status = sub.add_parser('status')
    status.add_argument('service')
    adopt = sub.add_parser('import-functional')
    adopt.add_argument('service')
    adopt.add_argument('source_worktree', type=Path)
    adopt.add_argument('event_id')
    args = parser.parse_args(argv)
    repo = Path.cwd().resolve()
    try:
        print(reviews.WARNING)
        if args.command == 'status':
            active = {g['eventId'] for g in reviews.current(repo, args.service)}
            history = reviews.events(repo, args.service)
            dead = {target for event in history for target in event['targets']}
            def validity(event):
                if event['eventId'] in dead:
                    return 'revoked-or-superseded'
                if event['eventId'] in active:
                    return 'current'
                if event['action'] == 'revoke':
                    return 'revocation-record'
                if event['context'] != reviews.context(repo, args.service, event['context']['purpose']):
                    return 'stale-context; prepare a current request'
                return 'not-active; inspect scope or rejected/pending selections'
            print(yaml.safe_dump([{'eventId': e['eventId'], 'action': e['action'],
                                  'validity': validity(e),
                                  'selections': [{k: s[k] for k in ('decisionId', 'outcome', 'alternativeId')} for s in e['selections']]}
                                 for e in history], allow_unicode=True))
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise dc.DecisionError('manual-review-requires-interactive-terminal; no --by, pipe or approval flag supported')
        if args.command == 'revoke':
            print('Revoke ALL selections in event:', args.event_id)
            if input('Type REVOKE to record this operation: ') != 'REVOKE':
                return 4
            result = reviews._revoke(repo, args.service, args.event_id)
        elif args.command == 'import-functional':
            print('Adopt current functional review from', args.source_worktree, args.event_id)
            if input('Type IMPORT to adopt only permitted functional scope: ') != 'IMPORT':
                return 4
            result = reviews._import_functional(repo, args.service, args.source_worktree, args.event_id)
        else:
            request = dr.read(repo, args.service, args.request_id)
            print(yaml.safe_dump(request['context'], allow_unicode=True, sort_keys=False))
            if dr.status(repo, args.service, args.request_id)['validity'] != 'current':
                raise dc.DecisionError('stale-request; prepare a current one')
            active = {g['decisionId']: g for g in reviews.current(repo, args.service)}
            choices = {}
            for decision in request['decisions']:
                if decision['classification'] not in ('human-functional', 'explicit-authorization'):
                    print(decision['key'], ': analysis/technical item; not a human approval')
                    continue
                print(yaml.safe_dump(decision, allow_unicode=True, sort_keys=False))
                for alternative in decision['alternatives']:
                    binding = alternative.get('binding') or {}
                    if binding.get('kind') == 'historical-decision':
                        import consistency_gate as gate
                        record = gate.decisions_by_id(repo / '.factory/services' / args.service / 'sparx-reviewed-decisions.yml').get(binding['decisionId'])
                        print('Exact historical record to reattest (including scope/effects):')
                        print(yaml.safe_dump(record, allow_unicode=True, sort_keys=False))
                if decision['decisionId'] in active and not args.supersedes:
                    print('Current decision reused; no repeated approval.')
                    continue
                answer = input('Alternative id, REJECT, or Enter to leave pending: ').strip()
                if answer == 'REJECT':
                    choices[decision['decisionId']] = ('rejected', None)
                elif answer:
                    choices[decision['decisionId']] = ('approved', answer)
                else:
                    choices[decision['decisionId']] = ('pending', None)
            if not choices:
                print('No new reviews required.')
                return 0
            print('Selections:', yaml.safe_dump(choices, allow_unicode=True))
            print('Supersedes entire events:', args.supersedes)
            if input('Type RECORD to save exactly these selections: ') != 'RECORD':
                return 4
            result = reviews._record(repo, args.service, args.request_id, choices,
                                     scope='functional-common-git' if args.functional_common_git else 'worktree',
                                     supersedes=args.supersedes)
        print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, EOFError, yaml.YAMLError) as error:
        print(f'manual-review: {error}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
