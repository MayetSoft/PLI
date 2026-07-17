# SPDX-License-Identifier: 0BSD
# This skeleton file (alone, not the pli package it imports) is released
# under the Zero-Clause BSD license: copy it into your private plugin
# repository without restriction. Distribution or network use of a
# combined work with the AGPL core is governed by the core's license —
# the platform's copyright holder can license its own proprietary
# plugin; third parties should read LICENSE and talk to counsel.
"""Skeleton for a private billing/entitlements plugin (the closed half
of the open-core split).

Ship this as its own private package (e.g. `pli-pro`), install it in the
production image, and set:

    PLI_BILLING_PLUGIN=pli_pro.billing

The contract is one factory returning one object:

    create_provider(settings) -> pli.billing.BillingProvider

What the boundary means — and why it keeps the trust model intact:

- The provider answers "what plan is this organizer on?" and handles the
  money plumbing (checkout URL out, payment webhook in). That is all.
- It receives organizer rows and webhook bytes. It is never handed
  participants, declarations, rounds, or key material, and the feature
  gates that consume its answer live in the PUBLIC code
  (pli/billing.py): a plugin cannot widen what a plan may touch, and
  an unknown plan name resolves to 'free'.
- Anything participant-facing added here would be a design breach, not a
  configuration: the open core simply has no seam for it.

Replace the body with your real logic: license keys, invoicing, a
different PSP, seat counts, enterprise contracts — organizer-side only.
"""

from pli.billing import BillingProvider


class ProProvider(BillingProvider):
    def __init__(self, settings):
        self.settings = settings
        # e.g. read PLI_PRO_* env vars, open your entitlements store…

    def enforced(self) -> bool:
        return True

    def plan_name(self, organizer) -> str:
        # Look the organizer up in your entitlements backend.
        # Return "pro" or "free" (unknown values resolve to "free").
        return "free"

    def checkout_url(self, organizer, opener=None) -> str | None:
        # Return a hosted checkout/quote URL for this organizer,
        # or None if there is nothing to sell them right now.
        return None

    def handle_webhook(self, conn, headers: dict, body: bytes) -> tuple[int, str]:
        # Authenticate the payload (signature header), then update your
        # entitlements state. You may persist to your own storage or to
        # the organizers.plan column. Return (http_status, body_text).
        return 400, "not implemented"


def create_provider(settings) -> ProProvider:
    return ProProvider(settings)
