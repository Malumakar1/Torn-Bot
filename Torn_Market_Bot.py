import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
import os

from dotenv import load_dotenv
load_dotenv()

# --- CONFIG ---
api_key = os.getenv("API_KEY")  # YOUR TORN API KEY
bot_token = os.getenv("BOT_TOKEN")  # YOUR DISCORD BOT ID
channel_id = int(os.getenv("CHANNEL_ID"))  # YOUR DISCORD CHANNEL ID
guild_id = int(os.getenv("GUILD_ID"))  # YOUR DISCORD CHANNEL ID

# --- Setup bot ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
desired_qualities = {}  # Format: {item_id: [qualities]}
old_uids = {}
tracking_user_id = None

# --- Torn API Fetcher ---


def fetch_market(item_id):
    url = f"https://api.torn.com/v2/market/{item_id}/itemmarket?bonus=Any&offset=0&comment=Market"
    headers = {
        "accept": "application/json",
        "Authorization": f"ApiKey {api_key}"
    }
    response = requests.get(url, headers=headers)
    return response.json()

# --- Filter for desired qualities ---


def get_matching(data, qualities):
    results = {}
    if "itemmarket" not in data or "listings" not in data["itemmarket"]:
        return results

    for listing in data["itemmarket"]["listings"]:
        uid = listing["item_details"]["uid"]
        stats = listing["item_details"]["stats"]
        quality = stats["quality"]

        if quality in qualities:
            results[uid] = {
                "quality": quality,
                "damage": stats["damage"],
                "accuracy": stats["accuracy"],
                "price": listing["price"]
            }
    return results

# --- Stop Button View ---


class StopButtonView(discord.ui.View):
    def __init__(self, item_id=None):
        super().__init__(timeout=None)
        self.item_id = item_id

    @discord.ui.button(label="🔵 Stop Tracking Item", style=discord.ButtonStyle.danger)
    async def stop_tracking(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.item_id is not None and self.item_id in desired_qualities:
            del desired_qualities[self.item_id]
            del old_uids[self.item_id]
            await interaction.response.send_message(
                f"🛑 Stopped tracking item ID {self.item_id}", ephemeral=False
            )
        else:
            await interaction.response.send_message(
                f"❌ Item is not being tracked or already removed.", ephemeral=True
            )

# --- Slash Command to Start Tracking ---


@bot.tree.command(
    name="track",
    description="Track items with their desired quality values.",
    guild=discord.Object(id=guild_id)
)
@app_commands.describe(
    item_ids="Comma-separated list of item IDs (e.g. 219,220)",
    qualities="Comma-separated list of quality values (e.g. 110.5,112.33)"
)
async def track(interaction: discord.Interaction, item_ids: str, qualities: str):
    global desired_qualities, old_uids, tracking_user_id
    try:
        desired_qualities.clear()
        old_uids.clear()
        tracking_user_id = interaction.user.id

        item_id_list = [int(x.strip()) for x in item_ids.split(",")]
        quality_list = [float(q.strip()) for q in qualities.split(",")]

        for item_id in item_id_list:
            desired_qualities[item_id] = {
                "user_id": interaction.user.id,
                "qualities": quality_list
            }

        for item_id, info in desired_qualities.items():
            quals = info["qualities"]
            data = fetch_market(item_id)
            old_uids[item_id] = get_matching(data, quals)

        if not check_market_loop.is_running():
            check_market_loop.start()

        await interaction.response.send_message(
            f"📦 Tracking started for items {item_id_list} with qualities {quality_list}"
        )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error: Make sure both fields are filled correctly."
        )

# --- Loop: Check Market Every 15s ---


@tasks.loop(seconds=15)
async def check_market_loop():
    global old_uids

    if not desired_qualities:
        return

    channel = bot.get_channel(channel_id)
    if channel is None:
        print("❌ Channel not found. Check channel_id.")
        return

    for item_id, info in desired_qualities.items():
        qualities = info["qualities"]
        user_id = info["user_id"]
        new_data = fetch_market(item_id)
        new_uids = get_matching(new_data, qualities)

        old_items = old_uids.get(item_id, {})
        gone = set(old_items) - set(new_uids)
        still = set(old_items) & set(new_uids)

        for uid in still:
            data = old_items[uid]

            embed = discord.Embed(
                title=f"🟢 Item {item_id} - Quality {data['quality']}",
                description="Still in market.",
                color=0x2ecc71
            )
            embed.add_field(
                name="Price", value=f"${data['price']:,}", inline=True)
            embed.add_field(name="Damage", value=data['damage'], inline=True)
            embed.add_field(name="Accuracy",
                            value=data['accuracy'], inline=True)
            embed.set_footer(text=f"UID: {uid}")

            await channel.send(embed=embed, view=StopButtonView(item_id=item_id))

        for uid in gone:
            data = old_items[uid]

            embed = discord.Embed(
                title=f"🔻 Item {item_id} - Quality {data['quality']}",
                description="Listing has been bought!",
                color=0xe74c3c
            )
            embed.add_field(
                name="Price", value=f"${data['price']:,}", inline=True)
            embed.add_field(name="Damage", value=data['damage'], inline=True)
            embed.add_field(name="Accuracy",
                            value=data['accuracy'], inline=True)
            embed.set_footer(text=f"UID: {uid}")

            await channel.send(content=f"<@{user_id}>", embed=embed, view=StopButtonView(item_id=item_id))

        old_uids[item_id] = new_uids

# --- On Ready: Sync Commands ---


@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=guild_id))
    print(f"✅ Logged in as {bot.user}")

bot.run(bot_token)
