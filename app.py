from flask import Flask, render_template, request, redirect, session, url_for
import docker
import subprocess
import os
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

client = docker.from_env()

# Simple in-memory user storage (for prototype)
users = {}

# Path to store tmate info
TMATE_DIR = "./tmate_sessions"
os.makedirs(TMATE_DIR, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm = request.form.get("confirm")
        
        # Registration
        if username not in users:
            if password == confirm:
                users[username] = password
            else:
                return "Passwords do not match!"
        
        # Login check
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
    
    username = session["user"]
    
    # Only allow one container per user
    container_name = f"{username}_vps"
    container = None
    try:
        container = client.containers.get(container_name)
    except:
        container = None

    tmate_info = ""
    if container:
        tmate_file = os.path.join(TMATE_DIR, f"{container_name}.txt")
        if os.path.exists(tmate_file):
            with open(tmate_file, "r") as f:
                tmate_info = f.read()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "deploy" and not container:
            container = client.containers.run(
                "ubuntu:latest",  # You can customize image
                name=container_name,
                detach=True,
                tty=True,
                stdin_open=True,
                mem_limit="2g",
                cpu_quota=100000,  # 1 core
                command="/bin/bash"
            )
            # Install tmate inside container
            container.exec_run("apt-get update && apt-get install -y tmate")
            
            # Start tmate session
            result = container.exec_run("tmate -S /tmp/tmate.sock new-session -d")
            # Get tmate SSH connection string
            output = container.exec_run("tmate -S /tmp/tmate.sock display -p '#{tmate_ssh}'").output.decode().strip()
            with open(os.path.join(TMATE_DIR, f"{container_name}.txt"), "w") as f:
                f.write(output)
            tmate_info = output

        elif container:
            if action == "start":
                container.start()
            elif action == "stop":
                container.stop()
            elif action == "restart":
                container.restart()
                # Refresh tmate connection
                container.exec_run("tmate -S /tmp/tmate.sock kill-session || true")
                container.exec_run("tmate -S /tmp/tmate.sock new-session -d")
                output = container.exec_run("tmate -S /tmp/tmate.sock display -p '#{tmate_ssh}'").output.decode().strip()
                with open(os.path.join(TMATE_DIR, f"{container_name}.txt"), "w") as f:
                    f.write(output)
                tmate_info = output
            elif action == "delete":
                container.remove(force=True)
                tmate_info = ""
                container = None

        return redirect(url_for("dashboard"))
    
    return render_template("dashboard.html", tmate=tmate_info, container=container_name if container else None)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
