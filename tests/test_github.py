import json
from src.ci_triage.github import parse_run

payload = json.load(open("tests/fixtures/runs.json"))
parse_run(payload["workflow_runs"][0])
