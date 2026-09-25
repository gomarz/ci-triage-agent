"""The agent's sandbox, its loop, the SDK wrapper's requests, and the failure report."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci_triage.agent import MODES, SYSTEM, run_agent
from ci_triage.flake import load_observations
from ci_triage.llm import (
    FALLBACK_BETA,
    AnthropicModel,
    ModelRefused,
    ModelTruncated,
)
from ci_triage.report import build_report
from ci_triage.workspace import TOOL_DEFINITIONS, Workspace
from fakes import FakeSDK, ScriptedModel, call, say, sdk_response


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "shipping.py").write_text("THRESHOLD = 50\n", encoding="utf-8", newline="\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_shipping.py").write_text(
        "assert True\n", encoding="utf-8", newline="\n"
    )
    (root / ".gitignore").write_text("build/\n", encoding="utf-8", newline="\n")
    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.name", "t"],
        ["config", "user.email", "t@t"],
        ["add", "-A"],
        ["commit", "-q", "-m", "base"],
    ):
        git(root, *cmd)
    return root


@pytest.fixture
def ws(repo) -> Workspace:
    return Workspace(
        repo,
        lambda: {
            "passed": False,
            "failed_step": "Test",
            "ran": 3,
            "failures": 1,
            "log_tail": "boom",
        },
    )


# ---- the sandbox ----


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "src/../../secret.txt",
        "/etc/passwd",
        "C:/Windows/win.ini",
        ".git/config",
        "src/.git/x",
        "",
    ],
)
def test_paths_that_leave_the_workspace_are_refused(ws, path):
    for tool, args in [
        ("read_file", {"path": path}),
        ("write_file", {"path": path, "content": "x"}),
        ("delete_file", {"path": path}),
    ]:
        assert ws.execute(tool, args).startswith("error:"), (tool, path)


def test_a_refused_write_leaves_nothing_behind(ws, repo):
    ws.execute("write_file", {"path": "../escaped.txt", "content": "x"})
    assert not (repo.parent / "escaped.txt").exists()


def test_list_files_hides_git_and_lists_the_rest(ws):
    listing = ws.execute("list_files", {}).splitlines()
    assert listing == [".gitignore", "src/shipping.py", "tests/test_shipping.py"]
    assert ws.execute("list_files", {"path": "src"}) == "src/shipping.py"


def test_replace_requires_exactly_one_match(ws):
    assert ws.execute(
        "replace_in_file", {"path": "src/shipping.py", "old": "nope", "new": "x"}
    ).startswith("error: `old` matches 0")
    assert (
        ws.execute("replace_in_file", {"path": "src/shipping.py", "old": "50", "new": "75"})
        == "edited src/shipping.py"
    )
    assert ws.execute("read_file", {"path": "src/shipping.py"}) == "THRESHOLD = 75\n"


def test_unknown_tool_and_bad_arguments_come_back_as_results_not_exceptions(ws):
    assert ws.execute("rm_rf", {}).startswith("error: unknown tool")
    assert ws.execute("read_file", {"nonsense": 1}).startswith("error: bad arguments")


def test_run_ci_reports_the_result_and_counts_calls(ws):
    out = ws.execute("run_ci", {})
    assert out.startswith("CI failed at step 'Test' (ran=3, failures=1)")
    assert ws.ci_runs == 1


# ---- the patch ----


def test_the_diff_is_what_changed_since_baseline_with_lf_endings(ws):
    ws.execute("replace_in_file", {"path": "src/shipping.py", "old": "50", "new": "75"})
    ws.execute("write_file", {"path": "src/new.py", "content": "a = 1\nb = 2\n"})
    ws.execute("delete_file", {"path": "tests/test_shipping.py"})
    diff = ws.diff()

    assert "+THRESHOLD = 75" in diff and "+++ b/src/new.py" in diff
    assert "deleted file mode" in diff
    assert "\r" not in diff


def test_files_that_git_ignores_are_not_part_of_the_patch(ws, repo):
    """A CI run writes build/ output; it must not be mistaken for the agent's work."""
    ws.execute("write_file", {"path": "build/out.json", "content": "{}"})
    assert ws.diff() == ""


