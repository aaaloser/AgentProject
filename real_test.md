

```bash

$env:MOKIO_TASK_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'API Key' -AsSecureString)).Password

$env:MOKIO_TASK_MODEL = Read-Host '模型名'

$env:MOKIO_TASK_BASE_URL = Read-Host 'Base URL'

Set-Location 'C:\Users\lyf\.codex\worktrees\mokioclaw-stage-b\MokioAgent'

$env:PYTHONPATH = 'src'; & 'D:\envs\codeagent\Scripts\python.exe' -m mokioclaw dashboard --repo 'D:\agent work\project\MokioAgent' --task-root 'D:\agent work\project\MokioAgent-task10-private' --task-image 'sha256:83ff408c0f9ce6007afbc9b468815ae4fbdde79d7a702e4b7eb5ee21c91a72b2' --enable-agent

```