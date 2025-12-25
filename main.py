import discord
from discord import app_commands
from discord.ext import commands
from quart import Quart, render_template_string
import aiosqlite
import os
import datetime
import asyncio

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN") 
# Fallback to 5000 if no PORT is set (for local testing)
PORT = int(os.environ.get("PORT", 5000))

LOG_CHANNEL_NAME = 'mod-logs'
BANNED_WORDS = ['badword1', 'badword2', 'idiot', 'scam']

# --- QUART WEB SERVER SETUP ---
app = Quart(__name__)

# HTML Template with Bulma CSS
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>ModBot Dashboard</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bulma@0.9.4/css/bulma.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background-color: #f5f7fa; min-height: 100vh; }
        .hero { background: linear-gradient(to right, #5865F2, #404EED); }
        .card { border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); height: 100%; }
        .log-container { max-height: 600px; overflow-y: auto; }
        .log-entry { padding: 12px; border-bottom: 1px solid #eee; transition: background 0.2s; }
        .log-entry:hover { background-color: #fafafa; }
        .tag.is-action { width: 80px; font-weight: bold; }
    </style>
</head>
<body>
    <section class="hero is-info is-small">
        <div class="hero-body">
            <div class="container">
                <p class="title"><i class="fa-solid fa-robot"></i> ModBot Dashboard</p>
                <p class="subtitle">Live database logs & status</p>
            </div>
        </div>
    </section>

    <div class="container mt-5 px-3">
        <div class="columns">
            <div class="column is-one-third">
                <div class="card">
                    <header class="card-header">
                        <p class="card-header-title"><i class="fa-solid fa-server mr-2"></i> Status</p>
                    </header>
                    <div class="card-content">
                        <nav class="level is-mobile">
                            <div class="level-item has-text-centered">
                                <div>
                                    <p class="heading">Servers</p>
                                    <p class="title">{{ guild_count }}</p>
                                </div>
                            </div>
                            <div class="level-item has-text-centered">
                                <div>
                                    <p class="heading">Ping</p>
                                    <p class="title">{{ latency }}ms</p>
                                </div>
                            </div>
                        </nav>
                        <div class="content has-text-centered is-small mt-4">
                            <span class="tag is-success is-light">System Operational</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="column">
                <div class="card">
                    <header class="card-header">
                        <p class="card-header-title"><i class="fa-solid fa-list mr-2"></i> Audit Log History</p>
                    </header>
                    <div class="card-content p-0 log-container">
                        {% for log in logs %}
                        <div class="log-entry">
                            <span class="tag is-action 
                                {% if log[1] == 'Ban' %}is-danger
                                {% elif log[1] == 'Kick' %}is-warning
                                {% elif log[1] == 'Automod' %}is-dark
                                {% else %}is-info{% endif %}">
                                {{ log[1] }}
                            </span>
                            <span class="has-text-weight-bold ml-2">{{ log[2] }}</span>
                            <span class="is-hidden-mobile">: {{ log[3] }}</span>
                            <div class="is-size-7 has-text-grey mt-1">
                                <i class="far fa-clock"></i> {{ log[4] }}
                                <span class="is-hidden-tablet"> • {{ log[3] }}</span>
                            </div>
                        </div>
                        {% else %}
                        <div class="p-5 has-text-centered has-text-grey">
                            <i class="fa-solid fa-folder-open fa-2x mb-3"></i>
                            <p>No moderation actions recorded yet.</p>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
async def home():
    # Fetch logs from Database
    async with aiosqlite.connect('database.db') as db:
        async with db.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 50") as cursor:
            logs = await cursor.fetchall()

    return await render_template_string(
        DASHBOARD_HTML, 
        guild_count=len(bot.guilds),
        latency=round(bot.latency * 1000) if bot.latency else 0,
        logs=logs
    )

# --- BOT SETUP ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        # 1. Initialize Database
        async with aiosqlite.connect('database.db') as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT,
                    user TEXT,
                    reason TEXT,
                    timestamp TEXT
                )
            """)
            await db.commit()
        print("✅ Database connected.")

        # 2. Start Web Server
        self.loop.create_task(app.run_task(host='0.0.0.0', port=PORT))
        print(f"✅ Dashboard running on port {PORT}")
        
        # 3. Sync Slash Commands
        await self.tree.sync()
        print("✅ Slash commands synced.")

bot = MyBot()

# --- DATABASE HELPER ---
async def log_event(guild, action, user, reason):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Save to SQLite Database
    async with aiosqlite.connect('database.db') as db:
        await db.execute(
            "INSERT INTO logs (action, user, reason, timestamp) VALUES (?, ?, ?, ?)",
            (action, str(user), reason, timestamp)
        )
        await db.commit()

    # 2. Send to Discord Channel
    channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if channel:
        color = discord.Color.red() if action == "Ban" else discord.Color.blue()
        embed = discord.Embed(title=f"Action: {action}", color=color)
        embed.add_field(name="User", value=f"{user} ({user.id})")
        embed.add_field(name="Reason", value=reason)
        embed.set_footer(text=timestamp)
        await channel.send(embed=embed)

# --- SLASH COMMANDS ---

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    if member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ Cannot kick user with equal/higher role.", ephemeral=True)
        return
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {member}", ephemeral=False)
    await log_event(interaction.guild, "Kick", member, reason)

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
    if member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ Cannot ban user with equal/higher role.", ephemeral=True)
        return
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {member}", ephemeral=False)
    await log_event(interaction.guild, "Ban", member, reason)

@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason"):
    await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(f"🤐 Muted {member} for {minutes}m", ephemeral=False)
    await log_event(interaction.guild, "Timeout", member, f"{minutes}m - {reason}")

@bot.tree.command(name="clear", description="Delete messages")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)
    await log_event(interaction.guild, "Clear", interaction.user, f"Deleted {len(deleted)} messages")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You don't have permission!", ephemeral=True)
    else:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)

# --- EVENTS ---

@bot.event
async def on_message(message):
    if message.author.bot: return
    
    if any(word in message.content.lower() for word in BANNED_WORDS):
        await message.delete()
        await message.channel.send(f"{message.author.mention} No bad words!", delete_after=5)
        await log_event(message.guild, "Automod", message.author, f"Said: {message.content[:20]}...")

# --- RUNNER ---
if __name__ == "__main__":
    if not TOKEN:
        print("Error: TOKEN not found in environment variables.")
    else:
        bot.run(TOKEN)
      
