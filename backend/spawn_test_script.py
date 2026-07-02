# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
import json
from app.container.spawner import spawner

async def test():
    try:
        server = await spawner.spawn(
            user_id="35ef958f-0fd9-4f33-a007-88ab88023d39",
            username="admin",
            server_name="test-server",
            environment="dev",
            cpu=1,
            memory="512m",
        )
        print("SUCCESS!")
        print(json.dumps({
            "id": str(server.id),
            "name": server.name,
            "status": server.status,
            "container_id": server.container_id,
            "external_url": server.external_url,
        }, indent=2))
    except Exception as e:
        print(f"ERROR: {e}")

asyncio.run(test())
