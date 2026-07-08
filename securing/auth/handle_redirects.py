from urllib.parse import quote, unquote
import logging
import httpx
import re

def get_data(response: str) -> dict | None:
    logging.info(f"Getting Live Data: {response[:500]}...")

    urlPost = re.search(r'"urlPost"\s*:\s*"([^"]+)"', response)
    ppft = re.search(r'id=\\"i0327\\" value=\\"([^\\]+)\\"', response)
    if not ppft:
        ppft = re.search(r'"sFT"\s*:\s*"([^"]+)"', response)

    if not urlPost or not ppft:
        return None

    return {
        "urlPost": urlPost.group(1),
        "ppft": quote(ppft.group(1), safe='-*')
    }

async def submit_form(session: httpx.AsyncClient, action_url: str, redirect: str) -> str:
    pprid = re.search(r'name="pprid"[^>]+value="([^"]+)"', redirect).group(1)
    ipt = re.search(r'name="ipt"[^>]+value="([^"]+)"', redirect).group(1)
    
    response = await session.post(
        url = action_url,
        data = {
            "pprid": pprid,
            "ipt": ipt
        },
        follow_redirects=True
    )
    rtext = response.text
    return rtext

# FIDO Passkey interruption
async def handle_fido(session: httpx.AsyncClient, redirect: str) -> dict:
    postBackUrl = re.search(r"""name=['"]postBackUrl['"]\s+value=['"]([^'"]+)['"]""", redirect).group(1)
    formatURL = postBackUrl.replace('&amp;', '&')

    ru = re.search(r'[?&]ru=([^&"]+)', formatURL).group(1)
    
    response = await session.get(unquote(ru), follow_redirects=True)

    return response.text

# Accept Notice Form
async def handle_notice(session: httpx.AsyncClient, action_url: str, redirect: str) -> str:
    cid, actioncode = re.search(
        r'id="correlation_id"\s+value="([^"]+)".*?id="code"\s+value="([^"]+)"',
        redirect,
        re.DOTALL
    ).groups()
    
    acceptNotice = await session.post(
        url = action_url,
        data = {
            "correlation_id": cid,
            "code": actioncode
        }
    )
    postURL = re.search(r"var redirectUrl = '([^']+)';", acceptNotice.text).group(1).replace(r"\\u0026", "&")
    response = await session.post(postURL)

    return response.text

async def handle_redirects(session: httpx.AsyncClient, response: str) -> dict | str | None:
    # Handles Microsofts random form popups
    # Response = Original Form without prrid
    # Redirect = Response after handling form

    try:
        logging.info(f"Redirect Response: {response[:500]}...")
        action_match = re.search(r'action="([^"]+)"', response)
        if not action_match:
            return get_data(response)

        action_url = action_match.group(1)
        logging.info(f"Action URL redirect: {action_url}")
        result = response

        # Family Locked
        if "family" in action_url:
            print(f"[X] - Account is Family Locked")
            return "Family"

        # FIDO passkey interrupt
        if "fido" in action_url or "interrupt/passkey" in action_url:
            print(f"[~] - Handling FIDO")
            fido_page = await submit_form(session, action_url, response)
            logging.info(f"Redirect Response: {fido_page[:500]}...")
            result = await handle_fido(session, fido_page)

        # Accept notice
        elif "privacynotice.account.microsoft.com" in action_url:
            print(f"[~] - Handling Accept Notice Form")
            logging.info(f"Accept Notice Response: {response[:500]}...")
            result = await handle_notice(session, action_url, response)

        # Submit forms with pprid/ipt
        elif "pprid" in response:
            redirect = await submit_form(session, action_url, response)

            print(f"[~] - Handling Accrou Notice Form")
            logging.info(f"Accrou Notice Response: {redirect[:500]}...")

            skip_match = (
                re.search(r'"skip":\s*\{"url"\s*:\s*"([^"]+)"', redirect) or
                re.search(r'"skipUrl"\s*:\s*"([^"]+)"', redirect)
            )
            if skip_match:
                skip_url = skip_match.group(1).replace('\\u0026', '&')
                skip_response = await session.get(skip_url, follow_redirects=True)
                return get_data(skip_response.text)

            cancel_url = re.search(r'"cancel":\s*{\s*"url":\s*"([^"]+)"', redirect)
            if cancel_url:
                response2 = await session.get(cancel_url.group(1), follow_redirects=True)
                logging.info(f"Cancel Notice Response: {response2}")
                return get_data(response2.text)

            result = redirect

        parsed = get_data(result)
        if parsed:
            return parsed
        return get_data(response)

    except Exception as e:
        logging.error(f"Error handling redirect: {e}")
        return get_data(response)
