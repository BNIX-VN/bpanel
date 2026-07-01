import pytest

from app.services import waf


def test_default_rules_only_cover_general_and_wordpress():
    definitions = waf.default_rule_definitions()

    assert {rule["category"] for rule in definitions} == {"General", "WordPress"}
    assert all(rule["enabled_default"] for rule in definitions)


def test_removed_framework_rule_ids_are_rejected():
    with pytest.raises(ValueError, match="Unknown WAF rule"):
        waf.validate_enabled_rule_ids(["laravel-sensitive-files"])


def test_render_site_rules_only_includes_selected_wordpress_rule():
    content = waf.render_site_rules("example.com", ["wordpress-sensitive-files"])

    assert "id:1001101" in content
    assert "id:1001001" not in content
    assert "id:1001201" not in content
