"""mtagent v0 entrypoint hint.

v0 has no HTTP routes (those land in v1's C-subsystem spec). Run:

  Terminal 1 (mock server):
    uvicorn dianping.mock_server:mock_app --host 127.0.0.1 --port 9192

  Terminal 2 (tests):
    PYTHONPATH=. pytest tests/ -v

  Manual smoke (requires DASHSCOPE_API_KEY in .env):
    PYTHONPATH=. python -c "
    import asyncio
    from agents.profiler import Profiler
    from agents.planner import Planner
    from agents.context import TripContext
    from dianping.client import DianpingClient
    from dianping.schemas import UserInput

    async def main():
        client = DianpingClient()
        ctx = TripContext.create(user_input=UserInput(free_text='情侣 3 天深圳'))
        profiler = Profiler()
        await profiler.run(ctx)
        planner = Planner(client=client)
        route = await planner.run(ctx)
        print(route.model_dump_json(indent=2))
        await client.close()

    asyncio.run(main())
    "
"""

if __name__ == "__main__":
    import sys

    print(__doc__)
    sys.exit(0)
