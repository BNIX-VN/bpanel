from types import SimpleNamespace

from app.api.provisioning import _provisioning_app_type, _provisioning_email
from app.services.provisioning import account_to_dict


def test_provisioning_email_is_stable_per_username():
    assert _provisioning_email("bp_123") == "bp_123@users.bpanel.dev"


def test_provisioning_email_ignores_customer_email():
    assert _provisioning_email("bp456_abcd") != "customer@example.com"


def test_provisioning_without_domain_is_panel_user_only():
    payload = SimpleNamespace(domain=None, install_wordpress=False, app_type="wordpress")

    assert _provisioning_app_type(payload) == "php"


def test_account_to_dict_uses_package_and_whmcs_service_id_label():
    account = SimpleNamespace(
        external_id="whmcs:123",
        user=SimpleNamespace(username="bp_123", email="bp_123@users.bpanel.dev"),
        primary_website=None,
        package=SimpleNamespace(name="Starter"),
        package_id=2,
        status="active",
        created_at=None,
    )

    data = account_to_dict(account, None)

    assert data["domain"] is None
    assert data["service_label"] == "Starter #123"
