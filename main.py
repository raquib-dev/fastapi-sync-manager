import os
import platform
from typing import Optional , List
import paramiko
import asyncio
import uvicorn
from fastapi import FastAPI, Request,WebSocket, WebSocketDisconnect, Form, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Text, Enum, ForeignKey, DateTime, desc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import datetime
from fastapi.templating import Jinja2Templates
import configparser
from fastapi.openapi.docs import get_swagger_ui_html,get_swagger_ui_oauth2_redirect_html

# Load config from config.ini
config = configparser.ConfigParser()
config.read('config.ini')

db_user = config['database']['user']
db_password = config['database']['password']
db_host = config['database']['host']
db_port = config['database']['port']
db_name = config['database']['database']

admin_username = config['web_admin']['username']
admin_password = config['web_admin']['password']

# Database connection (MySQL) with optimized connection pool settings
DATABASE_URL = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
engine = create_engine(
    DATABASE_URL,
    pool_size=20,             # Set the number of connections to maintain in the pool
    max_overflow=30,          # Set the number of additional connections allowed beyond pool_size
    pool_timeout=30,          # Set the timeout for getting a connection from the pool (in seconds)
    pool_recycle=1800,        # Set the time (in seconds) to recycle and refresh connections (optional)
    pool_pre_ping=True        # Enable to check if connections are alive before using them
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Initialize FastAPI app
app = FastAPI(docs_url=None)

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Serve static files (CSS, JS, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

# User credentials (admin) from config.ini
user_credentials = {admin_username: admin_password}
logged_in_users = set()

# Database models
class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    hostname = Column(String(255), nullable=False)
    username = Column(String(100), nullable=False)
    password = Column(String(100), nullable=False)

class SyncTask(Base):
    __tablename__ = "sync_tasks"
    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String(255), nullable=False)
    username = Column(String(100), nullable=False)
    password = Column(String(100), nullable=False)
    local_directory_path = Column(String(255), nullable=False)
    remote_directory_path = Column(String(255), nullable=False)
    sudo_commands = Column(Text, nullable=False)
    sudo_commands_executed = Column(Integer, default=0)  # New column to track executed commands
    client_id = Column(Integer, nullable=False)
    status = Column(Enum('pending', 'in_progress', 'completed', 'failed'), default='pending')
    progress = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.now)

class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True, index=True)
    command = Column(String(255), nullable=False)  # Store the command string

Base.metadata.create_all(bind=engine)

# In-memory sync requests for tracking progress
sync_requests = []

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",  
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger/swagger-ui.css",
    )

@app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()

# Serve the index.html page
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    if admin_username not in logged_in_users:
        return RedirectResponse(url="/login")
    return FileResponse('templates/index.html')

