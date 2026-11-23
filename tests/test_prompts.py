from src.prompts import CLIPrompter


def test_confirm_default_yes_on_enter(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert CLIPrompter().confirm("ok?") is True


def test_confirm_explicit_no_declines(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert CLIPrompter().confirm("ok?") is False


def test_confirm_explicit_yes_default_no_on_enter(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert CLIPrompter().confirm_explicit_yes("exit?") is False


def test_confirm_explicit_yes_accepts_y(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert CLIPrompter().confirm_explicit_yes("exit?") is True


def test_select_index_valid_choice(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "2")
    # 1-based input, 0-based return
    assert CLIPrompter().select_index("pick", 3) == 1


def test_select_index_cancel_token(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "r")
    assert CLIPrompter().select_index("pick", 3, cancel_tokens=frozenset({"r"})) is None


def test_select_index_retries_on_invalid(monkeypatch):
    responses = iter(["bogus", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    assert CLIPrompter().select_index("pick", 3) == 0


def test_select_index_retries_on_out_of_range(monkeypatch):
    responses = iter(["99", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    assert CLIPrompter().select_index("pick", 3) == 0
