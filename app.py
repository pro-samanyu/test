from flask import Flask, render_template, request, redirect, session, url_for
import asyncio
import os
import secrets
import subprocess

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

database_file = "database.txt"  # Stores user|container_id|ssh_session
os.makedirs("./tmate_sessions", exist_ok=True)

# Prebuilt Docker image (must build locally)
DOCKER_IMAGE = "ubuntu-22.04-with-tmate"

# Resource limits
MEM_LIMIT = "2g"
CPU_QUOTA = 100000  # 1 CPU

# Max one VPS per user
MAX_VPS = 1

# --- Helper functions ---
def add_to_database(user, container_id, ssh_command):
    with open(database_file, "a") as f:
        f.write(f"{user}|{container_id}|{ssh_command}\n")

def remove_from_database(container_id):
    if not os.path.exists(database_file):
        return
    with open(database_file, "r") as f:
        lines = f.readlines()
    with open(database_file, "w") as f:
        for line in lines:
            if container_id not in line:
                f.write(line)

def get_user_vps(user):
    if not os.path.exists(database_file):
        return None
    with open(database_file, "r") as f:
        for line in f:
            if line.startswith(user):
                parts = line.strip().split("|")
                return {"container_id": parts[1], "ssh": parts[2]}
    return None

async def start_tmate(container_id):
    """Start tmate in container and return SSH session"""
    exec_cmd = await asyncio.create_subprocess_exec(
        "docker", "exec", container_id, "tmate", "-F",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    while True:
        line = await exec_cmd.stdout.readline()
        if not line:
            break
        line = line.decode().strip()
        if "ssh session:" in line:
            return line.split("ssh session:")[1].strip()
    return None

async def create_vps(user):
    """Create a new VPS container"""
    container_id = subprocess.check_output([
        "docker", "run", "-dit",
        "--privileged", "--cap-add=ALL",
        "-m", MEM_LIMIT,
        "--cpu-quota", str(CPU_QUOTA),
        DOCKER_IMAGE,
        "/bin/bash"
    ]).decode().strip()

    ssh = await start_tmate(container_id)
    if ssh:
        add_to_database(user, container_id, ssh)
    return container_id, ssh

async def manage_vps(container_id, action):
    """Start/Stop/Restart container and regenerate SSH"""
    if action == "start":
        subprocess.run(["docker", "start", container_id])
    elif action == "stop":
        subprocess.run(["docker", "stop", container_id])
    elif action == "restart":
        subprocess.run(["docker", "restart", container_id])

    ssh = await start_tmate(container_id)
    if ssh:
        # Update database
        remove_from_database(container_id)
        user = None
        for line in open(database_file):
            if container_id in line:
                user = line.split("|")[0]
                break
        if user:
            add_to_database(user, container_id, ssh)
    return ssh

# --- Routes ---
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm = request.form.get("confirm")

        # Simple registration/login
        if username not in users:
            if password == confirm:
                users[username] = password
            else:
                return "Passwords do not match!"

        if users.get(username) == password:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            return "Invalid credentials!"
    return render_template("login.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    user = session["user"]
    vps = get_user_vps(user)
    ssh_info = vps["ssh"] if vps else ""

    if request.method == "POST":
        action = request.form.get("action")
        if action == "deploy" and not vps:
            container_id, ssh_info = asyncio.run(create_vps(user))
        elif vps and action in ["start", "stop", "restart"]:
            ssh_info = asyncio.run(manage_vps(vps["container_id"], action))
        elif vps and action == "delete":
            subprocess.run(["docker", "rm", "-f", vps["container_id"]])
            remove_from_database(vps["container_id"])
            ssh_info = ""
        return redirect(url_for("dashboard"))

    return render_template("dashboard.html", tmate=ssh_info, container=vps["container_id"] if vps else None)

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    users = {}  # Simple in-memory users
    app.run(host="0.0.0.0", port=5000)
