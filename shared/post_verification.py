import discord
import json
import logging


def verification_config():
    with open("config/bot.json") as f:
        data = json.load(f)

    return data.get("post_verification", {})


async def after_verify(interaction: discord.Interaction, mc_name: str = ""):
    config = verification_config()
    actions = config.get("actions", [])
    if not actions:
        return

    guild = interaction.guild
    if not guild:
        return

    member = guild.get_member(interaction.user.id)
    if not member:
        member = await guild.fetch_member(interaction.user.id)

    for action in actions:
        try:
            match action["type"]:
                case "role":
                    id = action.get("role_id", "")
                    if id:
                        role = guild.get_role(int(id))
                        if role:
                            await member.add_roles(role)

                case "message":
                    text = action.get("message_content", "").replace("{username}", mc_name)
                    if text:
                        await interaction.user.send(text)

                case "channel":
                    channel_name = action.get("channel_name", "").replace("{username}", mc_name)
                    permissions = {
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                    }

                    category_id = action.get("channel_category_id", "")
                    category = guild.get_channel(int(category_id)) if category_id else None

                    channel = await guild.create_text_channel(
                        name=channel_name,
                        category=category,
                        overwrites=permissions,
                        reason="Post-verification channel",
                    )

                    title = action.get("channel_embed_title", "").replace("{username}", mc_name)
                    description = action.get("channel_embed_description", "").replace("{username}", mc_name)
                    color = action.get("channel_embed_color", 0x3B89FF)

                    embed = discord.Embed(
                        title=title,
                        description=description,
                        color=color
                    )
                    await channel.send(content=member.mention, embed=embed)
        except discord.Forbidden as e:
            logging.error(f"Post-verification action '{action['type']}' forbidden: {e}")
        except Exception as e:
            logging.error(f"Post-verification action '{action['type']}' failed: {e}")
