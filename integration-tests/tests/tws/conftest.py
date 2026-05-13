import os
import subprocess
from pathlib import Path
from typing import AsyncGenerator, Iterator

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from tws_testkit.profile import ArtifactProfile
from tws_testkit.seeder.db.base import DbSeeder
from tws_testkit.seeder.db.mariadb import MariaDbDbSeeder
from tws_testkit.seeder.db.postgres import PostgresDbSeeder
from tws_testkit.seeder.queue.base import QueueSeeder
from tws_testkit.seeder.queue.rabbitmq import RabbitQueueSeeder
from tws_testkit.seeder.queue.sqs import SqsQueueSeeder

# ----------------------------------------
# Artifacts
# ----------------------------------------

repo_root = Path(__file__).parent / "../../.."
artifact_profiles: dict[str, ArtifactProfile] = {
    "rust": ArtifactProfile(
        cwd=repo_root / "tws",
        build_cmd=["cargo", "build"],
        backend_cmd=["target/debug/tws-backend"],
    ),
}

tws_lang = os.environ.get("TWS_LANG", "rust")
if tws_lang not in artifact_profiles:
    raise ValueError(f"TWS_LANG must be one of {sorted(artifact_profiles)}; got {tws_lang!r}")

artifact_profile = artifact_profiles[tws_lang]

# ----------------------------------------
# Docker Compose
# ----------------------------------------

compose_dir = Path(__file__).parent / "../.."
tws_test_profile = os.environ.get("TWS_TEST_PROFILE", "aws")


def _get_host_port(service: str, *, container_port: int) -> str:
    for cmd in (["docker", "compose"], ["docker-compose"]):
        result = subprocess.run(
            [*cmd, "port", service, str(container_port)],
            cwd=compose_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _, port = result.stdout.strip().rsplit(":", 1)
            return port

    raise RuntimeError(f"failed to get host port for {service}:{container_port} — is docker compose running?")


excluded_tables = ["flyway_schema_history"]

# Logical key → broker-specific name. Same set for both profiles.
_queue_keys = {
    "control_standard": "test-tws-control-standard",
    "control_premium": "test-tws-control-premium",
    "compute_standard": "test-tws-compute-standard",
    "compute_premium": "test-tws-compute-premium",
}


queue_seeder: QueueSeeder

if tws_test_profile == "aws":
    postgres_host = "127.0.0.1"
    postgres_port = _get_host_port("postgres", container_port=5432)
    postgres_db_name = "tws-db"
    postgres_user = "tws-admin"
    postgres_password = "tws-admin"
    postgres_url = (
        f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db_name}"
    )

    db_env: dict[str, str] = {
        "TWS_DB_PROVIDER": "postgres",
        "TWS_POSTGRES_HOST": postgres_host,
        "TWS_POSTGRES_PORT": postgres_port,
        "TWS_POSTGRES_DB_NAME": postgres_db_name,
        "TWS_POSTGRES_USER": postgres_user,
        "TWS_POSTGRES_PASSWORD": postgres_password,
    }
    db_seeder: DbSeeder = PostgresDbSeeder(
        engine=create_async_engine(url=postgres_url), excluded_tables=excluded_tables
    )

    sqs_port = _get_host_port("sqs", container_port=9324)
    sqs_endpoint = f"http://127.0.0.1:{sqs_port}"
    # ElasticMQ default URL format: <endpoint>/<account_id>/<queue_name>, account=000000000000.
    queue_urls = {key: f"{sqs_endpoint}/000000000000/{name}" for key, name in _queue_keys.items()}

    queue_env: dict[str, str] = {
        "TWS_QUEUE_PROVIDER": "sqs",
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "x",
        "AWS_SECRET_ACCESS_KEY": "x",
        "TWS_SQS_LOCAL_ENDPOINT_URL": sqs_endpoint,
        "TWS_SQS_CONTROL_STANDARD_QUEUE_URL": queue_urls["control_standard"],
        "TWS_SQS_CONTROL_PREMIUM_QUEUE_URL": queue_urls["control_premium"],
        "TWS_SQS_COMPUTE_STANDARD_QUEUE_URL": queue_urls["compute_standard"],
        "TWS_SQS_COMPUTE_PREMIUM_QUEUE_URL": queue_urls["compute_premium"],
    }
    queue_seeder = SqsQueueSeeder(endpoint_url=sqs_endpoint, queue_urls=queue_urls)

