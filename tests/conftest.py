from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def app_client(tmp_path):
    from app import create_app

    db_path = tmp_path / "prostanet_test.db"
    flask_app = create_app(
        {
            "TESTING": True,
            "LOAD_MODEL": False,
            "DB_PATH": str(db_path),
        }
    )

    with flask_app.test_client() as client:
        yield client, db_path
