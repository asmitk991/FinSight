# 🚢 Hosting FinSight with Docker

This project is now "Dockerized," which means you can run the entire application (Frontend, Backend, Redis, and Worker) with a single command on any server that has Docker installed.

## What is Dockerization?
Imagine you are building a house. Without Docker, you have to bring the tools, the wood, the plumbing, and the electricity to the site one by one and hope they all fit. 
With **Docker**, you build the house inside a "shipping container" in the factory. Once it's done, you just drop that container onto the land, and it works perfectly because the plumbing and electricity are already built-in.

**Key Benefits:**
1. **Consistency**: It works exactly the same on your Mac as it does on a Linux cloud server.
2. **Isolation**: The application doesn't interfere with other software on your computer.
3. **Easy Maintenance**: You don't need to manually install Node.js, Python 3.11, or Redis on your server. Docker handles it all internally.

---

## 🚀 How to Start (Deployment)

### 1. Requirements
Ensure you have **Docker** and **Docker Compose** installed on your hosting machine.

### 2. Configure Credentials
Create a `.env` file in the root directory (where `docker-compose.yml` is) and add your Gemini API key:
```env
GEMINI_API_KEY=your_actual_key_here
```

### 3. Launch the App
Open your terminal in the root folder and run:
```bash
docker-compose up -d --build
```
*Wait for a few minutes as it installs dependencies inside the containers.*

### 4. Access the App
* **Web UI**: `http://localhost` (or your server's IP)
* **API Docs**: `http://localhost:8000/docs`

---

## 📂 Understanding the Services

| Service | Role | Purpose |
| :--- | :--- | :--- |
| **Frontend** | React Web UI | The user interface you see in the browser. |
| **Backend** | FastAPI | The "brain" that stores transactions and talks to the AI. |
| **Redis** | Message Broker | A fast memory-store that helps the background workers communicate. |
| **Worker** | Celery OCR | Does the heavy lifting of reading receipt images in the background. |

## 💾 Data Persistence
All your transactions are stored in the `./backend/data` folder on your host machine. Docker "mounts" this folder into the container, so **even if you stop or delete the container, your data remains safe on your hard drive.**

## 🛑 How to Stop
To stop all services:
```bash
docker-compose down
```
