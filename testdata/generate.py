"""Test data generator CLI.

    python -m testdata.generate all
    python -m testdata.generate policies
    python -m testdata.generate claims --scenario all       # or --scenario CLM-006
    python -m testdata.generate textract --mode synthetic
    python -m testdata.generate textract --mode capture --profile aws
    python -m testdata.generate prompts
    python -m testdata.generate verify

Everything is generated offline and deterministically, costs nothing, and is committed to
the repo so CI needs no network. `--mode capture` is the one exception (P15, one-time, real
Textract) and is not needed for local development.
"""

import argparse
import copy
import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "testdata" / "manifest.yaml"
SEEDS_DIR = ROOT / "testdata" / "seeds"

DATA_POLICIES_DIR = ROOT / "data" / "policies"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
FIXTURES_CLAIMS_DIR = FIXTURES_DIR / "claims"
FIXTURES_TEXTRACT_DIR = FIXTURES_DIR / "textract"
FIXTURES_EXPECTED_DIR = FIXTURES_DIR / "expected"
FIXTURES_PROMPTS_DIR = FIXTURES_DIR / "prompts"
FIXTURES_POLICIES_DIR = FIXTURES_DIR / "policies"


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_manifest() -> dict[str, list[dict[str, Any]]]:
    return load_yaml(MANIFEST_PATH)


def load_seeds() -> dict[str, Any]:
    return {
        "members": load_yaml(SEEDS_DIR / "members.yaml"),
        "code_catalog": load_yaml(SEEDS_DIR / "code_catalog.yaml"),
        "policy_wordings": load_yaml(SEEDS_DIR / "policy_wordings.yaml"),
        "prompts": load_yaml(SEEDS_DIR / "prompts.yaml"),
    }


