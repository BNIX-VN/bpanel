from types import SimpleNamespace

from app.services.provisioning import account_to_dict


def test_account_to_dict_uses_package_and_whmcs_service_id_label():
    account = SimpleNamespace(
        external_id="whmcs:123",
        user=SimpleNamespace(username="bp_123", email="client@bpanel.dev"),
        primary_website=None,
        package=SimpleNamespace(name="Starter"),
        package_id=2,
        status="active",
        created_at=None,
    )

    data = account_to_dict(account, None)

    assert data["domain"] is None
    assert data["service_label"] == "Starter #123"