# Modern Login page with improved colors and toggle password icon alignment
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login</title>
        <link rel="stylesheet" href="/static/bootstrap/css/4.5.2-bootstrap.min.css">
        <link rel="icon" href="/static/logo.png" type="image/x-icon" />
        <style>
            body {
                background-color: #f0f2f5;  /* Softer background */
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }

            .login-container {
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 10px;
                box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
                max-width: 400px;
                width: 100%;
                text-align: center;
                position: relative; /* Relative positioning for toggle icon */
            }

            .brand {
                font-size: 1.7rem;
                font-weight: bold;
                color: #007bff;  /* Blue for File Sync Manager branding */
                margin-bottom: 2rem;
            }

            h2 {
                color: #333333;  /* Darker color for the Login heading */
                margin-bottom: 2rem;
            }

            .form-control {
                border-radius: 50px;
                font-size: 1rem;
                padding: 0.75rem;
                padding-right: 50px; /* Add space for the toggle icon */
            }

            .btn-primary {
                width: 100%;
                border-radius: 50px;
                padding: 0.75rem;
                font-size: 1.2rem;
                background-color: #007bff; /* Blue button */
                border: none;
                transition: background-color 0.3s ease;
            }

            .btn-primary:hover {
                background-color: #0056b3; /* Darker blue on hover */
            }

            .form-group {
                margin-bottom: 1.5rem;
            }

            /* Styles for the password toggle icon */
            .toggle-password {
                position: absolute;
                top: 50%;
                right: 25px;
                transform: translateY(-50%);
                cursor: pointer;
                font-size: 1.5rem;
                color: #007bff;
            }
        </style>
    </head>
    <body>

        <!-- Centered Login Form -->
        <div class="login-container">
            <div class="brand">File Sync Manager</div>  <!-- Branding in blue -->
            <h2>Login</h2>  <!-- Login heading in darker gray -->
            <form action="/login" method="post">
                <div class="form-group">
                    <input type="text" name="username" class="form-control" placeholder="Username" required>
                </div>
                <div class="form-group position-relative">
                    <input type="password" id="password" name="password" class="form-control" placeholder="Password" required>
                    <span class="toggle-password" onclick="togglePasswordVisibility()">
                        <i class="fas fa-eye" id="togglePasswordIcon"></i>
                    </span>
                </div>
                <button type="submit" class="btn btn-primary">Login</button>
            </form>
        </div>

        <!-- Bootstrap JS (Optional) -->
        <script src="/static/jquery/jquery-3.5.1.min.js"></script>
        <script src="/static/bootstrap/js/4.5.2-bootstrap.bundle.min.js"></script>
        <script src="/static/font-awesome/6.0.0-beta3-all.min.js"></script>

        <script>
            // Toggle password visibility
            function togglePasswordVisibility() {
                const passwordField = document.getElementById('password');
                const togglePasswordIcon = document.getElementById('togglePasswordIcon');
                
                if (passwordField.type === 'password') {
                    passwordField.type = 'text';
                    togglePasswordIcon.classList.remove('fa-eye');
                    togglePasswordIcon.classList.add('fa-eye-slash');
                } else {
                    passwordField.type = 'password';
                    togglePasswordIcon.classList.remove('fa-eye-slash');
                    togglePasswordIcon.classList.add('fa-eye');
                }
            }
        </script>
    </body>
    </html>
    """

# Handle login
@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username in user_credentials and user_credentials[username] == password:
        logged_in_users.add(username)
        return RedirectResponse(url="/login-success", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/invalid-credentials", status_code=status.HTTP_303_SEE_OTHER)

# Invalid credentials page
@app.get("/invalid-credentials", response_class=HTMLResponse)
async def invalid_credentials():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Invalid Credentials</title>
        <!-- Bootstrap for styling -->
        <link rel="stylesheet" href="/static/bootstrap/css/4.5.2-bootstrap.min.css">
        <link rel="icon" href="/static/logo.png" type="image/x-icon" />
        <style>
            body {
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                background-color: #f8f9fa;
                margin: 0;
            }

            .error-container {
                text-align: center;
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 10px;
                box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
                width: 100%;
                max-width: 500px;
            }

            h1 {
                color: #dc3545;
                font-size: 2.5rem;
                margin-bottom: 1.5rem;
            }

            .emoji-container {
                font-size: 4rem;
                margin-bottom: 1.5rem;
            }

            .btn-primary {
                margin-top: 1rem;
            }
        </style>
    </head>
    <body>
        <div class="error-container">
            <div class="emoji-container">😔</div>
            <h1>Invalid Credentials!</h1>
            <p>Oops, the username or password you entered is incorrect.</p>
            <a href="/login" class="btn btn-danger">Try Again</a>
        </div>

        <!-- Bootstrap JS (Optional) -->
        <script src="/static/jquery/jquery-3.5.1.min.js"></script>
        <script src="/static/bootstrap/js/4.5.2-bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """

