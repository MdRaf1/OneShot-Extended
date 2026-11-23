from src.gui.prompter import GuiPrompter


def test_confirm_maps_opener_response_to_bool():
    opener = lambda msg, choices: "y"
    assert GuiPrompter(dialog_opener=opener).confirm("ok?") is True


def test_confirm_maps_no_response_to_false():
    opener = lambda msg, choices: "n"
    assert GuiPrompter(dialog_opener=opener).confirm("ok?") is False


def test_confirm_default_yes_on_none_response():
    opener = lambda msg, choices: None
    assert GuiPrompter(dialog_opener=opener).confirm("ok?") is True


def test_confirm_explicit_yes_requires_explicit_y():
    opener = lambda msg, choices: None
    assert GuiPrompter(dialog_opener=opener).confirm_explicit_yes("exit?") is False


def test_confirm_explicit_yes_accepts_y():
    opener = lambda msg, choices: "y"
    assert GuiPrompter(dialog_opener=opener).confirm_explicit_yes("exit?") is True


def test_select_index_maps_chosen_label_back_to_index():
    opener = lambda msg, choices: choices[1]
    assert GuiPrompter(dialog_opener=opener).select_index("pick", 3) == 1


def test_select_index_none_on_cancel():
    opener = lambda msg, choices: None
    assert GuiPrompter(dialog_opener=opener).select_index("pick", 3) is None


def test_select_index_passes_count_many_choices_to_opener():
    seen = {}

    def opener(msg, choices):
        seen["choices"] = choices
        return choices[0]

    GuiPrompter(dialog_opener=opener).select_index("pick", 3)
    assert len(seen["choices"]) == 3


def test_select_index_returns_none_for_an_unrecognized_response():
    opener = lambda msg, choices: "not-a-real-choice"
    assert GuiPrompter(dialog_opener=opener).select_index("pick", 3) is None
