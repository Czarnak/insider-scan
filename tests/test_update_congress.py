"""Tests for the Congress member update script."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import responses

# Add scripts/ to path so we can import the module
_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_scripts_dir))

import update_congress  # noqa: E402

SAMPLE_YAML = """
- id:
    bioguide: A000001
  name:
    first: Alice
    last: Smith
    official_full: Alice Smith
  terms:
    - type: sen
      state: CA
      party: Democrat
- id:
    bioguide: B000002
  name:
    first: Bob
    last: Jones
    official_full: Bob Jones
  terms:
    - type: rep
      state: TX
      party: Republican
"""

SAMPLE_OPENSTATES_PAGE1 = {
    "results": [
        {
            "name": "Carlos Rivera",
            "jurisdiction": {"name": "California"},
            "current_role": {"org_classification": "upper"},
            "party": "Democrat",
            "id": "ocd-person/111",
        },
    ],
    "pagination": {"max_page": 1},
}


class TestFetchFederalLegislators:
    @responses.activate
    def test_yaml_source(self):
        responses.add(
            responses.GET,
            update_congress.FEDERAL_URL,
            body=SAMPLE_YAML,
            status=200,
        )
        members = update_congress.fetch_federal_legislators()
        assert len(members) == 2
        assert members[0]["last_name"] == "Smith"
        assert members[0]["chamber"] == "Senate"
        assert members[0]["state"] == "CA"
        assert members[0]["level"] == "federal"
        assert members[1]["chamber"] == "House"
        assert members[1]["state"] == "TX"

    @responses.activate
    def test_yaml_fail_json_fallback(self):
        responses.add(responses.GET, update_congress.FEDERAL_URL, status=500)
        responses.add(
            responses.GET,
            update_congress.FEDERAL_FALLBACK_URL,
            json=[
                {
                    "id": {"bioguide": "C000003"},
                    "name": {"first": "Carol", "last": "Lee", "official_full": "Carol Lee"},
                    "terms": [{"type": "sen", "state": "NY", "party": "Democrat"}],
                }
            ],
            status=200,
        )
        members = update_congress.fetch_federal_legislators()
        assert len(members) == 1
        assert members[0]["last_name"] == "Lee"

    @responses.activate
    def test_both_fail(self):
        responses.add(responses.GET, update_congress.FEDERAL_URL, status=500)
        responses.add(responses.GET, update_congress.FEDERAL_FALLBACK_URL, status=500)
        members = update_congress.fetch_federal_legislators()
        assert members == []

    @responses.activate
    def test_name_format(self):
        responses.add(
            responses.GET,
            update_congress.FEDERAL_URL,
            body=SAMPLE_YAML,
            status=200,
        )
        members = update_congress.fetch_federal_legislators()
        # Name should be "Last First" for congress flagging consistency
        assert members[0]["name"] == "Smith Alice"
        assert members[1]["name"] == "Jones Bob"


class TestFetchStateLegislators:
    @responses.activate
    def test_single_page(self):
        responses.add(
            responses.GET,
            update_congress.OPENSTATES_PEOPLE_URL,
            json=SAMPLE_OPENSTATES_PAGE1,
            status=200,
        )
        members = update_congress.fetch_state_legislators("test-key")
        assert len(members) == 1
        assert members[0]["level"] == "state"
        assert members[0]["chamber"] == "State Senate"

    @responses.activate
    def test_invalid_api_key(self):
        responses.add(
            responses.GET,
            update_congress.OPENSTATES_PEOPLE_URL,
            status=401,
        )
        members = update_congress.fetch_state_legislators("bad-key")
        assert members == []

    @responses.activate
    def test_empty_results(self):
        responses.add(
            responses.GET,
            update_congress.OPENSTATES_PEOPLE_URL,
            json={"results": [], "pagination": {"max_page": 1}},
            status=200,
        )
        members = update_congress.fetch_state_legislators("test-key")
        assert members == []


class TestMergeAndSave:
    def test_save(self, tmp_path):
        out = tmp_path / "members.json"
        federal = [{"name": "Smith Alice", "state": "CA", "level": "federal"}]
        state = [{"name": "Rivera Carlos", "state": "CA", "level": "state"}]
        update_congress.merge_and_save(federal, state, out)
        data = json.loads(out.read_text())
        assert len(data) == 2
        # Federal should come first
        assert data[0]["level"] == "federal"
        assert data[1]["level"] == "state"

    def test_deduplication(self, tmp_path):
        out = tmp_path / "members.json"
        federal = [
            {"name": "Smith Alice", "state": "CA", "level": "federal"},
            {"name": "Smith Alice", "state": "CA", "level": "federal"},
        ]
        update_congress.merge_and_save(federal, [], out)
        data = json.loads(out.read_text())
        assert len(data) == 1

    def test_dry_run(self, tmp_path, capsys):
        out = tmp_path / "members.json"
        update_congress.merge_and_save(
            [{"name": "Test", "state": "CA", "level": "federal"}],
            [],
            out,
            dry_run=True,
        )
        assert not out.exists()
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