def test_the_diff_applies_to_a_clean_copy(ws, repo, tmp_path):
    ws.execute("replace_in_file", {"path": "src/shipping.py", "old": "50", "new": "75"})
    patch = tmp_path / "p.diff"
    patch.write_text(ws.diff(), encoding="utf-8", newline="\n")

    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "src").mkdir()
    (clean / "src" / "shipping.py").write_text("THRESHOLD = 50\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "apply", str(patch)], cwd=clean, check=True)
    assert (clean / "src" / "shipping.py").read_text(encoding="utf-8") == "THRESHOLD = 75\n"


# ---- the loop ----


def test_loop_runs_tools_returns_all_results_in_one_message_and_stops_when_done(ws):
    model = ScriptedModel(
        [
            call(
                ("read_file", {"path": "src/shipping.py"}),
                ("replace_in_file", {"path": "src/shipping.py", "old": "50", "new": "75"}),
            ),
            call(("run_ci", {})),
            say("Raised the threshold."),
        ]
    )
    run = run_agent(model, ws, "FAILURE REPORT", mode="cause")

    assert (run.outcome, run.turns, run.ci_runs) == ("done", 3, 1)
    assert run.summary == "Raised the threshold."
    assert "+THRESHOLD = 75" in run.diff
    # One user message carries both results of the first turn.
    results = model.seen[1][-1]
    assert results["role"] == "user" and len(results["content"]) == 2
    assert {r["tool_use_id"] for r in results["content"]} == {"toolu_0", "toolu_1"}
    assert run.usage.calls == 3


def test_the_task_is_the_mode_plus_the_report_and_nothing_else(ws):
    model = ScriptedModel([say("nothing to do")])
    run_agent(model, ws, "REPORT-BODY", mode="pass")
    assert model.seen[0][0]["content"] == f"{MODES['pass']}\n\nREPORT-BODY"


def test_the_prompt_does_not_tell_the_model_what_not_to_do():
    """A rule against cheating would measure compliance with the rule, not cheating."""
    text = " ".join([SYSTEM, *MODES.values()]).lower()
    for phrase in ("cheat", "do not edit", "don't edit", "do not delete", "do not skip", "honest"):
        assert phrase not in text


def test_a_model_that_never_stops_is_cut_off_but_its_work_is_kept(ws):
    edit = call(("replace_in_file", {"path": "src/shipping.py", "old": "50", "new": "75"}))
    model = ScriptedModel([edit, call(("run_ci", {})), call(("run_ci", {}))])
    run = run_agent(model, ws, "r", max_turns=3)
    assert run.outcome == "max_turns" and "+THRESHOLD = 75" in run.diff


def test_an_error_result_does_not_end_the_run(ws):
    model = ScriptedModel([call(("read_file", {"path": "../x"})), say("gave up")])
    run = run_agent(model, ws, "r")
    assert run.outcome == "done"
    assert run.transcript[0]["tools"][0]["result"].startswith("error:")


def test_a_refusal_ends_the_run_as_refused_not_as_done(ws):
    class Refuses:
        def step(self, *args):
            raise ModelRefused("declined")

    run = run_agent(Refuses(), ws, "r")
    assert run.outcome == "refused" and run.diff == ""


def test_an_unknown_mode_is_rejected(ws):
    with pytest.raises(ValueError):
        run_agent(ScriptedModel(), ws, "r", mode="please")


def test_every_tool_the_model_is_offered_has_a_handler(ws):
    for tool in TOOL_DEFINITIONS:
        assert hasattr(ws, f"_tool_{tool['name']}"), tool["name"]


# ---- the SDK wrapper, against a fake SDK ----


def test_step_sends_the_documented_request_shape():
    sdk = FakeSDK(sdk_response([{"type": "text", "text": "hi"}]))
    model = AnthropicModel(client=sdk)
    turn = model.step("sys", [{"role": "user", "content": "go"}], TOOL_DEFINITIONS)

    [request] = sdk.requests
    assert request["model"] == "claude-opus-5"
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"] == {"effort": "high"}
    assert request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"
    assert request["tools"] is TOOL_DEFINITIONS and request["system"] == "sys"
    assert "temperature" not in request and "budget_tokens" not in str(request)
    assert (turn.text, turn.input_tokens, turn.output_tokens) == ("hi", 11, 7)


def test_step_returns_tool_calls_and_keeps_the_blocks_for_replay():
    blocks = [
        {"type": "thinking", "thinking": ""},
        {"type": "tool_use", "id": "toolu_9", "name": "read_file", "input": {"path": "a.py"}},
    ]
    turn = AnthropicModel(client=FakeSDK(sdk_response(blocks, "tool_use"))).step("s", [], [])
    assert [(c.id, c.name, c.input) for c in turn.tool_calls] == [
        ("toolu_9", "read_file", {"path": "a.py"})
    ]
    assert len(turn.assistant_content) == 2  # thinking block included, unchanged


def test_a_refusal_raises_with_its_category():
    details = type("D", (), {"category": "cyber"})()
    sdk = FakeSDK(sdk_response([], "refusal", stop_details=details))
    with pytest.raises(ModelRefused, match="cyber"):
        AnthropicModel(client=sdk).step("s", [], [])


def test_hitting_max_tokens_raises_instead_of_returning_a_cut_off_answer():
    sdk = FakeSDK(sdk_response([{"type": "text", "text": "{"}], "max_tokens"))
    with pytest.raises(ModelTruncated):
        AnthropicModel(client=sdk).complete_json("s", "u", {"type": "object"})


def test_complete_json_constrains_the_answer_to_the_schema_and_parses_it():
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "additionalProperties": False,
    }
    sdk = FakeSDK(sdk_response([{"type": "text", "text": '{"ok": true}'}]))
    answer, usage = AnthropicModel(client=sdk, effort="low").complete_json("s", "u", schema)

    assert answer == {"ok": True} and (usage.input_tokens, usage.calls) == (11, 1)
    assert sdk.requests[0]["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": schema},
    }


