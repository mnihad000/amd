from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FrontendEnterpriseSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec_path = Path("frontend/specs/enterprise-ux.json")
        cls.spec = json.loads(spec_path.read_text(encoding="utf-8"))

    def test_operations_dashboard_spec_covers_required_surfaces(self) -> None:
        operations = self.spec["operations_dashboard"]
        self.assertEqual(
            set(operations["run_list_filters"]),
            {"status", "class", "source_mode", "updated_range", "alert_state", "sla_state"},
        )
        self.assertIn("run_drill_down", operations)
        self.assertIn("stage_diagnostics", operations)
        self.assertIn("failure_root_cause_panes", operations)

    def test_class_review_governance_and_iteration_views_have_artifact_sources(self) -> None:
        self.assertIn("side_by_side_model_or_run", self.spec["class_health_regression_views"]["comparison"])
        self.assertIn("pending_queue", self.spec["label_qa_review_workflow"]["surfaces"])
        self.assertIn("lineage_explorer", self.spec["governance_visibility"]["surfaces"])
        self.assertIn("budget_spend_ratio", self.spec["usage_cost_system_health"]["panels"])
        self.assertIn("selected_action", self.spec["iteration_explainability"]["panels"])

    def test_rbac_matrix_limits_actions_by_role(self) -> None:
        matrix = self.spec["rbac_matrix"]
        self.assertIn("create_run", matrix["Operator"]["actions"])
        self.assertIn("read_monitoring", matrix["Operator"]["actions"])
        self.assertIn("approve_label", matrix["Reviewer"]["actions"])
        self.assertIn("manage_policy", matrix["Admin"]["actions"])
        self.assertIn("rollback", matrix["Admin"]["actions"])
        self.assertIn("review_labels", matrix["Operator"]["denied"])
        self.assertIn("rollback", matrix["Reviewer"]["denied"])
        self.assertEqual(matrix["Admin"]["denied"], [])

    def test_phased_delivery_sequence_preserves_existing_dashboard_flow(self) -> None:
        phases = self.spec["phased_delivery"]
        self.assertEqual([phase["phase"] for phase in phases], [1, 2, 3])
        self.assertIn("operations_dashboard", phases[0]["scope"])
        self.assertIn("label_qa_review_workflow", phases[1]["scope"])
        self.assertIn("rollback_controls", phases[2]["scope"])
        self.assertEqual(self.spec["route_compatibility"]["existing_dashboard_route"], "/app")
        self.assertEqual(self.spec["route_compatibility"]["phase_1_behavior"], "additive_read_only_panels")


if __name__ == "__main__":
    unittest.main()