elif tws_test_profile == "onprem":
    mariadb_host = "127.0.0.1"
    mariadb_port = _get_host_port("mariadb", container_port=3306)
    mariadb_db_name = "tws-db"
    mariadb_user = "tws-admin"
    mariadb_password = "tws-admin"
    mariadb_url = f"mysql+asyncmy://{mariadb_user}:{mariadb_password}@{mariadb_host}:{mariadb_port}/{mariadb_db_name}"

    db_env = {
        "TWS_DB_PROVIDER": "mariadb",
        "TWS_MARIADB_HOST": mariadb_host,
        "TWS_MARIADB_PORT": mariadb_port,
        "TWS_MARIADB_DB_NAME": mariadb_db_name,
        "TWS_MARIADB_USER": mariadb_user,
        "TWS_MARIADB_PASSWORD": mariadb_password,
    }
    db_seeder = MariaDbDbSeeder(engine=create_async_engine(url=mariadb_url), excluded_tables=excluded_tables)

    rabbit_host = "127.0.0.1"
    rabbit_port = _get_host_port("rabbitmq", container_port=5672)
    rabbit_user = "tws-admin"
    rabbit_password = "tws-admin"

    queue_env = {
        "TWS_QUEUE_PROVIDER": "rabbitmq",
        "TWS_RABBITMQ_HOST": rabbit_host,
        "TWS_RABBITMQ_PORT": rabbit_port,
        "TWS_RABBITMQ_USER": rabbit_user,
        "TWS_RABBITMQ_PASSWORD": rabbit_password,
        "TWS_RABBITMQ_CONTROL_STANDARD_QUEUE": _queue_keys["control_standard"],
        "TWS_RABBITMQ_CONTROL_PREMIUM_QUEUE": _queue_keys["control_premium"],
        "TWS_RABBITMQ_COMPUTE_STANDARD_QUEUE": _queue_keys["compute_standard"],
        "TWS_RABBITMQ_COMPUTE_PREMIUM_QUEUE": _queue_keys["compute_premium"],
    }
    queue_seeder = RabbitQueueSeeder(
        url=f"amqp://{rabbit_user}:{rabbit_password}@{rabbit_host}:{rabbit_port}/%2F",
        queue_names=_queue_keys,
    )

else:
    raise ValueError(f"unknown TWS_TEST_PROFILE: {tws_test_profile!r} (expected 'aws' or 'onprem')")


# ----------------------------------------
# Fixtures
# ----------------------------------------


@pytest.fixture(name="artifact_profile", autouse=True, scope="package")
def artifact_profile_fixture() -> Iterator[ArtifactProfile]:
    artifact_profile.build()
    yield artifact_profile


@pytest.fixture(name="proc_env", scope="package")
def proc_env_fixture() -> Iterator[dict[str, str]]:
    env: dict[str, str] = {
        **db_env,
        **queue_env,
    }
    yield env


@pytest.fixture(name="db_seeder")
async def db_seeder_fixture() -> AsyncGenerator[DbSeeder]:
    async with db_seeder as seeder:
        yield seeder


@pytest.fixture(name="queue_seeder")
async def queue_seeder_fixture() -> AsyncGenerator[QueueSeeder]:
    async with queue_seeder as seeder:
        yield seeder


@pytest.fixture(scope="session", autouse=True)
async def _close_queue_seeder() -> AsyncGenerator[None]:
    yield
    await queue_seeder.close()
