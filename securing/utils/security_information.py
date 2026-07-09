import logging
import httpx
import html
import re


async def security_information(session: httpx.AsyncClient):
    sec_info = await session.get(
        url="https://account.live.com/proofs/Manage/additional",
    )
    logging.info("Security Info: %s", sec_info.text[:2000])

    match = re.search(
        r"var\s+t0\s*=\s*(\{.*?\});",
        sec_info.text,
        re.DOTALL,
    )

    if not match:
        href_m = re.search(r'href="([^"]+)"', sec_info.text)
        if not href_m:
            raise RuntimeError(
                "security_information: proofs/Manage page missing t0 and href "
                f"(status={sec_info.status_code})."
            )

        url = html.unescape(href_m.group(1))
        response = await session.get(url=url)

        action_m = re.search(r'action="([^"]+)"', response.text)
        pprid_m = re.search(r'name="pprid"[^>]*value="([^"]+)"', response.text)
        nap_m = re.search(r'name="NAP"[^>]*value="([^"]+)"', response.text)
        anon_m = re.search(r'name="ANON"[^>]*value="([^"]+)"', response.text)
        t_m = re.search(r'name="t"[^>]*value="([^"]+)"', response.text)
        if not (action_m and pprid_m and nap_m and anon_m and t_m):
            raise RuntimeError(
                "security_information: SSO continue form incomplete after proofs redirect."
            )

        response = await session.post(
            url=action_m.group(1),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "pprid": pprid_m.group(1),
                "NAP": nap_m.group(1),
                "ANON": anon_m.group(1),
                "t": t_m.group(1),
            },
            follow_redirects=True,
        )

        logging.info("Security Info after SSO: %s", response.text[:2000])
        match = re.search(
            r"var\s+t0\s*=\s*(\{.*?\});",
            response.text,
            re.DOTALL,
        )

    if not match:
        raise RuntimeError("security_information: could not find var t0= on proofs page.")

    return match.group(1)
