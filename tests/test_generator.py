from src.prompts import Prompter
from src.wps.generator import WPSpin

# Captured directly from the pre-refactor generator.py (one BSSID per
# algorithm family, each chosen to match exactly one of the 24 ALGOS
# entries via _suggest()'s OUI tables) — this is the regression guard
# proving Task 7's prompter-DI refactor changes zero bits of the actual
# PIN-generation output.
GOLDEN_CASES = [
    ('04:BF:6D:11:22:33', ['11228677']),   # pin24 (ALGO_MAC)
    ('20:0B:C7:11:22:33', ['85633797']),   # pin28 (ALGO_MAC)
    ('00:07:26:11:22:33', ['86570756']),   # pin32 (ALGO_MAC)
    ('00:18:E7:11:22:33', ['56098419']),   # pinDLink1 (ALGO_MAC)
    ('04:92:26:11:22:33', ['37841003']),   # pinASUS (ALGO_MAC)
    ('00:0B:2B:4A:22:33', ['14785115']),   # pinAirocon (ALGO_MAC)
    ('E4:6F:13:11:22:33', ['']),           # pinEmpty (ALGO_EMPTY)
    ('00:1A:2B:11:22:33', ['12345670']),   # pinCisco (ALGO_STATIC)
]


def test_suggested_pins_unchanged_for_known_bssids():
    gen = WPSpin()
    for bssid, expected_pins in GOLDEN_CASES:
        assert gen._getSuggestedList(bssid) == expected_pins  # pylint: disable=protected-access


MULTI_CANDIDATE_BSSID = '14:D6:4D:11:22:33'  # matches 8 algorithms


class FakePrompter(Prompter):
    def __init__(self, select_index_returns=None):
        self.select_index_returns = select_index_returns
        self.select_index_called = False

    def confirm(self, message: str) -> bool:
        return True

    def confirm_explicit_yes(self, message: str) -> bool:
        return False

    def select_index(self, prompt, count, cancel_tokens=frozenset()):
        self.select_index_called = True
        return self.select_index_returns


def test_get_all_likely_wraps_get_suggested_list():
    gen = WPSpin()
    assert gen.getAllLikely(MULTI_CANDIDATE_BSSID) == gen._getSuggestedList(MULTI_CANDIDATE_BSSID)  # pylint: disable=protected-access


def test_prompt_pin_uses_injected_prompter():
    fake = FakePrompter(select_index_returns=0)
    gen = WPSpin(prompter=fake)
    result = gen.promptPin(MULTI_CANDIDATE_BSSID)
    assert fake.select_index_called
    assert result == gen._getSuggested(MULTI_CANDIDATE_BSSID)[0]['pin']  # pylint: disable=protected-access


def test_prompt_pin_defaults_to_cli_prompter_when_none_given():
    gen = WPSpin()
    assert gen.prompter is not None


def test_prompt_pin_single_candidate_does_not_consult_prompter():
    # pinCisco BSSID above has exactly 1 suggestion, so promptPin must
    # auto-select without ever calling the prompter (matches today's
    # len(pins) == 1 branch).
    fake = FakePrompter(select_index_returns=0)
    gen = WPSpin(prompter=fake)
    result = gen.promptPin('00:1A:2B:11:22:33')
    assert not fake.select_index_called
    assert result == '12345670'


def test_prompt_pin_zero_candidates_returns_none_without_consulting_prompter():
    fake = FakePrompter(select_index_returns=0)
    gen = WPSpin(prompter=fake)
    # a BSSID with no matching OUI table entry at all
    result = gen.promptPin('FF:FF:FF:FF:FF:FF')
    assert not fake.select_index_called
    assert result is None