# Handle successful login redirect
@app.get("/login-success", response_class=HTMLResponse)
async def login_success():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login Successful</title>
        <!-- Bootstrap for styling -->
        <link rel="stylesheet" href="/static/bootstrap/css/4.5.2-bootstrap.min.css">
        <link rel="icon" href="/static/logo.png" type="image/x-icon" />
        <style>
            body {
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                background-color: #f8f9fa;
                margin: 0;
            }

            .success-container {
                text-align: center;
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 10px;
                box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
                width: 100%;
                max-width: 500px;
            }

            h1 {
                color: #28a745;
                font-size: 2.5rem;
                margin-bottom: 1.5rem;
            }

            .emoji-container {
                font-size: 4rem;
                margin-bottom: 1.5rem;
            }

            .thumbs-up {
                animation: blink 2s infinite;
            }

            @keyframes blink {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.2); }
            }
        </style>
    </head>
    <body>
        <div class="success-container">
            <div class="emoji-container thumbs-up">😉👍</div>
            <h1>Login Successful!</h1>
            <p>Redirecting you to your dashboard...</p>
        </div>

        <!-- Redirect after 3 seconds -->
        <script>
            setTimeout(function () {
                window.location.href = "/";
            }, 1500);
        </script>

        <!-- Bootstrap JS (Optional) -->
        <script src="/static/jquery/jquery-3.5.1.min.js"></script>
        <script src="/static/bootstrap/js/4.5.2-bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """

# Logout
@app.get("/logout")
async def logout():
    logged_in_users.discard(admin_username)
    return RedirectResponse(url="/login")

# Sync creation handler
@app.post("/create_sync")
async def create_sync(
        hostname: str = Form(...), 
        username: str = Form(...),
        password: str = Form(...), 
        local_directory_path: str = Form(...),
        remote_directory_path: str = Form(...), 
        sudo_commands: List[str] = Form(...),  # Expecting a list of command IDs
        client_id: int = Form(...), 
        background_tasks: BackgroundTasks = BackgroundTasks()
    ):
    db = SessionLocal()

    # Check if a pending sync task already exists
    existing_task = db.query(SyncTask).filter(
        SyncTask.client_id == client_id,
        SyncTask.local_directory_path == local_directory_path,
        SyncTask.remote_directory_path == remote_directory_path,
        SyncTask.status == 'pending'
    ).first()

    if existing_task:
        return {"message": "Pending sync task already exists", "id": existing_task.id}

    # Convert the list of command IDs to a comma-separated string
    commands_str = ",".join(map(str, sudo_commands))

    # Create a new sync task
    sync_task = SyncTask(
        hostname=hostname, 
        username=username, 
        password=password,
        local_directory_path=local_directory_path, 
        remote_directory_path=remote_directory_path,
        sudo_commands=commands_str,  # Store as comma-separated string
        client_id=client_id, 
        status='pending', 
        progress=0,
        sudo_commands_executed=0
    )
    db.add(sync_task)
    db.commit()

    # Start the sync in the background
    background_tasks.add_task(sync_files_and_commands, sync_task.id)
    return {"message": "Sync request created", "id": sync_task.id}

async def sync_files_and_commands(sync_task_id):
    db = SessionLocal()
    sync_task = db.query(SyncTask).filter(SyncTask.id == sync_task_id, SyncTask.status == 'pending').first()

    if sync_task is None:
        return

    try:
        sync_task.status = 'in_progress'
        db.commit()

        hostname = sync_task.hostname
        username = sync_task.username
        password = sync_task.password
        local_directory_path = sync_task.local_directory_path
        remote_directory_path = sync_task.remote_directory_path
        sudo_commands = sync_task.sudo_commands.split(',')

        # Perform file sync and command execution
        await sync_files(hostname, username, password, local_directory_path, remote_directory_path, sudo_commands, sync_task)

        # Make sure the progress doesn't exceed 100%
        sync_task.progress = min(sync_task.progress, 100)
        sync_task.status = 'completed' if sync_task.progress == 100 else 'failed'
        sync_task.status = 'completed' if sync_task.sudo_commands_executed == len(sudo_commands) else 'failed'

    except Exception as e:
        print(f"Error during sync: {e}")
        sync_task.status = 'failed'
    finally:
        db.commit()

