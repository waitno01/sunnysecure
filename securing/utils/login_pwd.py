import httpx

async def login_pwd(session: httpx.AsyncClient, email: str, post_url: str, password: str, ppft: str) -> str:
    # Login with Password
    
    vanguard_response = await session.post(
        url = "https://login.live.com/checkpassword.srf",
        headers = {
            "Accept": "application/json",
            "Content-Type" :"application/json; charset=utf-8"
        },
        json = {
            "checkpaswordflowtoken": "",
            "password": password,
            "username": email
        }
    )

    vanguardflowtoken = vanguard_response.json()["vanguardflowtoken"]
    print(f"Got VanguardFlowtoken ({vanguardflowtoken})")
    password_post = await session.post(
        url = post_url,
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data = {
            "type": 11,
            "login": email,
            "loginfmt": email,
            "passwd": password,
            "PPFT": ppft,
            "vanguardflowtoken": vanguardflowtoken
        },
        follow_redirects = True
    )

    return password_post.text