"""Add general runtime v3 tables without rewriting historical rows."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE general_effect_records (\n\tkey VARCHAR(100) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tvalue VARCHAR(4000) NOT NULL, \n\tPRIMARY KEY (key)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE project_blobs (\n\tid VARCHAR(64) NOT NULL, \n\tcontent BYTEA NOT NULL, \n\tlength INTEGER NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE project_workspaces (\n\tid VARCHAR(36) NOT NULL, \n\tkey VARCHAR(160) NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tprincipal VARCHAR(64) NOT NULL, \n\tinitial_revision VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (key)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE project_revisions (\n\tid VARCHAR(64) NOT NULL, \n\tworkspace_id VARCHAR(36) NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id) REFERENCES project_workspaces (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_project_revisions_workspace_id ON project_revisions (workspace_id)")
    op.execute(
        "\nCREATE TABLE general_runs (\n\trun_id VARCHAR(36) NOT NULL, \n\troot_id VARCHAR(36) NOT NULL, \n\tparent_id VARCHAR(36), \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (run_id), \n\tFOREIGN KEY(run_id) REFERENCES runs (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_general_runs_root_id ON general_runs (root_id)")
    op.execute(
        "\nCREATE TABLE general_operations (\n\tid VARCHAR(160) NOT NULL, \n\trun_id VARCHAR(36) NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES general_runs (run_id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_general_operations_run_id ON general_operations (run_id)")
    op.execute(
        "\nCREATE TABLE general_records (\n\tid VARCHAR(160) NOT NULL, \n\trun_id VARCHAR(36) NOT NULL, \n\tkind VARCHAR(32) NOT NULL, \n\tsequence INTEGER NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (run_id, kind, sequence), \n\tFOREIGN KEY(run_id) REFERENCES general_runs (run_id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_general_records_run_id ON general_records (run_id)")
    op.execute(
        "\nCREATE TABLE project_branches (\n\tid VARCHAR(36) NOT NULL, \n\tworkspace_id VARCHAR(36) NOT NULL, \n\trun_id VARCHAR(36) NOT NULL, \n\thead VARCHAR(64) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workspace_id) REFERENCES project_workspaces (id), \n\tUNIQUE (run_id), \n\tFOREIGN KEY(run_id) REFERENCES general_runs (run_id), \n\tFOREIGN KEY(head) REFERENCES project_revisions (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE general_attempts (\n\tid VARCHAR(160) NOT NULL, \n\toperation_id VARCHAR(160) NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (operation_id, ordinal), \n\tFOREIGN KEY(operation_id) REFERENCES general_operations (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE project_grants (\n\trun_id VARCHAR(36) NOT NULL, \n\tbranch_id VARCHAR(36) NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (run_id), \n\tFOREIGN KEY(run_id) REFERENCES general_runs (run_id), \n\tFOREIGN KEY(branch_id) REFERENCES project_branches (id)\n)\n\n"
    )


def downgrade():
    raise RuntimeError("V3 data must be retained; automatic downgrade is disabled")
