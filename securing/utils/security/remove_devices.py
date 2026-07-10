import httpx


async def remove_devices(session: httpx.AsyncClient, token: str, devices: dict | None):
    if not isinstance(devices, dict):
        print("[~] - No devices payload to remove")
        return

    device_list = devices.get("devices") or []
    if not device_list:
        print("[~] - No devices to remove")
        return

    print(devices)
    last_model = "Unknown"
    for device in device_list:
        if not isinstance(device, dict) or not device.get("id"):
            continue
        last_model = device.get("model") or device.get("id") or "Unknown"
        await session.post(
            url="https://account.microsoft.com/devices/api/disclaim",
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json",
                "__RequestVerificationToken": token,
                "Correlation-Context": (
                    "v=1,ms.b.tel.market=en-US,"
                    "ms.b.qos.rootOperationName=Devices.Disclaim,"
                    "ms.b.tel.scenario=ust.amc.devices.disclaim,"
                    "ms.c.ust.scenarioStep=Index"
                ),
            },
            json={"deviceId": device["id"]},
        )

    print(f"[~] - Removed Device ({last_model})")
