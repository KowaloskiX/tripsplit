"""`uv run seed-demo`: creates (or keeps) the demo account and tops its wallet up to 5 000 zł.
Dev/test only — see `app.services.demo_account`."""

from pydantic_settings import BaseSettings, CliApp, SettingsConfigDict

from app.core.config import get_settings
from app.db.client import Database
from app.documents import DOCUMENT_MODELS
from app.services.demo_account import DEMO_EMAIL, DEMO_PASSWORD, seed_demo


class SeedDemo(BaseSettings):
    """CLI settings (pydantic-settings instead of argparse — typed and validated)."""

    model_config = SettingsConfigDict(cli_parse_args=True)

    async def cli_cmd(self) -> None:
        settings = get_settings()
        database = Database.from_settings(settings)
        try:
            await database.init_documents(DOCUMENT_MODELS, create_indexes=False)
            seeded = await seed_demo(database, settings)
        finally:
            await database.dispose()
        state = "created" if seeded.created else "already there"
        print(f"demo account {state}: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        print(
            f"wallet: {seeded.balance_minor / 100:,.2f} zł "
            f"(topped up {seeded.topped_up_minor / 100:,.2f} zł)".replace(",", " ")
        )


def main() -> None:
    CliApp.run(SeedDemo)


if __name__ == "__main__":
    main()
