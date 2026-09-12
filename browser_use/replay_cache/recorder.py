"""Records raw per-step DOM signals to a JSONL trace.

Captures nothing that requires interpretation: no locators, no scoring, no
knowledge of optexity's automation schema. It exists here rather than upstream
because DOMInteractedElement.load_from_enhanced_dom_tree drops ax_node and
element text, and those are gone by the time AgentHistory is returned.

Inert unless OPTEXITY_REPLAY_CACHE_TRACE names a writable path. Every public
entry point swallows exceptions: a recorder failure must never affect the
agent loop.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

TRACE_ENV_VAR = 'OPTEXITY_REPLAY_CACHE_TRACE'


def _element_signals(node) -> dict | None:
	"""Pull the signals a locator scorer needs off a live EnhancedDOMTreeNode."""
	if node is None:
		return None
	ax = getattr(node, 'ax_node', None)
	try:
		text = node.get_meaningful_text_for_llm() or ''
	except Exception:
		text = ''
	bounds = None
	snapshot = getattr(node, 'snapshot_node', None)
	raw_bounds = getattr(snapshot, 'bounds', None) if snapshot else None
	if raw_bounds is not None:
		bounds = {
			'x': getattr(raw_bounds, 'x', 0.0),
			'y': getattr(raw_bounds, 'y', 0.0),
			'width': getattr(raw_bounds, 'width', 0.0),
			'height': getattr(raw_bounds, 'height', 0.0),
		}
	try:
		element_hash = hash(node)
	except Exception:
		element_hash = None
	return {
		'tag_name': (getattr(node, 'node_name', '') or '').lower(),
		'attributes': dict(getattr(node, 'attributes', None) or {}),
		'xpath': getattr(node, 'xpath', '') or '',
		'ax_role': getattr(ax, 'role', None) if ax else None,
		'ax_name': getattr(ax, 'name', None) if ax else None,
		'text': text,
		'bounds': bounds,
		'element_hash': element_hash,
	}


def _action_name_and_params(action) -> tuple[str, dict]:
	dumped = action.model_dump(exclude_none=True)
	if not dumped:
		return 'unknown', {}
	name = next(iter(dumped))
	params = dumped[name] if isinstance(dumped[name], dict) else {}
	return name, params


class StepRecorder:
	def __init__(self, path):
		self.path = Path(path)

	@classmethod
	def from_env(cls) -> 'StepRecorder | None':
		try:
			path = os.environ.get(TRACE_ENV_VAR)
			return cls(path) if path else None
		except Exception as e:
			logger.debug(f'replay-cache recorder disabled: {type(e).__name__}: {e}')
			return None

	def record(self, *, step, url, actions, results, selector_map, duration_s) -> None:
		"""Append one line per action. Never raises."""
		try:
			self.path.parent.mkdir(parents=True, exist_ok=True)
			hashes = []
			for node in (selector_map or {}).values():
				try:
					hashes.append(hash(node))
				except Exception:
					hashes.append(None)
			with open(self.path, 'a', encoding='utf-8') as fh:
				for i, action in enumerate(actions or []):
					try:
						name, params = _action_name_and_params(action)
						index = action.get_index()
					except Exception:
						name, params, index = 'unknown', {}, None
					result = results[i] if results and i < len(results) else None
					error = getattr(result, 'error', None) if result else None
					node = (selector_map or {}).get(index) if index is not None else None
					try:
						element = _element_signals(node)
					except Exception:
						element = None
					row = {
						'step': step,
						'url': url,
						'action': {'type': name, 'index': index, 'params': params},
						'element': element,
						'selector_map_hashes': hashes,
						'success': error is None,
						'error': error,
						'duration_s': duration_s,
					}
					fh.write(json.dumps(row, default=str) + '\n')
		except Exception as e:
			logger.debug(f'replay-cache recorder skipped step {step}: {type(e).__name__}: {e}')
