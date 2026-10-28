"""R07 Change Offer frontend/source contract tests; no API/DB calls."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "apps/web/src/app/subscriptions/page.tsx"
HELPER = ROOT / "apps/web/src/lib/subscriptions.ts"
ROUTE = ROOT / "services/api/app/routes/subscriptions.py"


def test_route_still_enforces_tenant_permission_and_same_application():
    source = ROUTE.read_text(encoding="utf-8")
    body = source.split("def change_subscription_offer(", 1)[1].split("# =========================================================", 1)[0]
    assert "subscription_id" in body
    assert '"/subscriptions/{subscription_id}/change-offer"' in source
    anchor = source.split("def change_subscription_offer(", 1)[1]
    assert 'permission_code="subscription.manage"' in anchor
    assert "target_offer.application_id" in anchor
    assert "application.id" in anchor
    assert "db.commit()" in anchor
    assert 'action="subscription.change_offer"' in anchor


def test_frontend_uses_canonical_api_and_body_contract():
    source = HELPER.read_text(encoding="utf-8")
    assert "import api from" in source
    assert "/api/v1/marketplace/offers" in source
    assert "/api/v1/subscriptions/${subscriptionId}/change-offer" in source
    assert "{ offer_id: offerId }" in source
    assert "offer.application.id === applicationId" in source
    assert 'offer.status === "active"' in source
    assert 'item.code === "application.deploy"' in source


def test_dialog_keeps_existing_page_shell_tenant_and_lifecycle_controls():
    source = PAGE.read_text(encoding="utf-8")
    assert "<ProtectedRoute>" in source
    assert "<AppShell>" in source
    assert "useTenant()" in source
    for func in ["suspendTenantSubscription", "resumeTenantSubscription", "cancelTenantSubscription"]:
        assert func in source
    assert "onChangeOffer" in source
    assert "Change Subscription Offer" in source
    assert "Confirm Change Offer" in source
    assert "changeTenantSubscriptionOffer(subscription.id, option.id)" in source
    assert "loadSubscriptions(selectedTenantId)" in source
    assert "selectedTenantId !== changeOfferTenantId" in source
    assert "option.application.id !== subscription.application.id" in source
    assert "result.subscriptionId !== subscription.id" in source


def test_change_offer_is_active_only_and_fail_closed():
    source = PAGE.read_text(encoding="utf-8")
    idx = source.index('onClick={onChangeOffer}')
    portion = source[idx-240:idx+100]
    assert 'status === "active"' in portion
    assert "!selectedChangeOffer" in source
    assert "changeOfferLoading" in source
    assert "changeOfferError" in source
    assert "!selectedTenantId" in source
    assert "setChangeOfferTarget(null)" in source


def test_stale_offer_fetch_cannot_reopen_or_overwrite_new_dialog():
    source = PAGE.read_text(encoding="utf-8")
    assert "useRef(0)" in source
    assert "requestId === changeOfferRequestId.current" in source
    assert "changeOfferRequestId.current += 1" in source