async def sync_files(hostname, username, password, local_directory_path, remote_directory_path, sudo_commands, sync_task):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname, username=username, password=password)

    sftp = ssh.open_sftp()

    # Helper function to ensure that all directories in the path exist
    def ensure_remote_dir_exists(path):
        dirs = path.split('/')
        current_path = ""
        for dir_name in dirs:
            if dir_name:  # avoid empty strings
                current_path += f"/{dir_name}"
                try:
                    sftp.stat(current_path)  # Check if the directory exists
                except FileNotFoundError:
                    sftp.mkdir(current_path)  # Create the directory if it doesn't exist

    # Detect local OS
    local_os = platform.system().lower()  # 'windows', 'linux', 'darwin' (macOS)

    # Detect remote OS by checking for 'uname' command (assuming a Linux-based remote system)
    stdin, stdout, stderr = ssh.exec_command('uname -s')
    remote_os = stdout.read().decode().strip().lower()

    # Normalize local paths based on the local OS
    local_directory_path = os.path.normpath(local_directory_path)

    # If remote OS is Linux-based, normalize the remote path to use forward slashes
    if 'linux' in remote_os or 'unix' in remote_os:
        remote_directory_path = remote_directory_path.replace('\\', '/')  # Ensure correct separator for remote path

    # Ensure the full remote root directory exists
    ensure_remote_dir_exists(remote_directory_path)

    total_files = sum([len(files) for _, _, files in os.walk(local_directory_path)])
    files_synced = 0

    # Create a new session for database operations
    db = SessionLocal()

    try:
        for root, dirs, files in os.walk(local_directory_path):
            # Calculate the relative path and construct the remote path
            relative_path = os.path.relpath(root, local_directory_path)
            
            if relative_path == ".":
                remote_path = remote_directory_path  # Keep the root remote path as is
            else:
                remote_path = os.path.join(remote_directory_path, relative_path)
                if 'linux' in remote_os or 'unix' in remote_os:
                    remote_path = remote_path.replace('\\', '/')  # Normalize to forward slashes for Linux remote

            # Ensure remote directory exists (recursive creation)
            ensure_remote_dir_exists(remote_path)

            # Sync files in the current directory
            for file_name in files:
                local_file_path = os.path.join(root, file_name)
                remote_file_path = os.path.join(remote_path, file_name)
                if 'linux' in remote_os or 'unix' in remote_os:
                    remote_file_path = remote_file_path.replace('\\', '/')  # Normalize to forward slashes

                # Transfer the file
                sftp.put(local_file_path, remote_file_path)

                files_synced += 1
                progress = (files_synced / total_files) * 100

                # Update progress in the database
                task_in_db = db.query(SyncTask).filter(SyncTask.id == sync_task.id).first()
                task_in_db.progress = progress
                sync_task.progress = progress

                # Commit progress update to the database
                db.commit()

                # Simulate delay between file transfers
                await asyncio.sleep(1)

    except Exception as e:
        print(f"Error during file sync: {e}")
        db.rollback()  # Rollback in case of an error

    finally:
        sftp.close()
        ssh.close()
        db.close()  # Close the database session

    # After file sync, run commands (if necessary)
    await run_commands(hostname, username, password, sudo_commands, sync_task)

async def run_commands(hostname, username, password, commands, sync_task):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname, username=username, password=password)

    channel = ssh.invoke_shell()

    total_commands = len(commands)
    commands_executed = 0

    # Create a new session
    db = SessionLocal()

    try:
        for command in commands:
            channel.send(command + '\n')
            while not channel.recv_ready():
                await asyncio.sleep(2)

            output = channel.recv(4096).decode('utf-8')
            print(f"Command: {command}\nOutput:\n{output}")

            # Increase the commands executed counter
            commands_executed += 1

            # Update the sync_task in the database with the current command execution count
            task_in_db = db.query(SyncTask).filter(SyncTask.id == sync_task.id).first()
            task_in_db.sudo_commands_executed = commands_executed
            sync_task.sudo_commands_executed = commands_executed

            # Commit the update to the database after each command
            db.commit()

            await asyncio.sleep(3)
    
    except Exception as e:
        print(f"Error executing commands: {e}")
        db.rollback()  # Rollback in case of any error
    
    finally:
        ssh.close()
        db.close()  # Close the database session

