from __future__ import annotations

import argparse

from app.worker import dispatch_outbox_events, reconcile_billing_reservations


def main() -> None:
    parser = argparse.ArgumentParser(description="点凡阅卷后台维护任务")
    parser.add_argument(
        "task",
        choices=("reconcile-billing", "dispatch-outbox"),
        help="要投递到后台队列的维护任务",
    )
    args = parser.parse_args()
    if args.task == "reconcile-billing":
        reconcile_billing_reservations.send()
    elif args.task == "dispatch-outbox":
        dispatch_outbox_events.send()


if __name__ == "__main__":
    main()
