import json
from types import SimpleNamespace

from browser_use.replay_cache.recorder import StepRecorder


def _node(**kw):
	"""A stand-in for EnhancedDOMTreeNode carrying only what the recorder reads."""
	defaults = dict(
		node_name="A",
		attributes={"href": "/stocks/nvda/"},
		xpath="/html/body/div/a",
		ax_node=SimpleNamespace(role="link", name="NVDA NVIDIA Corporation Stock"),
		snapshot_node=None,
	)
	defaults.update(kw)
	node = SimpleNamespace(**defaults)
	node.get_meaningful_text_for_llm = lambda: "NVDA NVIDIA Corporation Stock"
	return node


def _action(name, **params):
	return SimpleNamespace(
		model_dump=lambda exclude_none=True: {name: params},
		get_index=lambda: params.get("index"),
	)


def test_records_one_line_per_action(tmp_path):
	trace = tmp_path / "trace.jsonl"
	rec = StepRecorder(trace)
	rec.record(
		step=1,
		url="https://stockanalysis.com/",
		actions=[_action("click", index=2421)],
		results=[SimpleNamespace(error=None)],
		selector_map={2421: _node()},
		duration_s=2.5,
	)
	lines = trace.read_text().strip().splitlines()
	assert len(lines) == 1
	row = json.loads(lines[0])
	assert row["action"]["type"] == "click"
	assert row["action"]["index"] == 2421
	assert row["url"] == "https://stockanalysis.com/"
	assert row["duration_s"] == 2.5


def test_captures_the_signals_history_drops(tmp_path):
	"""ax_role, ax_name and text are the whole reason this lives in browser-use."""
	trace = tmp_path / "trace.jsonl"
	StepRecorder(trace).record(
		step=1,
		url="https://stockanalysis.com/",
		actions=[_action("click", index=2421)],
		results=[SimpleNamespace(error=None)],
		selector_map={2421: _node()},
		duration_s=None,
	)
	el = json.loads(trace.read_text().strip())["element"]
	assert el["ax_role"] == "link"
	assert el["ax_name"] == "NVDA NVIDIA Corporation Stock"
	assert el["text"] == "NVDA NVIDIA Corporation Stock"
	assert el["tag_name"] == "a"          # lowercased from node_name
	assert el["xpath"] == "/html/body/div/a"


def test_records_selector_map_hashes_before_the_action(tmp_path):
	"""The scroll pruning rule needs to know what existed before each step."""
	trace = tmp_path / "trace.jsonl"
	StepRecorder(trace).record(
		step=1,
		url="https://example.com/",
		actions=[_action("scroll", down=True)],
		results=[SimpleNamespace(error=None)],
		selector_map={11: _node(), 12: _node()},
		duration_s=None,
	)
	row = json.loads(trace.read_text().strip())
	assert len(row["selector_map_hashes"]) == 2


def test_records_failure(tmp_path):
	trace = tmp_path / "trace.jsonl"
	StepRecorder(trace).record(
		step=1,
		url="https://example.com/",
		actions=[_action("click", index=99)],
		results=[SimpleNamespace(error="element not found")],
		selector_map={},
		duration_s=None,
	)
	row = json.loads(trace.read_text().strip())
	assert row["success"] is False
	assert row["error"] == "element not found"
	assert row["element"] is None


def test_never_raises_on_a_hostile_node(tmp_path):
	"""A recorder failure must never break the agent loop."""
	trace = tmp_path / "trace.jsonl"

	class Exploding:
		def __getattr__(self, name):
			raise RuntimeError("boom")

	StepRecorder(trace).record(
		step=1,
		url="https://example.com/",
		actions=[_action("click", index=1)],
		results=[SimpleNamespace(error=None)],
		selector_map={1: Exploding()},
		duration_s=None,
	)
	# No exception is the assertion.


def test_from_env_is_none_when_unset(monkeypatch):
	monkeypatch.delenv("OPTEXITY_REPLAY_CACHE_TRACE", raising=False)
	assert StepRecorder.from_env() is None


def test_from_env_builds_a_recorder_when_set(monkeypatch, tmp_path):
	monkeypatch.setenv("OPTEXITY_REPLAY_CACHE_TRACE", str(tmp_path / "t.jsonl"))
	assert StepRecorder.from_env() is not None