# WebSocket to monitor sync progress
@app.websocket("/ws/{sync_id}")
async def websocket_endpoint(websocket: WebSocket, sync_id: int):
    await websocket.accept()

    db = SessionLocal()
    sync_task = db.query(SyncTask).filter(SyncTask.id == sync_id).first()

    if sync_task:
        try:
            while sync_task.progress < 100 and sync_task.status == 'in_progress':
                await websocket.send_json({
                    "id": sync_task.id,
                    "status": sync_task.status,
                    "progress": sync_task.progress,
                    "sudo_commands_executed": sync_task.sudo_commands.count(",") + 1
                })
                await asyncio.sleep(1)

            # Send the final status
            await websocket.send_json({
                "id": sync_task.id,
                "status": sync_task.status,
                "progress": sync_task.progress
            })
        except WebSocketDisconnect:
            print(f"Client disconnected for sync request {sync_id}")
    await websocket.close()

# Backend code to serve the client creation form and process form submission
# Serve the create-client page using Jinja2 template
@app.get("/create-client", response_class=HTMLResponse)
async def create_client_form(request: Request):
    if admin_username not in logged_in_users:
        return RedirectResponse(url="/login")

    db = SessionLocal()
    clients = db.query(Client).all()  # Fetch all clients
    return templates.TemplateResponse("create_client.html", {"request": request, "clients": clients})

@app.get("/clients")
async def get_clients():
    db = SessionLocal()
    clients = db.query(Client).all()
    return [{"id": client.id, "name": client.name, "hostname": client.hostname, "username": client.username, "password": client.password} for client in clients]