def _index_by(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {record[key]: record for record in records}


def all_scenarios(manifest: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return list(manifest.get("claims", [])) + list(manifest.get("pharmacy", []))


def find_scenario(manifest: dict[str, list[dict[str, Any]]], scenario_id: str) -> dict[str, Any]:
    for scenario in all_scenarios(manifest):
        if scenario["id"] == scenario_id:
            return scenario
    raise SystemExit(f"unknown scenario id: {scenario_id}")


def ground_truth_for(scenario: dict[str, Any], seeds: dict[str, Any]) -> dict[str, Any]:
    members_by_id = _index_by(seeds["members"]["members"], "member_id")
    member = members_by_id[scenario["member_id"]]

    if scenario["domain"] == "claims":
        providers_by_id = _index_by(seeds["members"]["providers"], "provider_id")
        provider = providers_by_id[scenario["provider_id"]]
        return {
            "member_id": member["member_id"],
            "policy_no": member["policy_no"],
            "member_age": member["age"],
            "provider_id": provider["provider_id"],
            "provider_name": provider["name"],
            "network_status": provider["network_status"],
            "service_start_date": scenario["service_start_date"],
            "service_end_date": scenario["service_end_date"],
            "diagnosis_codes": scenario["diagnosis_codes"],
            "procedure_codes": [item["code"] for item in scenario["line_items"]],
            "line_items": scenario["line_items"],
            "claimed_amount": scenario["claimed_amount"],
            "currency": scenario["currency"],
        }

    pharmacies_by_id = _index_by(seeds["members"]["pharmacies"], "pharmacy_id")
    pharmacy = pharmacies_by_id[scenario["pharmacy_id"]]
    return {
        "member_id": member["member_id"],
        "policy_no": member["policy_no"],
        "pharmacy_id": pharmacy["pharmacy_id"],
        "pharmacy_name": pharmacy["name"],
        "service_date": scenario["service_date"],
        "procedure_codes": [item["code"] for item in scenario["line_items"]],
        "line_items": scenario["line_items"],
        "claimed_amount": scenario["claimed_amount"],
        "currency": scenario["currency"],
    }


def _party_for(scenario: dict[str, Any], seeds: dict[str, Any]) -> dict[str, Any]:
    if scenario["domain"] == "claims":
        return _index_by(seeds["members"]["providers"], "provider_id")[scenario["provider_id"]]
    return _index_by(seeds["members"]["pharmacies"], "pharmacy_id")[scenario["pharmacy_id"]]


def cmd_policies(seeds: dict[str, Any]) -> None:
    from testdata.builders.policy_builder import build_all

    build_all(seeds["policy_wordings"], DATA_POLICIES_DIR)
    FIXTURES_POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(DATA_POLICIES_DIR.glob("*.pdf"))
    for pdf_path in pdf_paths:
        shutil.copyfile(pdf_path, FIXTURES_POLICIES_DIR / pdf_path.name)
    print(f"policies: wrote {len(pdf_paths)} PDFs to {DATA_POLICIES_DIR}")


def cmd_claims(manifest: dict[str, Any], seeds: dict[str, Any], scenario_filter: str) -> None:
    from testdata.builders.claim_builder import build_claim_pdf
    from testdata.builders.pharmacy_builder import build_pharmacy_pdf

    FIXTURES_CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURES_EXPECTED_DIR.mkdir(parents=True, exist_ok=True)

    members_by_id = _index_by(seeds["members"]["members"], "member_id")
    scenarios = all_scenarios(manifest)
    if scenario_filter != "all":
        scenarios = [find_scenario(manifest, scenario_filter)]

    for scenario in scenarios:
        member = members_by_id[scenario["member_id"]]
        party = _party_for(scenario, seeds)
        pdf_path = FIXTURES_CLAIMS_DIR / f"{scenario['id']}.pdf"
        if scenario["domain"] == "claims":
            build_claim_pdf(scenario, member, party, pdf_path)
        else:
            build_pharmacy_pdf(scenario, member, party, pdf_path)

        expected = {
            "id": scenario["id"],
            "domain": scenario["domain"],
            "description": scenario["description"],
            "ground_truth": ground_truth_for(scenario, seeds),
            **{k: v for k, v in scenario.get("expected", {}).items()},
        }
        if "validation_failure_code" in scenario:
            expected["validation_failure_code"] = scenario["validation_failure_code"]
        if "duplicate_of" in scenario:
            expected["duplicate_of"] = scenario["duplicate_of"]

        expected_path = FIXTURES_EXPECTED_DIR / f"{scenario['id']}.expected.json"
        expected_text = json.dumps(expected, indent=2, sort_keys=True) + "\n"
        expected_path.write_text(expected_text, encoding="utf-8")

    print(f"claims: wrote {len(scenarios)} PDF(s) + expected outcome file(s)")


def cmd_textract(manifest: dict[str, Any], seeds: dict[str, Any], mode: str, profile: str) -> None:
    FIXTURES_TEXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    members_by_id = _index_by(seeds["members"]["members"], "member_id")

    if mode == "capture":
        _capture_via_real_textract(manifest, seeds, profile)
        return

    from testdata.builders.textract_builder import build_textract_json

    scenarios = all_scenarios(manifest)
    for scenario in scenarios:
        member = members_by_id[scenario["member_id"]]
        party = _party_for(scenario, seeds)
        doc = build_textract_json(scenario, member, party)
        out_path = FIXTURES_TEXTRACT_DIR / f"{scenario['id']}.json"
        out_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"textract: wrote {len(scenarios)} synthetic Textract JSON file(s)")


def _capture_via_real_textract(
    manifest: dict[str, Any], seeds: dict[str, Any], profile: str
) -> None:
    """One-time, real AWS Textract capture (P15). Requires AWS credentials for `profile`."""
    import boto3

    session = boto3.Session(profile_name=profile)
    client = session.client("textract")
    for scenario in all_scenarios(manifest):
        pdf_path = FIXTURES_CLAIMS_DIR / f"{scenario['id']}.pdf"
        if not pdf_path.exists():
            raise SystemExit(
                f"missing PDF for {scenario['id']} — run `claims` before `textract --mode capture`"
            )
        response = client.analyze_document(
            Document={"Bytes": pdf_path.read_bytes()},
            FeatureTypes=["FORMS", "TABLES"],
        )
        out_path = FIXTURES_TEXTRACT_DIR / f"{scenario['id']}.json"
        response_text = json.dumps(response, indent=2, sort_keys=True, default=str) + "\n"
        out_path.write_text(response_text, encoding="utf-8")
    print("textract: captured real Textract responses — commit them, they never need regenerating")


def cmd_prompts(seeds: dict[str, Any]) -> None:
    FIXTURES_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FIXTURES_PROMPTS_DIR / "claim_queries.yaml"
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(seeds["prompts"], f, sort_keys=False, allow_unicode=True)
    print(f"prompts: wrote {out_path}")


def _collect_clause_ids(seeds: dict[str, Any]) -> set[str]:
    return {clause["clause_id"] for clause in seeds["policy_wordings"]["clauses"]}


def cmd_verify(manifest: dict[str, Any], seeds: dict[str, Any]) -> None:
    errors: list[str] = []
    scenarios = all_scenarios(manifest)
    clause_ids = _collect_clause_ids(seeds)

    for scenario in scenarios:
        sid = scenario["id"]
        pdf_path = FIXTURES_CLAIMS_DIR / f"{sid}.pdf"
        textract_path = FIXTURES_TEXTRACT_DIR / f"{sid}.json"
        expected_path = FIXTURES_EXPECTED_DIR / f"{sid}.expected.json"

        if not pdf_path.exists():
            errors.append(f"{sid}: missing PDF at {pdf_path}")
        if not textract_path.exists():
            errors.append(f"{sid}: missing Textract JSON at {textract_path}")
        if not expected_path.exists():
            errors.append(f"{sid}: missing expected outcome at {expected_path}")
            continue

        try:
            textract_doc = json.loads(textract_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{sid}: Textract JSON does not parse: {exc}")
            textract_doc = {}

        if "error" not in textract_doc and "Blocks" not in textract_doc:
            errors.append(f"{sid}: Textract JSON has neither 'Blocks' nor 'error'")

        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        decision = expected.get("decision", {})
        for clause_id in decision.get("citations", []) or []:
            if clause_id not in clause_ids:
                errors.append(f"{sid}: citation '{clause_id}' not found in policy corpus")
        for per_line in decision.get("per_line", []) or []:
            clause_id = per_line.get("clause_id")
            if clause_id is not None and clause_id not in clause_ids:
                errors.append(f"{sid}: per_line clause_id '{clause_id}' not found in policy corpus")

        payable_amount = decision.get("payable_amount")
        per_line = decision.get("per_line") or []
        if payable_amount is not None and per_line:
            line_sum = sum(line["payable"] for line in per_line)
            if line_sum != payable_amount:
                errors.append(
                    f"{sid}: payable_amount {payable_amount} != sum(per_line.payable) {line_sum}"
                )

    if not FIXTURES_PROMPTS_DIR.joinpath("claim_queries.yaml").exists():
        errors.append("missing tests/fixtures/prompts/claim_queries.yaml")

    _verify_regeneration_is_idempotent(manifest, seeds, errors)

    if errors:
        print(f"verify: FAILED with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    print(f"verify: OK — {len(scenarios)} scenarios, all fixtures present and consistent")


def _verify_regeneration_is_idempotent(
    manifest: dict[str, Any], seeds: dict[str, Any], errors: list[str]
) -> None:
    """Rebuilds every artifact into a scratch dir and diffs it byte-for-byte against the
    committed fixtures — same seed must produce the same bytes."""
    global DATA_POLICIES_DIR, FIXTURES_CLAIMS_DIR, FIXTURES_TEXTRACT_DIR
    global FIXTURES_EXPECTED_DIR, FIXTURES_PROMPTS_DIR, FIXTURES_POLICIES_DIR

    committed = {
        "data_policies": DATA_POLICIES_DIR,
        "claims": FIXTURES_CLAIMS_DIR,
        "textract": FIXTURES_TEXTRACT_DIR,
        "expected": FIXTURES_EXPECTED_DIR,
        "prompts": FIXTURES_PROMPTS_DIR,
        "fixture_policies": FIXTURES_POLICIES_DIR,
    }
    saved = copy.copy(committed)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        DATA_POLICIES_DIR = tmp_path / "data_policies"
        FIXTURES_CLAIMS_DIR = tmp_path / "claims"
        FIXTURES_TEXTRACT_DIR = tmp_path / "textract"
        FIXTURES_EXPECTED_DIR = tmp_path / "expected"
        FIXTURES_PROMPTS_DIR = tmp_path / "prompts"
        FIXTURES_POLICIES_DIR = tmp_path / "fixture_policies"
        try:
            cmd_policies(seeds)
            cmd_claims(manifest, seeds, "all")
            cmd_textract(manifest, seeds, "synthetic", "aws")
            cmd_prompts(seeds)

            for label, tmp_dir in [
                ("data/policies", DATA_POLICIES_DIR),
                ("tests/fixtures/claims", FIXTURES_CLAIMS_DIR),
                ("tests/fixtures/textract", FIXTURES_TEXTRACT_DIR),
                ("tests/fixtures/expected", FIXTURES_EXPECTED_DIR),
                ("tests/fixtures/policies", FIXTURES_POLICIES_DIR),
                ("tests/fixtures/prompts", FIXTURES_PROMPTS_DIR),
            ]:
                committed_dir = saved[
                    {
                        "data/policies": "data_policies",
                        "tests/fixtures/claims": "claims",
                        "tests/fixtures/textract": "textract",
                        "tests/fixtures/expected": "expected",
                        "tests/fixtures/policies": "fixture_policies",
                        "tests/fixtures/prompts": "prompts",
                    }[label]
                ]
                if not committed_dir.exists():
                    errors.append(f"regeneration check: {label} was never generated to compare")
                    continue
                comparison = filecmp.dircmp(
                    committed_dir, tmp_dir, ignore=[".gitkeep", "__pycache__"]
                )
                if comparison.left_only or comparison.right_only or comparison.diff_files:
                    errors.append(
                        f"regeneration check: {label} is not byte-identical on regeneration "
                        f"(missing={comparison.right_only}, extra={comparison.left_only}, "
                        f"changed={comparison.diff_files})"
                    )
        finally:
            DATA_POLICIES_DIR = saved["data_policies"]
            FIXTURES_CLAIMS_DIR = saved["claims"]
            FIXTURES_TEXTRACT_DIR = saved["textract"]
            FIXTURES_EXPECTED_DIR = saved["expected"]
            FIXTURES_PROMPTS_DIR = saved["prompts"]
            FIXTURES_POLICIES_DIR = saved["fixture_policies"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m testdata.generate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("all")
    subparsers.add_parser("policies")

    claims_parser = subparsers.add_parser("claims")
    claims_parser.add_argument("--scenario", default="all")

    textract_parser = subparsers.add_parser("textract")
    textract_parser.add_argument("--mode", choices=["synthetic", "capture"], default="synthetic")
    textract_parser.add_argument("--profile", default="aws")

    subparsers.add_parser("prompts")
    subparsers.add_parser("verify")

    args = parser.parse_args(argv)

    manifest = load_manifest()
    seeds = load_seeds()

    if args.command == "all":
        cmd_policies(seeds)
        cmd_claims(manifest, seeds, "all")
        cmd_textract(manifest, seeds, "synthetic", "aws")
        cmd_prompts(seeds)
    elif args.command == "policies":
        cmd_policies(seeds)
    elif args.command == "claims":
        cmd_claims(manifest, seeds, args.scenario)
    elif args.command == "textract":
        cmd_textract(manifest, seeds, args.mode, args.profile)
    elif args.command == "prompts":
        cmd_prompts(seeds)
    elif args.command == "verify":
        cmd_verify(manifest, seeds)


if __name__ == "__main__":
    main(sys.argv[1:])
