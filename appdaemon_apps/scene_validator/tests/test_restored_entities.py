"""C1: restored or re-added entities (integration reload, HA restart) are not activations."""

from datetime import timedelta

import pytest

from test_select_listener import SCENE, SELECT, make_app


@pytest.fixture
def app(tmp_path):
    validator = make_app(tmp_path, {SCENE: "2026-11-01T10:00:00+00:00", SELECT: "unknown"})
    validator.logs.clear()  # startup logs (version banner) are WARNING level
    return validator


def validations(app):
    return [kw["scene_entity"] for name, _d, kw in app.scheduled
            if name == "perform_scene_validation"]


def fresh(app, offset=0.0):
    return (app.now + timedelta(seconds=offset)).isoformat()


def no_warnings(app):
    return not any(level in ("WARNING", "ERROR") for level, _m in app.logs)


def test_scene_restored_after_reload_is_ignored(app):
    three_weeks_ago = (app.now - timedelta(weeks=3)).isoformat()

    app.on_scene_state_changed(SCENE, "state", None, three_weeks_ago, {})

    assert app.scheduled == []
    assert app.light_last_activation == {}
    assert no_warnings(app)


def test_scene_old_unavailable_is_ignored(app):
    # 2.5.1 (A1): old "unknown" is no longer a restore - a never-activated scene
    # activated via HA must validate (test_pr20_scene_path); a restored old
    # timestamp is still rejected by the stale check
    app.on_scene_state_changed(SCENE, "state", "unavailable", fresh(app), {})

    assert app.scheduled == []
    assert no_warnings(app)


def test_scene_stale_timestamp_is_ignored(app):
    stale = fresh(app, -(app.transition_delay + 1))

    app.on_scene_state_changed(SCENE, "state", "2026-11-01T10:00:00+00:00", stale, {})

    assert app.scheduled == []
    assert any(level == "DEBUG" for level, _m in app.logs)
    assert no_warnings(app)


def test_scene_fresh_activation_still_validates(app):
    app.on_scene_state_changed(SCENE, "state", "2026-11-01T10:00:00+00:00", fresh(app, -1), {})

    assert validations(app) == [SCENE]


def test_select_readded_is_ignored(app):
    app.on_select_state_changed(SELECT, "state", None, "Standard", {})

    assert app.scheduled == []
    assert no_warnings(app)


def test_select_old_unavailable_is_ignored(app):
    app.on_select_state_changed(SELECT, "state", "unavailable", "Standard", {})

    assert app.scheduled == []


def test_select_unknown_to_scene_still_activates(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})

    assert validations(app) == [SCENE]