# Backend code to handle form submission for creating a new client
@app.post("/submit-client")
async def submit_client(client_id: Optional[int] = Form(None), name: str = Form(...), hostname: str = Form(...), username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    
    if client_id:  # If client_id is present, we are updating
        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            client.name = name
            client.hostname = hostname
            client.username = username
            client.password = password
            db.commit()

            # Update sync tasks where client_id matches the updated client
            sync_tasks = db.query(SyncTask).filter(SyncTask.client_id == client_id).all()
            for sync_task in sync_tasks:
                sync_task.hostname = hostname
                sync_task.username = username
                sync_task.password = password
            db.commit()

            return {"message": "Client and related sync tasks updated successfully"}

    else:  # Otherwise, we are creating a new client
        new_client = Client(name=name, hostname=hostname, username=username, password=password)
        db.add(new_client)
        db.commit()
        return {"message": "Client created"}
    
@app.get("/client/{client_id}")
async def get_client(client_id: int):
    db = SessionLocal()
    client = db.query(Client).filter(Client.id == client_id).first()
    if client:
        return {
            "id": client.id,
            "name": client.name,
            "hostname": client.hostname,
            "username": client.username,
            "password": client.password
        }
    return {"error": "Client not found"}, 404

@app.delete("/delete-client/{client_id}")
async def delete_client(client_id: int):
    db = SessionLocal()
    # Find the client by id
    client = db.query(Client).filter(Client.id == client_id).first()

    if client:
        # Delete all sync tasks associated with the client
        sync_tasks = db.query(SyncTask).filter(SyncTask.client_id == client_id).all()
        for task in sync_tasks:
            db.delete(task)

        # Delete the client after deleting sync tasks
        db.delete(client)
        db.commit()
        
        return {"message": "Client and associated sync tasks deleted successfully"}

    return {"error": "Client not found"}, 404

@app.get("/logout")
async def logout():
    logged_in_users.discard(admin_username)
    return RedirectResponse(url="/login")

@app.get("/sync-requests")
async def get_sync_requests(filter: str = "all"):
    db = SessionLocal()
    
    # Start by querying all sync tasks and joining with the client table to get client names
    query = db.query(SyncTask, Client.name).join(Client, SyncTask.client_id == Client.id).order_by(SyncTask.id.desc())
    
    # Apply filtering based on the provided filter query parameter
    if filter == "pending":
        query = query.filter(SyncTask.status == "pending")
    elif filter == "in_progress":
        query = query.filter(SyncTask.status == "in_progress")
    elif filter == "completed":
        query = query.filter(SyncTask.status == "completed")
    elif filter == "failed":
        query = query.filter(SyncTask.status == "failed")
    elif filter == "incomplete":
        query = query.filter(SyncTask.status != "completed")  # Exclude completed tasks

    tasks = query.all()

    # Construct the response with the required data
    sync_requests = [{
        "id": task.SyncTask.id,
        "client_name": task.name,  # Client name from the join
        "client_id": task.SyncTask.client_id,
        "status": task.SyncTask.status,
        "progress": task.SyncTask.progress,
        "sudo_commands_executed": task.SyncTask.sudo_commands_executed,
        "total_commands": len(task.SyncTask.sudo_commands.split(','))  # Calculate total commands
    } for task in tasks]

    return sync_requests

@app.post("/retry-sync/{sync_id}")
async def retry_sync_request(sync_id: int, background_tasks: BackgroundTasks):
    db = SessionLocal()
    sync_task = db.query(SyncTask).filter(SyncTask.id == sync_id, SyncTask.status == 'failed').first()

    if sync_task:
        sync_task.status = 'pending'
        sync_task.progress = 0
        sync_task.sudo_commands_executed = 0
        db.commit()

        # Retry the sync in the background
        background_tasks.add_task(sync_files_and_commands, sync_task.id)
        return {"message": "Sync retried"}

    return {"error": "Sync task not found"}, 404

@app.get("/sync-request/{sync_id}")
async def get_sync_request(sync_id: int):
    db = SessionLocal()
    sync_task = db.query(SyncTask).filter(SyncTask.id == sync_id).first()
    if sync_task:
        return {
            "id": sync_task.id,
            "local_directory_path": sync_task.local_directory_path,
            "remote_directory_path": sync_task.remote_directory_path,
            "sudo_commands": sync_task.sudo_commands,
        }
    return {"error": "Sync request not found"}, 404

@app.post("/update-sync/{sync_id}")
async def update_sync_request(sync_id: int, client_id: int = Form(...), local_directory_path: str = Form(...),
                              remote_directory_path: str = Form(...), sudo_commands: str = Form(...)):
    db = SessionLocal()
    sync_task = db.query(SyncTask).filter(SyncTask.id == sync_id).first()

    if sync_task:
        # Update the sync task with the new data
        sync_task.client_id = client_id
        sync_task.local_directory_path = local_directory_path
        sync_task.remote_directory_path = remote_directory_path
        sync_task.sudo_commands = sudo_commands
        db.commit()
        return {"message": "Sync request updated successfully"}
    else:
        return {"error": "Sync request not found"}, 404
    
@app.get("/create-command", response_class=HTMLResponse)
async def create_command_form(request: Request):
    return templates.TemplateResponse("create_command.html", {"request": request})

@app.post("/submit-command")
async def submit_command(command_id: Optional[int] = Form(None), command: str = Form(...)):
    db = SessionLocal()

    # Strip whitespace from the command
    command = command.strip()

    if command_id:  # If command_id is present, we are updating
        cmd = db.query(Command).filter(Command.id == command_id).first()
        if cmd:
            cmd.command = command
            db.commit()
            return {"message": "success", "detail": "Command updated successfully"}
    else:  # Otherwise, we are creating a new command
        # Pre-check if the command already exists
        existing_command = db.query(Command).filter(Command.command == command).first()
        if existing_command:
            return {"message": "danger", "detail": "Command already exists"}

        new_command = Command(command=command)
        db.add(new_command)
        db.commit()
        return {"message": "success", "detail": "Command created"}

@app.get("/commands")
async def get_commands():
    db = SessionLocal()
    commands = db.query(Command).all()
    return [{"id": command.id, "command": command.command} for command in commands]

@app.get("/command/{command_id}")
async def get_command(command_id: int):
    db = SessionLocal()
    cmd = db.query(Command).filter(Command.id == command_id).first()
    if cmd:
        return {"id": cmd.id, "command": cmd.command}
    return {"error": "Command not found"}, 404

@app.delete("/delete-command/{command_id}")
async def delete_command(command_id: int):
    db = SessionLocal()
    cmd = db.query(Command).filter(Command.id == command_id).first()
    if cmd:
        db.delete(cmd)
        db.commit()
        return {"message": "Command deleted"}
    return {"error": "Command not found"}, 404

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9000,reload=True)