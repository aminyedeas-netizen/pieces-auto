"""CLI for testing each module independently."""

import asyncio
import sys


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    match cmd:
        case "decode-vin":
            from src.vin.decoder import decode_vin
            vin = sys.argv[2]
            result = asyncio.run(decode_vin(vin))
            print(f"Make: {result.make}")
            print(f"Model: {result.model}")
            print(f"Year: {result.year}")
            print(f"Engine: {result.engine}")
            print(f"Fuel: {result.fuel}")
            print(f"Confidence: {result.confidence.value}")
            if result.vehicle_id:
                print(f"Vehicle ID: {result.vehicle_id}")
            if result.pa24_full_name:
                print(f"PA24 Name: {result.pa24_full_name}")
            print("---")
            print("Explanation:")
            for line in result.explanation:
                print(f"  > {line}")

        case "init-db":
            from src.db.repository import init_schema
            asyncio.run(init_schema())
            print("Database schema initialized.")

        case "seed":
            from src.db.seed import seed_vehicles
            asyncio.run(seed_vehicles())

        case "stats":
            from src.db.repository import get_stats
            stats = asyncio.run(get_stats())
            for key, val in stats.items():
                print(f"  {key}: {val}")

        case "serve":
            import logging
            import os
            logging.basicConfig(level=logging.INFO)

            from src.telegram.client_bot import build_client_app
            from src.telegram.operator_bot import build_operator_app
            from src.chain import set_operator_app

            operator_chat_id = int(os.environ.get("TELEGRAM_OPERATOR_CHAT_ID") or "0")

            async def _serve():
                # Auto-seed DB from database.json on every startup
                from src.db.repository import init_schema, warmup_pool
                from src.db.seed import seed_vehicles
                await init_schema()
                await seed_vehicles()
                await warmup_pool()

                client_app = build_client_app()
                operator_app = build_operator_app()
                set_operator_app(operator_app, operator_chat_id)

                await client_app.initialize()
                await operator_app.initialize()
                await client_app.start()
                await operator_app.start()

                await client_app.updater.start_polling()
                await operator_app.updater.start_polling()

                print("Both bots running. Press Ctrl+C to stop.")
                try:
                    while True:
                        await asyncio.sleep(1)
                except KeyboardInterrupt:
                    pass
                finally:
                    await client_app.updater.stop()
                    await operator_app.updater.stop()
                    await client_app.stop()
                    await operator_app.stop()
                    await client_app.shutdown()
                    await operator_app.shutdown()
                    from src.chain import close_scraper
                    await close_scraper()

            asyncio.run(_serve())

        case _:
            print("Commands: decode-vin, init-db, seed, stats, serve")


if __name__ == "__main__":
    main()
