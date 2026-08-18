"""Search result labelling and project scoping (FEAT-007)."""
from pathlib import Path

from meridian.search import format_results, result_label


def _make_spec(specs_dir: Path, feat_id: str, name: str) -> None:
    # feat_display_name() reads the slug from the directory name, not frontmatter.
    slug = name.lower().replace(" ", "_")
    d = specs_dir / f"{feat_id}_{slug}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(
        f"---\nid: {feat_id.lower()}\nname: {name}\nstatus: draft\n---\nBody.\n"
    )


class TestResultLabel:
    def test_local_row_resolves_display_name(self, mock_cfg) -> None:
        _make_spec(mock_cfg.specs_path, "FEAT-003", "Local feature")
        row = {"feat_id": "FEAT-003", "project": "test-project"}
        assert result_label(row, mock_cfg) == "FEAT-003: local feature"

    def test_foreign_row_is_namespaced_not_resolved(self, mock_cfg) -> None:
        """The mis-attribution bug: a foreign FEAT-003 must not borrow the
        local FEAT-003's name."""
        _make_spec(mock_cfg.specs_path, "FEAT-003", "Local feature")
        row = {"feat_id": "FEAT-003", "project": "other-repo"}

        label = result_label(row, mock_cfg)
        assert label == "other-repo/FEAT-003"
        assert "Local feature" not in label

    def test_row_without_project_falls_back_to_feat_id(self, mock_cfg) -> None:
        _make_spec(mock_cfg.specs_path, "FEAT-004", "Another feature")
        row = {"feat_id": "FEAT-004"}
        assert result_label(row, mock_cfg) == "FEAT-004: another feature"

    def test_no_cfg_returns_bare_feat_id(self) -> None:
        assert result_label({"feat_id": "FEAT-009", "project": "x"}) == "FEAT-009"


class TestFormatResults:
    def test_foreign_project_visible_in_output(self, mock_cfg) -> None:
        _make_spec(mock_cfg.specs_path, "FEAT-003", "Local feature")
        results = [{
            "feat_id": "FEAT-003", "project": "other-repo",
            "source_name": "paper.pdf", "chunk_idx": 0,
            "text": "some research text", "_distance": 0.1,
        }]
        out = format_results(results, "query", mock_cfg)
        assert "other-repo/FEAT-003" in out

    def test_empty_results_message(self, mock_cfg) -> None:
        assert "No results" in format_results([], "query", mock_cfg)
