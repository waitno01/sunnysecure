module.exports = {
  apps: [
    {
      name: "autosecure-api",
      cwd: "/root/autosecure",
      script: ".venv/bin/python",
      args: "-m uvicorn app:app --host 127.0.0.1 --port 8000 --app-dir web",
      env: {
        // API stays localhost-only; Nitro proxies /api from the public UI
        CORS_ORIGINS:
          "http://127.0.0.1:3000,http://localhost:3000,http://208.84.101.140:3000",
      },
      autorestart: true,
      max_restarts: 10,
    },
    {
      name: "autosecure-web",
      cwd: "/root/autosecure",
      script: "node",
      args: "web/.output/server/index.mjs",
      env: {
        NITRO_HOST: "0.0.0.0",
        HOST: "0.0.0.0",
        PORT: "3000",
        NITRO_PORT: "3000",
      },
      autorestart: true,
      max_restarts: 10,
    },
    {
      name: "autosecure-bot",
      cwd: "/root/autosecure",
      script: ".venv/bin/python",
      args: "bot.py",
      autorestart: true,
      max_restarts: 10,
    },
  ],
};
