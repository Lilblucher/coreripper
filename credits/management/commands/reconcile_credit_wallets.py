"""Prove (or repair) the invariant that every wallet balance equals the sum of
its ledger deltas. The ledger is the source of truth; --fix overwrites wallet
balances from it (no ledger write  reconcile restores the ledger's truth, it
doesn't create history). Also cross-checks pack_balance against the sum of
unexpired PackCreditLot.credits_remaining.

Exit code 1 when drift is found without --fix (cron-friendly).
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from credits.models import CreditLedger, CreditWallet, PackCreditLot


class Command(BaseCommand):
    help = "Reconcile credit wallet balances against the append-only ledger."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Overwrite wallet balances from the ledger sums.",
        )

    def handle(self, *args, **options):
        fix = options["fix"]
        now = timezone.now()
        drift = 0

        for wallet in CreditWallet.objects.select_related("user").iterator():
            ledger = CreditLedger.objects.filter(user_id=wallet.user_id)
            sub_expected = max(
                0,
                ledger.filter(bucket="subscription").aggregate(s=Sum("delta"))["s"] or 0,
            )
            pack_expected = max(
                0, ledger.filter(bucket="pack").aggregate(s=Sum("delta"))["s"] or 0
            )
            lot_sum = (
                PackCreditLot.objects.filter(
                    wallet=wallet, credits_remaining__gt=0, expires_at__gt=now
                ).aggregate(s=Sum("credits_remaining"))["s"]
                or 0
            )

            problems = []
            if wallet.subscription_balance != sub_expected:
                problems.append(
                    f"subscription wallet={wallet.subscription_balance} ledger={sub_expected}"
                )
            if wallet.pack_balance != pack_expected:
                problems.append(f"pack wallet={wallet.pack_balance} ledger={pack_expected}")
            if wallet.pack_balance != lot_sum:
                problems.append(f"pack wallet={wallet.pack_balance} lots={lot_sum}")

            if problems:
                drift += 1
                self.stdout.write(
                    f"user {wallet.user_id}: " + "; ".join(problems)
                )
                if fix:
                    with transaction.atomic():
                        w = CreditWallet.objects.select_for_update().get(pk=wallet.pk)
                        w.subscription_balance = sub_expected
                        w.pack_balance = pack_expected
                        w.save(update_fields=["subscription_balance", "pack_balance", "updated_at"])

        if drift == 0:
            self.stdout.write(self.style.SUCCESS("No drift  all wallets reconcile."))
            return
        if fix:
            self.stdout.write(self.style.WARNING(f"Fixed {drift} wallet(s)."))
            return
        self.stderr.write(self.style.ERROR(f"{drift} wallet(s) drifted (run with --fix)."))
        raise SystemExit(1)
