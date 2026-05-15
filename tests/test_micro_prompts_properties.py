"""
Property-based tests for the Minimal Prompt System.

Uses hypothesis to validate correctness properties defined in the design document.
"""
from hypothesis import given, settings
from hypothesis.strategies import sampled_from, text

from mini_ai.core.micro_prompts import MicroPromptRegistry, PromptAssembler


# Shared fixtures
def _make_assembler() -> PromptAssembler:
    """Create a PromptAssembler with default registry."""
    registry = MicroPromptRegistry()
    return PromptAssembler(registry)


class TestGoalPreservation:
    """Property 3: Goal Preservation

    For any goal string of at least 50 characters and for any valid intent,
    the assembled prompt SHALL contain at least the first 50 characters of the goal.

    **Validates: Requirements 3.2, 3.7**
    """

    @given(
        intent=sampled_from(["TASK", "QUERY", "EDIT", "EXPLORE"]),
        goal=text(min_size=50, max_size=10000),
    )
    @settings(max_examples=200, deadline=None)
    def test_goal_first_50_chars_preserved(self, intent: str, goal: str) -> None:
        """The assembled prompt must contain at least the first 50 characters of the goal."""
        assembler = _make_assembler()
        prompt = assembler.assemble(intent, goal)
        assert goal[:50] in prompt, (
            f"First 50 chars of goal not found in assembled prompt.\n"
            f"Intent: {intent}\n"
            f"Goal prefix: {goal[:50]!r}\n"
            f"Prompt length: {len(prompt)}"
        )
