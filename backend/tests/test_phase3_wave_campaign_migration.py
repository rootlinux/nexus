from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "021_phase3_wave_campaigns.py"


class Phase3WaveCampaignMigrationTests(unittest.TestCase):
    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION.exists())

    def test_migration_declares_campaign_table_and_lineage_columns(self):
        contents = MIGRATION.read_text()
        self.assertIn('op.create_table(\n        "invite_campaigns"', contents)
        self.assertIn('sa.Column("generated_by_user_id"', contents)
        self.assertIn('sa.Column("campaign_id"', contents)
        self.assertIn('ck_invite_campaigns_per_user_invite_allowance_positive', contents)
        self.assertIn('fk_invite_codes_campaign_id_invite_campaigns', contents)


if __name__ == "__main__":
    unittest.main()