# ---- the failure report, from real log fixtures ----

BRANCH = "seed/s05-unique-skus-order"
RUNS = [(1, "unittest_verbose_pass.txt"), (2, "unittest_verbose_flaky_fail.txt")]


def test_the_report_carries_the_pipelines_findings_including_run_history(make_cache):
    data = make_cache(RUNS, branch=BRANCH)
    report = build_report(data, BRANCH)

    assert "1 failing test(s), 1 distinct root cause(s)" in report
    assert "AssertionError: Lists differ" in report
    assert "test_unique_skus (tests.test_cart.CartTests.test_unique_skus)" in report
    # History overrides the wording: the classifier alone would say regression.
    assert "triage guess: flake (rule: same-commit-pass-and-fail)" in report
    assert "failed in 1 of 2 runs of this same commit" in report
    assert "can be wrong" in report


def test_the_report_without_history_says_what_the_rules_say(make_cache):
    report = build_report(make_cache([RUNS[1]], branch=BRANCH), BRANCH)
    assert "triage guess: regression (rule: assertion)" in report
    assert "history:" not in report


def test_the_report_holds_nothing_from_a_manifest(make_cache):
    report = build_report(make_cache(RUNS, branch=BRANCH), BRANCH).lower()
    for leak in ("seeds/", "manifest", "fix_paths", "cheat", "inject"):
        assert leak not in report


def test_no_failing_run_is_an_error_not_an_empty_report(make_cache):
    data = make_cache([RUNS[0]], branch=BRANCH)
    with pytest.raises(LookupError):
        build_report(data, BRANCH, observations=load_observations(data))
