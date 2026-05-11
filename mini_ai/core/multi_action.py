"""
multi_action.py – Multi-action batch executor with dependency resolution.

Executes action batches respecting depends_on ordering, running independent
actions in parallel and dependent actions sequentially. Cancels transitive
dependents on failure while continuing independent actions.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 9.7
"""
from __future__ import annotations

import concurrent.futures
from collections import deque
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .logger import get_logger

if TYPE_CHECKING:
    from .executor import ToolExecutor

logger = get_logger("multi_action")


@dataclass
class ActionResult:
    """Result of a single action in a multi-action batch."""
    index: int
    tool: str
    success: bool
    output: str
    cancelled: bool = False


@dataclass
class BatchActionResult:
    """Aggregated result of a multi-action batch execution."""
    results: dict[int, ActionResult] = field(default_factory=dict)
    cancelled: list[int] = field(default_factory=list)

    @property
    def summary(self) -> str:
        succeeded = sum(1 for r in self.results.values() if r.success and not r.cancelled)
        failed = sum(1 for r in self.results.values() if not r.success and not r.cancelled)
        cancelled_count = len(self.cancelled)
        return f"{succeeded} succeeded, {failed} failed, {cancelled_count} cancelled"


class MultiActionExecutor:
    """Executes action batches with dependency resolution.

    Actions without depends_on are run in parallel. Actions with dependencies
    are run sequentially after their dependencies complete. If an action fails,
    all transitive dependents are cancelled while independent actions continue.
    """

    MAX_BATCH_SIZE = 10

    def execute_batch(
        self, actions: list[dict[str, Any]], executor: "ToolExecutor"
    ) -> BatchActionResult:
        """Execute actions respecting depends_on ordering.

        Args:
            actions: List of action dicts, each with at least an "action" key.
                     May include "depends_on" as a list of zero-based indices.
            executor: The ToolExecutor instance to dispatch individual actions.

        Returns:
            BatchActionResult with per-index results and cancelled indices.
        """
        # Reject oversized batches
        if len(actions) > self.MAX_BATCH_SIZE:
            result = BatchActionResult()
            # Return a single error result at index 0 indicating rejection
            result.results[0] = ActionResult(
                index=0,
                tool="batch_error",
                success=False,
                output=(
                    f"Batch rejected: {len(actions)} actions exceeds the "
                    f"maximum batch size of {self.MAX_BATCH_SIZE}."
                ),
            )
            return result

        if not actions:
            return BatchActionResult()

        # Validate dependencies
        valid, error_msg = self._validate_dependencies(actions)
        if not valid:
            result = BatchActionResult()
            result.results[0] = ActionResult(
                index=0,
                tool="batch_error",
                success=False,
                output=f"Invalid dependency structure: {error_msg}",
            )
            return result

        # Get execution layers via topological sort
        layers = self._topological_sort(actions)

        batch_result = BatchActionResult()
        failed_indices: set[int] = set()
        cancelled_indices: set[int] = set()

        # Execute layer by layer (sequential between layers, parallel within)
        for layer in layers:
            # Separate runnable actions from those cancelled due to dependency failure
            runnable: list[int] = []
            for idx in layer:
                if idx in cancelled_indices:
                    continue
                # Check if any dependency has failed
                deps = actions[idx].get("depends_on", [])
                if any(d in failed_indices or d in cancelled_indices for d in deps):
                    # Cancel this action and all its transitive dependents
                    self._cancel_transitive_dependents(
                        idx, actions, cancelled_indices, failed_indices
                    )
                    cancelled_indices.add(idx)
                    batch_result.cancelled.append(idx)
                    batch_result.results[idx] = ActionResult(
                        index=idx,
                        tool=str(actions[idx].get("action", "unknown")),
                        success=False,
                        output="Cancelled: dependency failed",
                        cancelled=True,
                    )
                    continue
                runnable.append(idx)

            if not runnable:
                continue

            # If only one action in this layer, run directly (no thread overhead)
            if len(runnable) == 1:
                idx = runnable[0]
                action_result = self._execute_single(idx, actions[idx], executor)
                batch_result.results[idx] = action_result
                if not action_result.success:
                    failed_indices.add(idx)
                    # Cancel transitive dependents of this failed action
                    newly_cancelled = self._get_transitive_dependents(idx, actions)
                    for c_idx in newly_cancelled:
                        if c_idx not in cancelled_indices:
                            cancelled_indices.add(c_idx)
                            batch_result.cancelled.append(c_idx)
                            batch_result.results[c_idx] = ActionResult(
                                index=c_idx,
                                tool=str(actions[c_idx].get("action", "unknown")),
                                success=False,
                                output="Cancelled: dependency failed",
                                cancelled=True,
                            )
            else:
                # Run independent actions in parallel
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(runnable), 4)
                ) as pool:
                    future_to_idx = {
                        pool.submit(
                            self._execute_single, idx, actions[idx], executor
                        ): idx
                        for idx in runnable
                    }
                    for future in concurrent.futures.as_completed(future_to_idx):
                        idx = future_to_idx[future]
                        try:
                            action_result = future.result()
                        except Exception as exc:
                            action_result = ActionResult(
                                index=idx,
                                tool=str(actions[idx].get("action", "unknown")),
                                success=False,
                                output=f"Execution error: {exc}",
                            )
                        batch_result.results[idx] = action_result
                        if not action_result.success:
                            failed_indices.add(idx)

                # After parallel layer completes, cancel dependents of any failures
                for f_idx in list(failed_indices):
                    newly_cancelled = self._get_transitive_dependents(f_idx, actions)
                    for c_idx in newly_cancelled:
                        if c_idx not in cancelled_indices:
                            cancelled_indices.add(c_idx)
                            batch_result.cancelled.append(c_idx)
                            batch_result.results[c_idx] = ActionResult(
                                index=c_idx,
                                tool=str(actions[c_idx].get("action", "unknown")),
                                success=False,
                                output="Cancelled: dependency failed",
                                cancelled=True,
                            )

        return batch_result

    def _validate_dependencies(self, actions: list[dict[str, Any]]) -> tuple[bool, str]:
        """Check for out-of-range indices and circular dependencies.

        Returns:
            (True, "") if valid, (False, error_message) if invalid.
        """
        n = len(actions)

        # Check for out-of-range indices
        for i, action in enumerate(actions):
            deps = action.get("depends_on", [])
            if not isinstance(deps, list):
                return False, f"Action {i}: depends_on must be a list, got {type(deps).__name__}"
            for dep in deps:
                if not isinstance(dep, int):
                    return False, f"Action {i}: dependency index must be int, got {type(dep).__name__}"
                if dep < 0 or dep >= n:
                    return False, (
                        f"Action {i}: depends_on index {dep} is out of range "
                        f"(valid range: 0 to {n - 1})"
                    )
                if dep == i:
                    return False, f"Action {i}: cannot depend on itself"

        # Check for circular dependencies using DFS
        # Build adjacency list: action -> actions that depend on it
        # For cycle detection, we check if the dependency graph is a DAG
        visited = [0] * n  # 0=unvisited, 1=in_progress, 2=done
        
        def has_cycle(node: int) -> bool:
            if visited[node] == 1:
                return True  # Back edge found = cycle
            if visited[node] == 2:
                return False  # Already fully explored
            
            visited[node] = 1
            deps = actions[node].get("depends_on", [])
            for dep in deps:
                if has_cycle(dep):
                    return True
            visited[node] = 2
            return False

        for i in range(n):
            if visited[i] == 0:
                if has_cycle(i):
                    return False, "Circular dependency detected in action batch"

        return True, ""

    def _topological_sort(self, actions: list[dict[str, Any]]) -> list[list[int]]:
        """Return execution layers (parallel within layer, sequential between).

        Each layer contains action indices that can be executed in parallel.
        Layers are ordered so that all dependencies of actions in layer N
        are satisfied by layers 0..N-1.

        Uses Kahn's algorithm (BFS-based topological sort) to produce layers.
        """
        n = len(actions)

        # Build in-degree count and adjacency (dependents) list
        in_degree = [0] * n
        dependents: dict[int, list[int]] = {i: [] for i in range(n)}

        for i, action in enumerate(actions):
            deps = action.get("depends_on", [])
            in_degree[i] = len(deps)
            for dep in deps:
                dependents[dep].append(i)

        # Start with all nodes that have no dependencies
        layers: list[list[int]] = []
        current_layer = [i for i in range(n) if in_degree[i] == 0]

        while current_layer:
            layers.append(sorted(current_layer))  # Sort for deterministic ordering
            next_layer: list[int] = []
            for node in current_layer:
                for dependent in dependents[node]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_layer.append(dependent)
            current_layer = next_layer

        return layers

    def _execute_single(
        self, index: int, action: dict[str, Any], executor: "ToolExecutor"
    ) -> ActionResult:
        """Execute a single action through the ToolExecutor.

        Args:
            index: The action's position in the batch.
            action: The action dict with "action" key and parameters.
            executor: The ToolExecutor to dispatch to.

        Returns:
            ActionResult with execution outcome.
        """
        tool_name = str(action.get("action", "unknown"))
        try:
            is_final, output = executor.execute(action, assume_yes=True)
            # Parse the output to determine success
            import json
            try:
                parsed = json.loads(output)
                success = parsed.get("success", False)
            except (json.JSONDecodeError, TypeError):
                success = False
            return ActionResult(
                index=index,
                tool=tool_name,
                success=success,
                output=output,
            )
        except Exception as exc:
            logger.error(
                f"Action {index} ({tool_name}) failed with exception",
                operation="multi_action_execute",
                error=exc,
            )
            return ActionResult(
                index=index,
                tool=tool_name,
                success=False,
                output=f"Exception: {exc}",
            )

    def _get_transitive_dependents(
        self, failed_index: int, actions: list[dict[str, Any]]
    ) -> set[int]:
        """Get all indices that transitively depend on the failed action.

        Uses BFS to find all actions reachable through dependency chains
        starting from the failed action.
        """
        n = len(actions)
        # Build forward adjacency: action -> list of actions that depend on it
        dependents: dict[int, list[int]] = {i: [] for i in range(n)}
        for i, action in enumerate(actions):
            for dep in action.get("depends_on", []):
                dependents[dep].append(i)

        # BFS from failed_index
        visited: set[int] = set()
        queue = deque(dependents[failed_index])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for dependent in dependents[node]:
                if dependent not in visited:
                    queue.append(dependent)

        return visited

    def _cancel_transitive_dependents(
        self,
        failed_index: int,
        actions: list[dict[str, Any]],
        cancelled_indices: set[int],
        failed_indices: set[int],
    ) -> None:
        """Mark all transitive dependents of a failed action as cancelled.

        Modifies cancelled_indices in place.
        """
        newly_cancelled = self._get_transitive_dependents(failed_index, actions)
        cancelled_indices.update(newly_cancelled)
