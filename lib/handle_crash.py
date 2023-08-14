import traceback
import asyncio
import pdb
import sys

TIMEOUT = 5

async def ainput(string: str) -> str:
    await asyncio.get_event_loop().run_in_executor(
            None, lambda s=string: sys.stdout.write(s+' '))
    return await asyncio.get_event_loop().run_in_executor(
            None, sys.stdin.readline)

async def async_input():
    await ainput(f"Press enter in the next {TIMEOUT} seconds to enter the post-mortem debugger...")

async def await_input():
    try:
        await asyncio.wait_for(async_input(), timeout=TIMEOUT)
    except Exception:
        return False
    else:
        return True

async def handle():
    traceback.print_exc()
    if await await_input():
        pdb.post_mortem()
    