import asyncio
import os
from app.iq_ws import get_candles


async def main() -> None:
    email = os.environ["IQ_OPTION_EMAIL"].strip()
    password = os.environ["IQ_OPTION_PASSWORD"]
    print("IQ_LOGIN_TEST=started")
    for label, active_id in (("NORMAL", 1), ("OTC", 76)):
        try:
            candles = await get_candles(email, password, active_id, 60, 5)
            print(f"{label}_CANDLES={len(candles)}")
        except Exception as error:
            print(f"{label}_ERROR={type(error).__name__}: {str(error)[:180]}")
    print("IQ_LOGIN_TEST=finished")


asyncio.run(main())
