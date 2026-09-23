"""Run inside the receiver: preview makes no exchange writes; apply is explicit."""
import argparse
import json
import urllib.error
import urllib.request


def call(cfg, path, body=None):
    request = urllib.request.Request('http://127.0.0.1:8089'+path,
        data=json.dumps(body).encode() if body is not None else None, headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer '+cfg.ingress_token,
            'X-Operator-Password': cfg.ft_pass})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def show(result, command_hint=True):
    print(json.dumps(result, indent=2))
    if result.get('state') == 'preview' and command_hint:
        print('\nFrom your Mac, apply this preview within five minutes:\n'
              "ssh main-instance 'docker exec killers-receiver python -m app.tp_migrate apply --request-id "
              +result['request_id']+"'")


def main():
    from .main import Config
    cfg = Config()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    preview = sub.add_parser('preview')
    choice = preview.add_mutually_exclusive_group(required=True)
    choice.add_argument('--trade-id', type=int)
    choice.add_argument('--all', action='store_true', help='Preview open legacy positions; never bulk-apply')
    sub.add_parser('review', help='Preview each legacy position and ask for APPLY interactively')
    apply = sub.add_parser('apply')
    apply.add_argument('--request-id', required=True)
    args = parser.parse_args()
    try:
        if args.command in ('preview', 'review'):
            if args.command == 'review' or args.all:
                positions = call(cfg, '/positions')['positions']
                ids = [p['ft_trade_id'] for p in positions if p['state'] == 'open'
                       and p['ft_trade_id'] and not p.get('tp_policy')]
            else:
                ids = [args.trade_id]
            if not ids:
                print('No open legacy positions to migrate.')
            failed = False
            for trade_id in ids:
                try:
                    proposal = call(cfg, '/operator/tp-migrations/preview', {'trade_id': trade_id})
                    show(proposal, command_hint=args.command!='review')
                    if args.command == 'review':
                        answer=input('Type APPLY to replace these TPs now, or Enter to skip: ').strip()
                        if answer == 'APPLY':
                            result=call(cfg, '/operator/tp-migrations/'+proposal['request_id']+'/apply', {})
                            show(result)
                            if result.get('state') != 'active':
                                raise SystemExit(2)
                        else:
                            print('Skipped; no orders changed.')
                except urllib.error.HTTPError as exc:
                    print('Request refused for trade', trade_id, exc.read().decode())
                    failed = True
            if failed:
                raise SystemExit(1)
        else:
            from uuid import UUID
            result = call(cfg, '/operator/tp-migrations/'+str(UUID(args.request_id))+'/apply', {})
            show(result)
            if result.get('state') != 'active':
                raise SystemExit(2)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode()); raise SystemExit(1)
    except (EOFError, KeyboardInterrupt):
        print('Stopped. No further requests sent.'); raise SystemExit(1)
    except (TimeoutError, urllib.error.URLError):
        print('Response unavailable. Do not create a new request blindly; inspect target_orders. Repeating the SAME request ID never resubmits.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
